"""Retrieval and candidate ranking for VMV pipeline."""
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Dict, List

from vmv.generation_process import run_generation


def _bigrams(text: str) -> set:
    t = re.sub(r"\s+", "", str(text or ""))
    return {t[i : i + 2] for i in range(len(t) - 1)} if len(t) > 1 else set()


def rank_candidates(requirement: Any, shots: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    if isinstance(requirement, dict):
        parts = [requirement.get(k, "") for k in ("characters", "setting", "action", "emotion", "visual_requirement")]
        req_text = "".join(str(p or "") for p in parts)
    else:
        req_text = str(requirement or "")
    req_bi = _bigrams(req_text)
    if not req_bi:
        return []
    results, seen = [], set()
    for s in shots:
        sid = s["id"]
        if sid in seen:
            continue
        shot_text = str(s.get("caption") or "") + str(s.get("subtitle") or "")
        overlap = req_bi & _bigrams(shot_text)
        if overlap:
            seen.add(sid)
            results.append({
                "shot_id": sid,
                "start_sec": s["start_sec"],
                "end_sec": s["end_sec"],
                "score": len(overlap),
                "reason": f"词语匹配基线：{len(overlap)}组相邻字重合",
            })
    results.sort(key=lambda x: (-x["score"], str(x["shot_id"])))
    return results[:max(0, min(3, limit))]


def verify_visual_file(path, runner=None):
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("媒体输出为空，未交付")
    result = (runner or run_generation)(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=nb_read_frames,width,height", "-of", "json", str(path)], timeout=60)
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams or int(streams[0].get("nb_read_frames", 0)) < 1 or int(streams[0].get("width", 0)) < 1 or int(streams[0].get("height", 0)) < 1:
        raise ValueError("媒体输出没有可解码画面，未交付")


def _is_num(val: Any) -> bool:
    return type(val) in (int, float) and type(val) is not bool and math.isfinite(val)


def _validate_inputs(script: dict, catalog: dict, video_path: str) -> None:
    if not isinstance(script, dict) or not isinstance(catalog, dict):
        raise ValueError("Script and catalog must be objects")
    if not isinstance(script.get("source_text"), str):
        raise ValueError("source_text must be string")
    if script.get("state") != "confirmed":
        raise ValueError("Script state must be 'confirmed'")
    if type(script.get("sample")) is not bool:
        raise ValueError("Script sample must be exact bool")
    raw_hash = hashlib.sha256(str(script.get("source_text", "")).encode("utf-8")).hexdigest()
    if script.get("source_sha256") != raw_hash:
        raise ValueError("Script source_sha256 mismatch")
    segs = script.get("segments")
    if not isinstance(segs, list) or not segs:
        raise ValueError("Script segments must be non-empty list")
    from vmv.script import _split_paragraphs
    expected = _split_paragraphs(script["source_text"])
    if len(segs) != len(expected):
        raise ValueError("Script paragraphs mismatch")
    for index, (seg, (start, end, text)) in enumerate(zip(segs, expected), 1):
        if not isinstance(seg, dict) or any(type(seg.get(key)) is not int for key in ("start", "end")):
            raise ValueError("Invalid segment offsets")
        if (seg.get("id"), seg["start"], seg["end"], seg.get("narration")) != (f"seg-{index:03d}", start, end, text):
            raise ValueError("Script paragraph mapping mismatch")
        if any(not isinstance(seg.get(key), str) for key in ("characters", "setting", "action", "emotion", "visual_requirement")):
            raise ValueError("Requirement fields must be strings")
    seg_ids = set()
    for s in segs:
        if not isinstance(s, dict): raise ValueError("Segment must be dict")
        sid = s.get("id")
        if not sid or sid in seg_ids: raise ValueError(f"Duplicate or empty segment id: {sid}")
        seg_ids.add(sid)
        if s.get("status") != "confirmed": raise ValueError(f"Segment {sid} status not confirmed")
        if not str(s.get("visual_requirement") or "").strip(): raise ValueError(f"Segment {sid} blank visual")
        if not (_is_num(s.get("start")) and _is_num(s.get("end")) and 0 <= s["start"] <= s["end"]):
            raise ValueError(f"Segment {sid} invalid time range")

    if type(catalog.get("sample")) is not bool or catalog["sample"] != script["sample"]:
        raise ValueError("Catalog sample must be bool and match script sample")
    mid = catalog.get("media_id", "")
    if not isinstance(mid, str) or not re.fullmatch(r"^[A-Za-z0-9_-]+$", mid):
        raise ValueError("Catalog media_id must be safe ASCII alnum/hyphen/underscore")
    dur = catalog.get("duration_sec")
    if not (_is_num(dur) and dur > 0): raise ValueError("Catalog duration_sec must be positive finite number")
    dsrc = catalog.get("description_source")
    if dsrc is not None and dsrc not in ("synthetic", "model_assisted", "human"):
        raise ValueError("Invalid catalog description_source")
    shots = catalog.get("shots")
    if not isinstance(shots, list): raise ValueError("Catalog shots must be list")
    shot_ids = set()
    for shot in shots:
        if not isinstance(shot, dict): raise ValueError("Shot must be dict")
        shid = shot.get("id")
        if not shid or not re.fullmatch(r"^[A-Za-z0-9_-]+$", str(shid)) or shid in shot_ids:
            raise ValueError(f"Invalid or duplicate shot id: {shid}")
        shot_ids.add(shid)
        st, et = shot.get("start_sec"), shot.get("end_sec")
        if not (_is_num(st) and _is_num(et) and 0 <= st < et <= dur):
            raise ValueError(f"Shot {shid} invalid start_sec/end_sec")
        if not str(shot.get("caption") or "").strip(): raise ValueError(f"Shot {shid} blank caption")
        sub = shot.get("subtitle")
        if sub is not None and not isinstance(sub, str): raise ValueError(f"Shot {shid} subtitle must be string")

    h = hashlib.sha256()
    with open(video_path, "rb") as vf:
        while chunk := vf.read(65536):
            h.update(chunk)
    if h.hexdigest() != catalog.get("source_sha256"): raise ValueError("Video SHA256 mismatch")


def document_hash(document):
    payload = {k: v for k, v in document.items() if k != "document_sha256"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _generate_html(doc: dict) -> str:
    safe_json = json.dumps(doc, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>候选镜头审核</title>
<style>
body{{font-family:sans-serif;margin:20px;background:#f5f5f5}}
.seg{{background:#fff;padding:15px;margin-bottom:15px;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,0.1)}}
.cands{{display:flex;gap:15px;flex-wrap:wrap;margin-top:10px}}
.card{{border:1px solid #ddd;border-radius:4px;padding:10px;width:280px;background:#fafafa}}
video{{width:100%;border-radius:4px;background:#000}}
.btn{{padding:8px 16px;background:#0066cc;color:#fff;border:none;border-radius:4px;cursor:pointer;margin-top:15px}}
.unfit{{margin-top:10px}}
</style></head><body><h2>候选镜头审核</h2><p>{"【合成测试素材】" if doc["sample"] else ""}</p><div id="content"></div>
<button class="btn" onclick="exportReview()">导出审核结果</button>
<script id="data" type="application/json">{safe_json}</script>
<script>
const doc = JSON.parse(document.getElementById('data').textContent);
function esc(v) {{return String(v ?? '').replace(/[&<>"']/g, c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));}}
const root = document.getElementById('content');
doc.segments.forEach((seg, sIdx) => {{
  const div = document.createElement('div');
  div.className = 'seg';
  div.innerHTML = `<h3>段落： ${{esc(seg.id)}}</h3><p>${{esc(seg.narration || '')}}</p><p>画面要求：${{esc(seg.visual_requirement)}}</p>
    <div class="cands" id="cands-${{sIdx}}"></div>
    <div class="unfit"><label><input type="checkbox" id="unfit-${{sIdx}}" onchange="toggleUnfit(${{sIdx}})"> 全部不合适</label></div>`;
  root.appendChild(div);
  const cBox = div.querySelector(`#cands-${{sIdx}}`);
  if (!seg.candidates || seg.candidates.length === 0) {{
    cBox.innerHTML = '<em>没有匹配候选</em>';
  }} else {{
    seg.candidates.forEach((c, cIdx) => {{
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `<video controls src="${{esc(c.preview)}}"></video>
        <p>镜头： ${{esc(c.shot_id)}}<br>起止： ${{c.start_sec}}s - ${{c.end_sec}}s<br>理由： ${{esc(c.reason)}}</p>
        <label>审核： <select id="dec-${{sIdx}}-${{cIdx}}" onchange="checkAdopt(${{sIdx}}, ${{cIdx}})">
          <option value="pending">待审核</option><option value="adopt">采用</option><option value="reject">淘汰</option>
        </select></label>`;
      cBox.appendChild(card);
    }});
  }}
}});
function toggleUnfit(sIdx) {{
  if (document.getElementById(`unfit-${{sIdx}}`).checked) {{
    (doc.segments[sIdx].candidates || []).forEach((_, cIdx) => {{
      const sel = document.getElementById(`dec-${{sIdx}}-${{cIdx}}`);
      if (sel) sel.value = 'reject';
    }});
  }}
}}
function checkAdopt(sIdx, cIdx) {{
  const sel = document.getElementById(`dec-${{sIdx}}-${{cIdx}}`);
  if (sel.value === 'adopt') {{
    document.getElementById(`unfit-${{sIdx}}`).checked = false;
    (doc.segments[sIdx].candidates || []).forEach((_, ci) => {{
      if (ci !== cIdx) {{
        const s = document.getElementById(`dec-${{sIdx}}-${{ci}}`);
        if (s && s.value === 'adopt') s.value = 'reject';
      }}
    }});
  }}
}}
function exportReview() {{
  const outSegs = [];
  for (let sIdx = 0; sIdx < doc.segments.length; sIdx++) {{
    const seg = doc.segments[sIdx];
    const unfit = document.getElementById(`unfit-${{sIdx}}`).checked;
    const cands = [];
    let adoptCount = 0;
    for (let cIdx = 0; cIdx < (seg.candidates || []).length; cIdx++) {{
      const dec = document.getElementById(`dec-${{sIdx}}-${{cIdx}}`).value;
      if (dec === 'pending') {{ alert(`Segment ${{esc(seg.id)}} candidate is pending!`); return; }}
      if (dec === 'adopt') adoptCount++;
      cands.push({{shot_id: seg.candidates[cIdx].shot_id, decision: dec}});
    }}
    if (unfit && adoptCount > 0) {{ alert(`Segment ${{esc(seg.id)}}: unsuitable cannot combine with adopt`); return; }}
    if (adoptCount > 1) {{ alert(`Segment ${{esc(seg.id)}}: at most 1 adopt`); return; }}
    if (adoptCount === 0 && (!unfit || cands.some(c => c.decision !== 'reject'))) {{
      alert(`Segment ${{esc(seg.id)}}: 0 adopt requires all_unsuitable and all reject`); return;
    }}
    outSegs.push({{id: seg.id, all_unsuitable: unfit, candidates: cands}});
  }}
  const blob = new Blob([JSON.stringify({{
    script_sha256: doc.script_sha256, catalog_sha256: doc.catalog_sha256, document_sha256: doc.document_sha256, sample: doc.sample, segments: outSegs
  }}, null, 2)], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'review.json'; a.click();
}}
</script></body></html>"""


def run_retrieval(script_path: str, catalog_path: str, video_path: str, output_dir: str, assisted_rankings_path=None) -> dict:
    out_p = Path(output_dir)
    if out_p.exists():
        raise FileExistsError(f"Output directory exists: {output_dir}")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe must be available in PATH")

    with open(script_path, "rb") as f:
        s_bytes = f.read()
    script = json.loads(s_bytes.decode("utf-8"))
    with open(catalog_path, "rb") as f:
        c_bytes = f.read()
    catalog = json.loads(c_bytes.decode("utf-8"))

    _validate_inputs(script, catalog, video_path)

    res = run_generation([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
    ], timeout=60)
    dur_out = res.stdout if hasattr(res, "stdout") else res
    if isinstance(dur_out, bytes): dur_out = dur_out.decode("utf-8")
    if not math.isfinite(float(str(dur_out).strip())) or abs(float(str(dur_out).strip()) - catalog["duration_sec"]) > 0.1:
        raise ValueError("Video duration mismatch with catalog duration_sec")

    assisted = None
    if assisted_rankings_path is not None:
        from vmv.retrieval_assistance import assisted_candidates
        assisted = assisted_candidates(assisted_rankings_path, hashlib.sha256(s_bytes).hexdigest(), hashlib.sha256(c_bytes).hexdigest(), script["segments"], catalog["shots"], script["sample"])
    parent = out_p.resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as tmp_str:
        payload = Path(tmp_str) / "out"
        payload.mkdir()
        doc_segs = []
        for s_idx, seg in enumerate(script["segments"]):
            baseline = rank_candidates(seg, catalog["shots"], limit=3)
            cands = assisted[seg["id"]] if assisted is not None else baseline
            cand_entries = []
            for c_idx, c in enumerate(cands):
                fname = f"{s_idx}-{c_idx}.mp4"
                dur = round(c["end_sec"] - c["start_sec"], 3)
                run_generation([
                    "ffmpeg", "-ss", f"{c['start_sec']:.3f}", "-i", str(video_path),
                    "-t", f"{dur:.3f}", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-y", str(payload / fname)
                ], timeout=60)
                verify_visual_file(payload / fname)
                entry = dict(c)
                entry["preview"] = fname
                cand_entries.append(entry)
            doc_segs.append({
                "id": seg["id"],
                "narration": seg.get("narration", ""),
                "visual_requirement": seg["visual_requirement"],
                "candidates": cand_entries,
                "lexical_baseline": baseline,
            })

        doc = {
            "sample": script["sample"],
            "state": "awaiting_review",
            "method": "GPT_assisted" if assisted is not None else "lexical_baseline",
            "script_sha256": hashlib.sha256(s_bytes).hexdigest(),
            "catalog_sha256": hashlib.sha256(c_bytes).hexdigest(),
            "media_id": catalog["media_id"],
            "segments": doc_segs,
        }
        doc["document_sha256"] = document_hash(doc)
        with open(payload / "candidates.json", "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        with open(payload / "review.html", "w", encoding="utf-8") as f:
            f.write(_generate_html(doc))
        os.replace(payload, out_p)
    return doc


def validate_review(review: dict, document: dict) -> dict:
    if not isinstance(review, dict) or not isinstance(document, dict):
        raise ValueError("review and document must be dicts")
    if document.get("document_sha256") != document_hash(document):
        raise ValueError("Candidate document changed")
    for k in ("script_sha256", "catalog_sha256", "document_sha256"):
        if review.get(k) != document.get(k): raise ValueError(f"Hash mismatch: {k}")
    if type(review.get("sample")) is not bool or review["sample"] != document.get("sample"):
        raise ValueError("sample mismatch or not bool")
    r_segs, d_segs = review.get("segments"), document.get("segments")
    if not isinstance(r_segs, list) or not isinstance(d_segs, list) or len(r_segs) != len(d_segs):
        raise ValueError("Segments count mismatch")
    for r_seg, d_seg in zip(r_segs, d_segs):
        if not isinstance(r_seg, dict) or not isinstance(d_seg, dict): raise ValueError("Segment must be dict")
        if r_seg.get("id") != d_seg.get("id"): raise ValueError("Segment ID mismatch or wrong order")
        all_un = r_seg.get("all_unsuitable")
        if type(all_un) is not bool: raise ValueError("all_unsuitable must be exact bool")
        r_cands, d_cands = r_seg.get("candidates"), d_seg.get("candidates")
        if not isinstance(r_cands, list) or not isinstance(d_cands, list) or len(r_cands) != len(d_cands):
            raise ValueError("Candidates count mismatch")
        adopt_count = 0
        for rc, dc in zip(r_cands, d_cands):
            if not isinstance(rc, dict) or not isinstance(dc, dict):
                raise ValueError("Candidate must be object")
            if rc.get("shot_id") != dc.get("shot_id"): raise ValueError("Candidate shot_id mismatch")
            dec = rc.get("decision")
            if dec not in ("adopt", "reject"): raise ValueError(f"Decision must be adopt or reject: {dec}")
            if dec == "adopt": adopt_count += 1
        if adopt_count > 1: raise ValueError("At most 1 adopt per segment")
        if all_un and adopt_count > 0: raise ValueError("all_unsuitable cannot combine with adopt")
        if adopt_count == 0:
            if not all_un: raise ValueError("Zero adopt requires all_unsuitable=True")
            if any(rc.get("decision") != "reject" for rc in r_cands):
                raise ValueError("Zero adopt requires every candidate rejected")
    return review
