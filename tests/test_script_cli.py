import json
from vmv.cli import main
from pathlib import Path


def test_script_and_review(tmp_path: Path):
    input_file = tmp_path / "input.txt"
    input_file.write_text("中文一段。\n\n中文二段。", encoding="utf-8")
    draft_dir = tmp_path / "draft"
    ret = main(["script", "--input", str(input_file), "--output", str(draft_dir), "--sample"])
    assert ret == 0

    draft_segments_file = draft_dir / "segments.json"
    with open(draft_segments_file, "r", encoding="utf-8") as f:
        draft_data = json.load(f)

    assert [s["narration"] for s in draft_data["segments"]] == ["中文一段。", "中文二段。"]
    assert draft_data["state"] == "draft"
    assert draft_data["sample"] is True

    req_segments = []
    for seg in draft_data["segments"]:
        s = dict(seg)
        s["characters"] = "人物甲"
        s["setting"] = "室内"
        s["action"] = "交谈"
        s["emotion"] = "平静"
        s["visual_requirement"] = "双人中景"
        s["status"] = "confirmed"
        req_segments.append(s)

    requirements_file = tmp_path / "requirements.json"
    requirements_data = {
        "source_sha256": draft_data["source_sha256"],
        "segments": req_segments,
    }
    requirements_file.write_text(json.dumps(requirements_data, ensure_ascii=False, indent=2), encoding="utf-8")

    confirmed_dir = tmp_path / "confirmed"
    ret_review = main([
        "script-review",
        "--draft",
        str(draft_segments_file),
        "--requirements",
        str(requirements_file),
        "--output",
        str(confirmed_dir),
    ])
    assert ret_review == 0

    confirmed_segments_file = confirmed_dir / "segments.json"
    with open(confirmed_segments_file, "r", encoding="utf-8") as f:
        confirmed_data = json.load(f)

    assert confirmed_data["state"] == "confirmed"
    assert [s["visual_requirement"] for s in confirmed_data["segments"]] == ["双人中景", "双人中景"]


def test_script_empty_input(tmp_path: Path):
    empty_input = tmp_path / "empty.txt"
    empty_input.write_text("", encoding="utf-8")
    output_dir = tmp_path / "output"
    ret = main(["script", "--input", str(empty_input), "--output", str(output_dir)])
    assert ret == 1
    assert not (output_dir / "segments.json").exists()
    assert not (output_dir / "summary.html").exists()


def test_tamper_requirement_source_hash(tmp_path: Path):
    input_file = tmp_path / "input.txt"
    input_file.write_text("中文一段。\n\n中文二段。", encoding="utf-8")
    draft_dir = tmp_path / "draft"
    ret = main(["script", "--input", str(input_file), "--output", str(draft_dir)])
    assert ret == 0

    draft_segments_file = draft_dir / "segments.json"
    with open(draft_segments_file, "r", encoding="utf-8") as f:
        draft_data = json.load(f)

    req_segments = []
    for seg in draft_data["segments"]:
        s = dict(seg)
        s["characters"] = "人物甲"
        s["setting"] = "室内"
        s["action"] = "交谈"
        s["emotion"] = "平静"
        s["visual_requirement"] = "双人中景"
        s["status"] = "confirmed"
        req_segments.append(s)

    requirements_file = tmp_path / "requirements.json"
    requirements_data = {
        "source_sha256": "tampered_hash_1234567890",
        "segments": req_segments,
    }
    requirements_file.write_text(json.dumps(requirements_data, ensure_ascii=False, indent=2), encoding="utf-8")

    confirmed_dir = tmp_path / "confirmed"
    ret_review = main([
        "script-review",
        "--draft",
        str(draft_segments_file),
        "--requirements",
        str(requirements_file),
        "--output",
        str(confirmed_dir),
    ])
    assert ret_review == 1
    assert not (confirmed_dir / "segments.json").exists()
    assert not (confirmed_dir / "summary.html").exists()