"""Unit tests for Stage 1 media probing, timecodes, and scene detection."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from vmv.media import (
    seconds_to_timecode,
    timecode_to_seconds,
    generate_stable_media_id,
    probe_media_file,
    detect_scenes,
    generate_summary_html,
    run_stage1_media_import,
    MediaProbeError,
    MediaInfo,
    VideoStreamInfo,
    SceneItem,
)


def create_synthetic_test_video(output_path: Path, duration_sec: int = 2) -> Path:
    """Helper to generate a lightweight 2-second synthetic MP4 using ffmpeg."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration_sec}:size=320x240:rate=25",
        "-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration_sec}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def test_seconds_to_timecode_broadcast_formats():
    """Verify conversion from seconds to broadcast HH:MM:SS:FF."""
    # 0s at 25fps -> 00:00:00:00
    assert seconds_to_timecode(0.0, fps=25.0) == "00:00:00:00"
    # 1s at 25fps -> 00:00:01:00
    assert seconds_to_timecode(1.0, fps=25.0) == "00:00:01:00"
    # 1.5s at 25fps (12.5 frames rounds to 13 or 12)
    assert seconds_to_timecode(1.48, fps=25.0) == "00:00:01:12"
    # 65.5s -> 1 min 5.5s -> 00:01:05:12 (0.5 * 25 = 12th frame)
    assert seconds_to_timecode(65.5, fps=25.0) == "00:01:05:12"
    # 3661s -> 1h 1m 1s -> 01:01:01:00
    assert seconds_to_timecode(3661.0, fps=25.0) == "01:01:01:00"


def test_seconds_to_timecode_ms_format():
    """Verify conversion from seconds to millisecond format HH:MM:SS.mmm."""
    assert seconds_to_timecode(0.0, format_type="ms") == "00:00:00.000"
    assert seconds_to_timecode(1.5, format_type="ms") == "00:00:01.500"
    assert seconds_to_timecode(65.123, format_type="ms") == "00:01:05.123"


def test_timecode_to_seconds_roundtrip():
    """Verify parsing timecode back to floating seconds."""
    assert timecode_to_seconds("00:00:01:00", fps=25.0) == 1.0
    assert timecode_to_seconds("01:01:01:00", fps=25.0) == 3661.0
    assert timecode_to_seconds("00:00:01.500") == 1.5
    assert abs(timecode_to_seconds("00:00:01:12", fps=25.0) - 1.48) < 0.01


def test_timecode_invalid_inputs():
    """Verify error handling on negative seconds or malformed string."""
    with pytest.raises(ValueError):
        seconds_to_timecode(-5.0)

    with pytest.raises(ValueError):
        timecode_to_seconds("invalid_timecode")

    with pytest.raises(ValueError):
        seconds_to_timecode(1.0, fps=0)


def test_generate_stable_media_id():
    """Verify media ID sanitation and stability."""
    vinfo = VideoStreamInfo(
        codec="h264", width=1280, height=720, fps=25.0,
        aspect_ratio="16:9", pix_fmt="yuv420p", bit_rate=500000, total_frames=1000
    )
    p = Path("data/input/qianfu_ep18.mp4")
    mid = generate_stable_media_id(p, vinfo)
    assert mid == "qianfu_ep18_720p_25fps"

    # With spaces and punctuation
    p_special = Path("data/input/My Test Video! [1080p].mp4")
    mid_special = generate_stable_media_id(p_special, vinfo)
    assert "!" not in mid_special
    assert "[" not in mid_special
    assert mid_special.startswith("My_Test_Video___1080p__")


def test_probe_media_file_not_found(tmp_path: Path):
    """Verify probing non-existent file raises MediaProbeError."""
    with pytest.raises(MediaProbeError, match="媒体文件不存在"):
        probe_media_file(tmp_path / "non_existent.mp4")


def test_probe_synthetic_media(tmp_path: Path):
    """Verify ffprobe extracts valid streams from synthetic media."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg or ffprobe not available in PATH")

    test_video = create_synthetic_test_video(tmp_path / "synth.mp4", duration_sec=2)
    info = probe_media_file(test_video, repo_root=tmp_path)

    assert info.filename == "synth.mp4"
    assert info.duration_sec >= 1.9
    assert info.video is not None
    assert info.video.width == 320
    assert info.video.height == 240
    assert info.video.fps == 25.0
    assert info.audio is not None
    assert info.audio.channels == 1 or info.audio.channels == 2


def test_detect_scenes_synthetic(tmp_path: Path):
    """Verify scene detection on synthetic video returns contiguous scenes."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")

    test_video = create_synthetic_test_video(tmp_path / "synth_scene.mp4", duration_sec=3)
    scenes = detect_scenes(test_video, total_duration_sec=3.0, fps=25.0)

    assert len(scenes) >= 1
    # Check boundaries
    assert scenes[0].start_sec == 0.0
    assert scenes[-1].end_sec == 3.0
    # Contiguity
    for i in range(len(scenes) - 1):
        assert scenes[i].end_sec == scenes[i + 1].start_sec


def test_run_stage1_media_import_empty_dir_blocked(tmp_path: Path):
    """Verify import in an empty directory records blocked state without crashing."""
    empty_input = tmp_path / "empty_input"
    empty_input.mkdir()
    output_dir = tmp_path / "output_stage1"

    res = run_stage1_media_import(
        input_dir=empty_input,
        output_dir=output_dir,
        repo_root=tmp_path,
    )

    assert res.status == "blocked"
    assert (output_dir / "import_blocked.json").exists()
    assert len(res.errors) >= 1
    assert "未在素材目录" in res.errors[0]


def test_run_stage1_media_import_synthetic_success(tmp_path: Path):
    """Verify end-to-end Stage 1 import produces manifests and HTML summary."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg or ffprobe not available")

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    create_synthetic_test_video(input_dir / "test_synth.mp4", duration_sec=2)

    output_dir = tmp_path / "output_stage1"
    res = run_stage1_media_import(
        input_dir=input_dir,
        output_dir=output_dir,
        target_pattern="test_synth",
        max_duration_sec=2.0,
        repo_root=tmp_path,
    )

    assert res.status == "passed"
    manifest_file = output_dir / "media_manifest.json"
    assert manifest_file.exists()

    with open(manifest_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["stage"] == "stage1_media_import"
    assert data["media"]["filename"] == "test_synth.mp4"

    # HTML report exists
    html_file = output_dir / "summary.html"
    assert html_file.exists()
    assert "阶段 1 素材导入与时间码清单" in html_file.read_text(encoding="utf-8")


def test_generate_summary_html_escapes_untrusted_media_text(tmp_path: Path):
    """Media-derived text must stay text when rendered into the local HTML report."""
    malicious = 'x"><script>alert(1)</script>.mp4'
    media = MediaInfo(
        media_id='id"><script>alert(1)</script>',
        filename=malicious,
        relative_path='data/input/' + malicious,
        file_size_bytes=1,
        file_size_mb=0.0,
        duration_sec=1.0,
        duration_timecode="00:00:01:00",
        format_name="mp4",
        video=None,
        audio=None,
        subtitles=[],
        subtitle_summary='subtitle <img src=x onerror=alert(1)>',
    )

    output_html = tmp_path / "summary.html"
    generate_summary_html(media, [], output_html)
    rendered = output_html.read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in rendered
    assert "<img src=x onerror=alert(1)>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered


def test_summary_shows_all_130_intervals_and_full_statistics(tmp_path):
    media = MediaInfo(
        media_id="sample", filename="sample.mp4", relative_path="sample.mp4",
        file_size_bytes=1, file_size_mb=0, duration_sec=597.96,
        duration_timecode="00:09:57:24", format_name="mp4", video=None,
        audio=None, subtitles=[], subtitle_summary="待核对",
    )
    scenes = []
    start = 0.0
    for index in range(1, 131):
        duration = 210.96 if index == 101 else 3.0
        end = round(start + duration, 3)
        scenes.append(SceneItem(index, start, seconds_to_timecode(start), end,
                                seconds_to_timecode(end), duration,
                                round(start * 25), round(end * 25)))
        start = end
    output = tmp_path / "summary.html"
    generate_summary_html(media, scenes, output)
    rendered = output.read_text()
    assert "#101" in rendered
    assert "#130" in rendered
    assert rendered.count("<tr>") == 131  # 130 rows and one heading
    assert "最长 210.96s" in rendered
    assert "前 100" not in rendered
