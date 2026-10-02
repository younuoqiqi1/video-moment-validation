import hashlib
import json
import math
from pathlib import Path
import re

from vmv.retrieval import document_hash
from vmv.script import _split_paragraphs
from vmv.production_validation import (
    canonical_shot_id, canonical_times, require_source_hash,
    require_paragraph_mapping, require_positive_trim,
)

def _num(v):
    return type(v) in (int, float) and not isinstance(v, bool) and math.isfinite(v)


def _safe_ascii(v):
    return isinstance(v, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]+", v))


def validate_inputs(s, d, c, r, m):
    try:
        if not all(isinstance(x, dict) for x in (s, d, c, r, m)):
            raise ValueError("All inputs (s, d, c, r, m) must be dictionaries")

        d_sha, r_sha = d.get("document_sha256"), r.get("document_sha256")
        if not isinstance(d_sha, str) or not d_sha or d_sha != r_sha:
            raise ValueError("document_sha256 must match between d and r")
        doc_h = document_hash(d)
        doc_h = doc_h.hexdigest() if hasattr(doc_h, "hexdigest") else doc_h
        if doc_h != d_sha:
            raise ValueError("document_hash(d) does not match document_sha256")

        sample = s.get("sample")
        if type(sample) is not bool:
            raise ValueError("sample must be exact bool")
        for name, obj in (("document", d), ("catalog", c), ("selection", r)):
            if type(obj.get("sample")) is not bool or obj.get("sample") is not sample:
                raise ValueError(f"{name} sample must be exact bool matching script")

        if s.get("state") != "confirmed":
            raise ValueError("script state must be confirmed")
        st = s.get("source_text")
        if not isinstance(st, str):
            raise ValueError("script source_text must be str")
        require_source_hash(s)

        s_segs = s.get("segments")
        if not isinstance(s_segs, list) or not s_segs:
            raise ValueError("script segments must be non-empty list")
        split_paras = _split_paragraphs(st)
        if not isinstance(split_paras, list) or len(s_segs) != len(split_paras):
            raise ValueError("script segments count must match split paragraphs")

        d_segs, r_segs = d.get("segments"), r.get("segments")
        if not isinstance(d_segs, list) or not isinstance(r_segs, list):
            raise ValueError("doc and selection segments must be lists")
        if len(d_segs) != len(s_segs) or len(r_segs) != len(s_segs):
            raise ValueError("segment counts must match across script, doc, and selection")

        for idx, (s_seg, para, d_seg, r_seg) in enumerate(zip(s_segs, split_paras, d_segs, r_segs), start=1):
            exp_id = f"seg-{idx:03d}"
            if not all(isinstance(x, dict) for x in (s_seg, d_seg, r_seg)):
                raise ValueError("segments must be dicts")
            if s_seg.get("id") != exp_id or d_seg.get("id") != exp_id or r_seg.get("id") != exp_id:
                raise ValueError(f"segment IDs must match {exp_id}")
            if s_seg.get("status") != "confirmed":
                raise ValueError("script segment status must be confirmed")
            start, end = s_seg.get("start"), s_seg.get("end")
            if type(start) is not int or type(end) is not int or isinstance(start, bool) or isinstance(end, bool) or not (0 <= start < end <= len(st)):
                raise ValueError("segment start/end must be valid exact ints")
            narration = s_seg.get("narration")
            if not isinstance(narration, str) or st[start:end] != narration:
                raise ValueError("narration must match source_text range")
            require_paragraph_mapping(s_seg, para)
            if d_seg.get("narration") != narration:
                raise ValueError("doc narration must match script")

        m_data = m.get("media") if isinstance(m.get("media"), dict) else m
        c_mid, d_mid, m_mid = c.get("media_id"), d.get("media_id"), m_data.get("media_id")
        if not _safe_ascii(c_mid) or c_mid != d_mid or c_mid != m_mid:
            raise ValueError("media_id must be safe ASCII and match across catalog, doc, and manifest")

        c_dur, m_dur = c.get("duration_sec"), m_data.get("duration_sec")
        if not _num(c_dur) or not _num(m_dur) or c_dur <= 0 or m_dur <= 0:
            raise ValueError("duration_sec must be positive finite numbers")
        if not math.isclose(c_dur, m_dur, abs_tol=1e-6):
            raise ValueError("catalog duration_sec must match manifest duration_sec")

        c_sha = c.get("source_sha256")
        if not isinstance(c_sha, str) or not re.match(r"^[0-9a-f]{64}$", c_sha):
            raise ValueError("catalog source_sha256 must be lowercase 64 hex")
        m_sha = m_data.get("source_sha256")
        if m_sha is not None and m_sha != c_sha:
            raise ValueError("manifest source_sha256 must match catalog")

        rel_path = m_data.get("relative_path")
        if not isinstance(rel_path, str) or not rel_path.strip() or "\\" in rel_path or ":" in rel_path:
            raise ValueError("manifest relative_path must be non-empty relative path without \\ or :")
        rp = Path(rel_path)
        if rp.is_absolute() or rel_path.startswith("/") or ".." in rp.parts:
            raise ValueError("relative_path cannot be absolute or contain ..")

        c_shots = c.get("shots")
        if not isinstance(c_shots, list) or not c_shots:
            raise ValueError("catalog shots must be non-empty list")
        cat_map = {}
        for cs in c_shots:
            if not isinstance(cs, dict):
                raise ValueError("catalog shot must be dict")
            sid = canonical_shot_id(dict(cs, shot_id=cs.get("shot_id", cs.get("id"))))
            if not _safe_ascii(sid) or sid in cat_map:
                raise ValueError("catalog shot ID must be unique safe ASCII")
            sin, sout = cs.get("start_sec"), cs.get("end_sec")
            if not _num(sin) or not _num(sout) or not (0 <= sin < sout <= c_dur):
                raise ValueError("catalog shot range invalid")
            cat_map[sid] = (sin, sout)

        for d_seg, r_seg in zip(d_segs, r_segs):
            cands = d_seg.get("candidates")
            if not isinstance(cands, list) or not cands:
                raise ValueError("candidates must be non-empty list")
            cand_map = {}
            for cand in cands:
                cid = canonical_shot_id(cand)
                if not _safe_ascii(cid) or cid in cand_map or cid not in cat_map:
                    raise ValueError("candidate ID invalid or not in catalog")
                cin, cout = cand.get("start_sec"), cand.get("end_sec")
                if not _num(cin) or not _num(cout) or cin < 0 or (cin, cout) != cat_map[cid]:
                    raise ValueError("candidate ranges must exact match catalog shot")
                cand_map[cid] = (cin, cout)

            sels = r_seg.get("selected_shots") if "selected_shots" in r_seg else r_seg.get("shots")
            if not isinstance(sels, list) or not sels:
                raise ValueError("selected shots must be non-empty list")
            chosen_seen = set()
            for sel in sels:
                chid = canonical_shot_id(sel)
                if not _safe_ascii(chid) or chid in chosen_seen or chid not in cand_map:
                    raise ValueError("chosen shot ID invalid or missing from candidates")
                chosen_seen.add(chid)
                sin, sout = canonical_times(sel)
                require_positive_trim(sin, sout)
                oin, oout = cand_map[chid]
                if not (oin <= sin < sout <= oout):
                    raise ValueError("selected shot range not within candidate range")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Malformed input: {exc}") from exc


def build_production_order(s, d, c, r, m, source_bindings=None):
    validate_inputs(s, d, c, r, m)
    m_data = m.get("media") if isinstance(m.get("media"), dict) else m
    current_time = 0.0
    out_segments = []

    for s_seg, r_seg in zip(s["segments"], r["segments"]):
        seg_shots = []
        sels = r_seg.get("selected_shots") if "selected_shots" in r_seg else r_seg.get("shots")
        for sel in sels:
            shot_id = canonical_shot_id(sel)
            sin, sout = require_positive_trim(*canonical_times(sel))
            dur = round(sout - sin, 6)
            tin, tout = round(current_time, 6), round(current_time + dur, 6)
            current_time = tout
            seg_shots.append({
                "shot_id": shot_id,
                "source_in_sec": sin,
                "source_out_sec": sout,
                "timeline_in_sec": tin,
                "timeline_out_sec": tout,
            })
        out_segments.append({"id": s_seg["id"], "narration": s_seg["narration"], "shots": seg_shots})

    order = {
        "state": "ready_for_tts",
        "sample": s["sample"],
        "media_id": c["media_id"],
        "source_sha256": c["source_sha256"],
        "source_path": m_data["relative_path"],
        "document_sha256": d["document_sha256"],
        "timing_basis": "source_clip_duration_not_voice",
        "duration_sec": round(current_time, 6),
        "segments": out_segments,
    }
    if source_bindings is not None:
        order["source_bindings"] = source_bindings
    return order


def write_order(script_path, candidates_path, catalog_path, selection_path, media_path, output_path):
    ps, pd, pc, pr, pm, po = [Path(p) for p in (script_path, candidates_path, catalog_path, selection_path, media_path, output_path)]
    s_bytes, d_bytes, c_bytes, r_bytes, m_bytes = ps.read_bytes(), pd.read_bytes(), pc.read_bytes(), pr.read_bytes(), pm.read_bytes()
    s, d, c, r, m = [json.loads(b.decode("utf-8")) for b in (s_bytes, d_bytes, c_bytes, r_bytes, m_bytes)]

    s_sha = hashlib.sha256(s_bytes).hexdigest()
    c_sha = hashlib.sha256(c_bytes).hexdigest()
    if not isinstance(d, dict) or d.get("script_sha256") != s_sha or d.get("catalog_sha256") != c_sha:
        raise ValueError("script/catalog byte sha256 mismatch with document bindings")

    source_bindings = {
        "script_sha256": s_sha,
        "catalog_sha256": c_sha,
        "candidate_file_sha256": hashlib.sha256(d_bytes).hexdigest(),
        "document_sha256": d.get("document_sha256"),
        "selection_sha256": hashlib.sha256(r_bytes).hexdigest(),
        "media_manifest_sha256": hashlib.sha256(m_bytes).hexdigest(),
    }
    order = build_production_order(s, d, c, r, m, source_bindings=source_bindings)

    po.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(order, ensure_ascii=False, indent=2, allow_nan=False)
    with open(po, "x", encoding="utf-8") as f:
        f.write(payload)
    return order
