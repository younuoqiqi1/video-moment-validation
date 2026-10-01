"""Actual FFmpeg preview generation, using tiny synthetic media only."""

import hashlib
import json
import subprocess

from vmv.cli import main
from vmv.media import SceneItem, probe_media_file


def inputs(tmp_path):
    video = tmp_path / "sample.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "testsrc=duration=2:size=160x90:rate=25", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", str(video),
    ], check=True)
    media = probe_media_file(video, repo_root=tmp_path)
    manifest = tmp_path / "media_manifest.json"
    manifest.write_text(json.dumps({"media": media.to_dict(), "scene_count": 2,
                                    "scene_manifest_file": "scenes_sample.json"}))
    scenes = tmp_path / "scenes_sample.json"
    scenes.write_text(json.dumps({
        "media_id": media.media_id, "fps": 25, "total_scenes": 2,
        "analyzed_duration_sec": 2,
        "scenes": [
            SceneItem(1, 0, "00:00:00:00", 1, "00:00:01:00", 1, 0, 25).to_dict(),
            SceneItem(2, 1, "00:00:01:00", 2, "00:00:02:00", 1, 25, 50).to_dict(),
        ],
    }))
    args = ["preview", "--media-manifest", str(manifest), "--scenes", str(scenes),
            "--video", str(video), "--output", str(tmp_path / "preview")]
    return video, manifest, scenes, args


def test_preview_cli_uses_existing_json_and_extracts_real_frames(tmp_path):
    video, manifest, scenes, args = inputs(tmp_path)
    original = scenes.read_bytes()
    assert main(args) == 0
    assert scenes.read_bytes() == original  # Do not rerun detection or replace evidence.
    report = json.loads((tmp_path / "preview" / "verification.json").read_text())
    assert report["source_scenes_sha256"] == hashlib.sha256(original).hexdigest()
    assert report["statistics"]["total_scenes"] == 2
    assert report["statistics"]["total_duration_sec"] == 2
    assert report["statistics"]["max_duration_sec"] == 1
    assert report["human_visual_review"] == "not_verified"
    images = list((tmp_path / "preview" / "frames").glob("*.jpg"))
    assert len(images) == 6  # Longest gets five points; other interval gets one.
    assert all(image.read_bytes().startswith(b"\xff\xd8") for image in images)
    html = (tmp_path / "preview" / "summary.html").read_text()
    assert "#002" in html
    assert "重点核对：5 处画面" in html
    assert "frames/scene-0002" in html


def test_preview_rejects_discontinuous_json_before_generating_images(tmp_path):
    _, _, scenes, args = inputs(tmp_path)
    data = json.loads(scenes.read_text())
    data["scenes"][1]["start_sec"] = 1.2
    scenes.write_text(json.dumps(data))
    assert main(args) == 1
    assert not list((tmp_path / "preview").rglob("*.jpg"))


def test_preview_rejects_statistics_from_a_different_manifest(tmp_path):
    _, manifest, _, args = inputs(tmp_path)
    data = json.loads(manifest.read_text())
    data["scene_count"] = 130
    manifest.write_text(json.dumps(data))
    assert main(args) == 1
    assert not list((tmp_path / "preview").rglob("*.jpg"))
