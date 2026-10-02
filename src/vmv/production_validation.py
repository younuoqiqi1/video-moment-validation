import hashlib
import math
import re


def canonical_shot_id(entry):
    if not isinstance(entry, dict):
        raise ValueError("entry must be a dict")
    shot_id = entry.get("shot_id")
    if not isinstance(shot_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", shot_id):
        raise ValueError("Invalid shot_id")
    for alias in ("id", "chosen_id"):
        if alias in entry and entry[alias] != shot_id:
            raise ValueError(f"Alias {alias} conflicts with shot_id")
    return shot_id


def canonical_times(entry):
    if not isinstance(entry, dict) or "in_sec" not in entry or "out_sec" not in entry:
        raise ValueError("Missing canonical in_sec or out_sec")
    for k in ("in_sec", "out_sec"):
        v = entry[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"Invalid {k}")
    for alias, canon in (("source_in_sec", "in_sec"), ("source_out_sec", "out_sec")):
        if alias in entry and entry[alias] != entry[canon]:
            raise ValueError(f"Alias {alias} conflicts with {canon}")
    return entry["in_sec"], entry["out_sec"]


def require_source_hash(script):
    if not isinstance(script, dict) or "source_sha256" not in script:
        raise ValueError("Missing mandatory source_sha256")
    h = script["source_sha256"]
    if not isinstance(h, str):
        raise ValueError("source_sha256 must be a string")
    src = script.get("source_text")
    if not isinstance(src, str):
        raise ValueError("source_text must be a string")
    if h != hashlib.sha256(src.encode("utf-8")).hexdigest():
        raise ValueError("Hash mismatch")


def require_paragraph_mapping(seg, paragraph):
    start = seg.get("start")
    end = seg.get("end")
    if type(start) is not int or type(end) is not int:
        raise ValueError("start and end must be exact int")
    if not isinstance(paragraph, tuple) or (start, end, seg.get("narration")) != paragraph:
        raise ValueError("Segment does not match paragraph tuple")


def require_positive_trim(in_sec, out_sec):
    r_in = round(in_sec, 6)
    r_out = round(out_sec, 6)
    if round(r_out - r_in, 6) <= 0:
        raise ValueError("Trim duration must be positive")
    return r_in, r_out
