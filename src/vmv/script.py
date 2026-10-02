import hashlib
import html
import json
from pathlib import Path


def _split_paragraphs(source_text: str):
    if not source_text or not source_text.strip():
        raise ValueError("Input source text is blank or empty")
    lines = source_text.splitlines(keepends=True)
    segments, cur_lines, cur_start, pos = [], [], None, 0
    for line in lines:
        start = pos
        pos += len(line)
        if line.strip():
            if cur_start is None:
                cur_start = start
            cur_lines.append(line)
        else:
            if cur_lines:
                text = "".join(cur_lines).rstrip("\r\n")
                segments.append((cur_start, cur_start + len(text), text))
                cur_lines, cur_start = [], None
    if cur_lines:
        text = "".join(cur_lines).rstrip("\r\n")
        segments.append((cur_start, cur_start + len(text), text))
    return segments


def _safe_json_embed(obj) -> str:
    s = json.dumps(obj, ensure_ascii=False)
    return s.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _render_html(data: dict) -> str:
    sample_banner = (
        '<div class="banner">【合成测试稿】此内容为测试样本，请仔细核对。</div>'
        if data.get("sample")
        else ""
    )
    embedded_json = _safe_json_embed(data)

    cards = []
    for s in data["segments"]:
        seg_id = html.escape(s["id"])
        narration = html.escape(s["narration"])
        char_val = html.escape(s.get("characters", ""))
        set_val = html.escape(s.get("setting", ""))
        act_val = html.escape(s.get("action", ""))
        emo_val = html.escape(s.get("emotion", ""))
        vis_val = html.escape(s.get("visual_requirement", ""))
        st = s.get("status", "needs_review")
        sel_review = ' selected' if st == "needs_review" else ''
        sel_confirmed = ' selected' if st == "confirmed" else ''

        card = f'''    <div class="card">
      <div class="card-header">
        <span class="seg-id">{seg_id}</span>
        <label>状态:
          <select class="f-status">
            <option value="needs_review"{sel_review}>待审核 (needs_review)</option>
            <option value="confirmed"{sel_confirmed}>已确认 (confirmed)</option>
          </select>
        </label>
      </div>
      <div class="narration">{narration}</div>
      <div class="grid">
        <div><label>人物</label><textarea class="f-char">{char_val}</textarea></div>
        <div><label>场景</label><textarea class="f-set">{set_val}</textarea></div>
        <div><label>动作</label><textarea class="f-act">{act_val}</textarea></div>
        <div><label>情绪</label><textarea class="f-emo">{emo_val}</textarea></div>
        <div><label>视觉要求 (必填)</label><textarea class="f-vis">{vis_val}</textarea></div>
      </div>
    </div>'''
        cards.append(card)

    cards_html = "\n".join(cards)
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>分镜脚本管理 - {html.escape(data.get("state", ""))}</title>
<style>
  body {{ font-family: sans-serif; margin: 24px; background: #f8fafc; color: #1e293b; }}
  .banner {{ background: #fef3c7; color: #92400e; padding: 12px 16px; border-radius: 6px; font-weight: bold; margin-bottom: 20px; border: 1px solid #fde68a; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
  .btn {{ background: #2563eb; color: #fff; border: none; padding: 10px 18px; border-radius: 6px; font-size: 14px; cursor: pointer; }}
  .btn:hover {{ background: #1d4ed8; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }}
  .card-header {{ display: flex; justify-content: space-between; margin-bottom: 10px; font-weight: bold; }}
  .seg-id {{ color: #0284c7; font-family: monospace; font-size: 15px; }}
  .narration {{ background: #f1f5f9; padding: 10px; border-radius: 4px; white-space: pre-wrap; margin-bottom: 12px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }}
  .grid label {{ display: block; font-size: 12px; color: #64748b; margin-bottom: 4px; }}
  textarea {{ width: 100%; box-sizing: border-box; height: 60px; border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px; font-size: 13px; resize: vertical; }}
  select {{ padding: 4px 8px; border-radius: 4px; border: 1px solid #cbd5e1; }}
</style>
</head>
<body>
{sample_banner}
<div class="header">
  <div>
    <h1>分镜脚本审核 ({html.escape(data.get("state", ""))})</h1>
    <div>哈希: <code>{html.escape(data.get("source_sha256", ""))}</code> | 段落数: {len(data.get("segments", []))}</div>
  </div>
  <button class="btn" onclick="exportRequirements()">下载 requirements.json</button>
</div>
<div id="container">
{cards_html}
</div>
<script>
const INITIAL_DATA = {embedded_json};
function exportRequirements() {{
  const cards = document.querySelectorAll('.card');
  const segments = INITIAL_DATA.segments.map((orig, i) => {{
    const c = cards[i];
    return {{
      id: orig.id,
      narration: orig.narration,
      characters: c.querySelector('.f-char').value,
      setting: c.querySelector('.f-set').value,
      action: c.querySelector('.f-act').value,
      emotion: c.querySelector('.f-emo').value,
      visual_requirement: c.querySelector('.f-vis').value,
      status: c.querySelector('.f-status').value
    }};
  }});
  const out = {{ source_sha256: INITIAL_DATA.source_sha256, segments: segments }};
  const blob = new Blob([JSON.stringify(out, null, 2)], {{ type: 'application/json' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'requirements.json';
  a.click();
  URL.revokeObjectURL(url);
}}
</script>
</body>
</html>'''


def _write_outputs(output_dir: str | Path, data: dict):
    out_p = Path(output_dir)
    if out_p.exists():
        raise FileExistsError(f"Output directory '{output_dir}' already exists")
    out_p.mkdir(parents=True, exist_ok=False)

    seg_path = out_p / "segments.json"
    html_path = out_p / "summary.html"

    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_render_html(data))


def prepare_script(input_path: str | Path, output_dir: str | Path, sample: bool = False) -> dict:
    with open(input_path, "rb") as f:
        raw_bytes = f.read()

    source_text = raw_bytes.decode("utf-8")
    if not source_text.strip():
        raise ValueError("Input source text cannot be blank")

    source_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    paragraphs = _split_paragraphs(source_text)

    segments = []
    for i, (start, end, narration) in enumerate(paragraphs):
        segments.append({
            "id": f"seg-{i+1:03d}",
            "start": start,
            "end": end,
            "narration": narration,
            "characters": "",
            "setting": "",
            "action": "",
            "emotion": "",
            "visual_requirement": "",
            "status": "needs_review",
        })

    draft_data = {
        "source_sha256": source_sha256,
        "source_text": source_text,
        "state": "draft",
        "sample": bool(sample),
        "segments": segments,
    }

    _write_outputs(output_dir, draft_data)
    return draft_data


def confirm_script(draft_path: str | Path, requirements_path: str | Path, output_dir: str | Path) -> dict:
    with open(draft_path, "r", encoding="utf-8") as f:
        draft = json.load(f)

    if not (isinstance(draft, dict) and isinstance(draft.get("sample"), bool) and draft.get("state") in ("draft", "confirmed")):
        raise ValueError("草稿数据格式无效")
    source_text = draft.get("source_text")
    if not isinstance(source_text, str):
        raise ValueError("Draft source_text must be a string")

    encoded_source = source_text.encode("utf-8")
    computed_hash = hashlib.sha256(encoded_source).hexdigest()
    if computed_hash != draft.get("source_sha256"):
        raise ValueError("Draft source hash mismatch or tamper detected")

    recomputed = _split_paragraphs(source_text)
    draft_segments = draft.get("segments")
    if not isinstance(draft_segments, list) or len(draft_segments) != len(recomputed):
        raise ValueError("Draft segments count mismatch")

    for i, (start, end, narration) in enumerate(recomputed):
        ds = draft_segments[i]
        if not (isinstance(ds, dict) and type(ds.get("start")) is int and type(ds.get("end")) is int):
            raise ValueError("分段数据格式无效")
        if (
            ds.get("id") != f"seg-{i+1:03d}"
            or ds.get("start") != start
            or ds.get("end") != end
            or ds.get("narration") != narration
        ):
            raise ValueError(f"Draft segment tamper detected at index {i}")

    with open(requirements_path, "r", encoding="utf-8") as f:
        req = json.load(f)

    if not isinstance(req, dict):
        raise ValueError("请求数据格式无效")
    if req.get("source_sha256") != draft["source_sha256"]:
        raise ValueError("Requirements source_sha256 does not match draft")

    req_root_keys = set(req.keys())
    if req_root_keys - {"source_sha256", "segments", "state", "sample"}:
        raise ValueError("Requirements has unexpected root keys")

    req_segments = req.get("segments")
    if not isinstance(req_segments, list) or len(req_segments) != len(draft_segments):
        raise ValueError("Requirements segments count or type mismatch")

    expected_fields = {"characters", "setting", "action", "emotion", "visual_requirement"}
    confirmed_segments = []

    for i, (ds, rs) in enumerate(zip(draft_segments, req_segments)):
        if not isinstance(rs, dict):
            raise ValueError(f"Segment {i} in requirements is not an object")

        rs_keys = set(rs.keys())
        allowed = expected_fields | {"id", "narration", "status", "start", "end"}
        if not (expected_fields | {"id", "narration", "status"}).issubset(rs_keys) or (rs_keys - allowed):
            raise ValueError(f"Segment {ds['id']} has invalid or missing fields")

        if rs["id"] != ds["id"]:
            raise ValueError(f"Segment ID mismatch: expected {ds['id']}, got {rs['id']}")
        if rs["narration"] != ds["narration"]:
            raise ValueError(f"Segment narration tamper in {ds['id']}")

        for fld in expected_fields:
            if not isinstance(rs[fld], str):
                raise ValueError(f"Field '{fld}' in segment {ds['id']} must be string")

        if not rs["visual_requirement"].strip():
            raise ValueError(f"visual_requirement cannot be blank in {ds['id']}")
        if rs.get("status") != "confirmed":
            raise ValueError(f"Segment status must be 'confirmed' in {ds['id']}")

        confirmed_segments.append({
            "id": ds["id"],
            "start": ds["start"],
            "end": ds["end"],
            "narration": ds["narration"],
            "characters": rs["characters"],
            "setting": rs["setting"],
            "action": rs["action"],
            "emotion": rs["emotion"],
            "visual_requirement": rs["visual_requirement"],
            "status": "confirmed",
        })

    confirmed_data = {
        "source_sha256": draft["source_sha256"],
        "source_text": draft["source_text"],
        "state": "confirmed",
        "sample": draft.get("sample", False),
        "segments": confirmed_segments,
    }

    _write_outputs(output_dir, confirmed_data)
    return confirmed_data
