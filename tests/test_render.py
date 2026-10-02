import hashlib
import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest


def get_render():
    """Lazy import helper that fails with a clear message if vmv.render is absent."""
    try:
        from vmv.render import render

        return render
    except ImportError as e:
        pytest.fail(f"Could not import vmv.render.render: {e}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generate_wav(path: Path, duration_sec: float = 1.0, freq_hz: float = 300.0, sample_rate: int = 22050):
    """Generates standard mono 22050Hz PCM16 300Hz sine wave."""
    path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(sample_rate * duration_sec)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        data = bytearray()
        for i in range(num_samples):
            sample = int(32767.0 * math.sin(2.0 * math.pi * freq_hz * i / sample_rate))
            data.extend(struct.pack("<h", sample))
        wf.writeframes(data)


def generate_mp4(path: Path, ffmpeg_bin: str = "ffmpeg"):
    """Generates 4sec 25fps red 2sec then blue 2sec MP4 320x180 h264 yuv420p, -an using lavfi."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=320x180:d=2:r=25",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=320x180:d=2:r=25",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[outv]",
        "-map",
        "[outv]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(path),
    ]
    subprocess.run(cmd, check=True, timeout=15, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def extract_pixel_rgb(video_path: Path, timestamp_sec: float, ffmpeg_bin: str = "ffmpeg") -> Tuple[int, int, int]:
    """Decodes a single frame scaled to 1:1 rawrgb24 via parameter list to sample color."""
    cmd = [
        ffmpeg_bin,
        "-ss",
        str(timestamp_sec),
        "-i",
        str(video_path),
        "-vframes",
        "1",
        "-vf",
        "scale=1:1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    proc = subprocess.run(cmd, check=True, timeout=15, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert len(proc.stdout) >= 3, f"Expected at least 3 raw RGB bytes, got {len(proc.stdout)}"
    r, g, b = struct.unpack("3B", proc.stdout[:3])
    return r, g, b


@pytest.fixture(autouse=True)
def check_ffmpeg_available():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg and/or ffprobe executable unavailable on PATH")


@pytest.fixture
def test_environment(tmp_path: Path):
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    video_path = media_root / "input.mp4"
    generate_mp4(video_path)
    video_hash = sha256_file(video_path)

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    wav_path = audio_dir / "voice.wav"
    generate_wav(wav_path, duration_sec=1.0, freq_hz=300.0, sample_rate=22050)
    wav_hash = sha256_file(wav_path)

    narration_text = "合成测试。"
    narration_hash = sha256_text(narration_text)

    order_data: Dict[str, Any] = {
        "state": "ready_for_tts",
        "sample": True,
        "media_id": "test",
        "source_sha256": video_hash,
        "source_path": "input.mp4",
        "document_sha256": "0" * 64,
        "timing_basis": "source_clip_duration_not_voice",
        "duration_sec": 3,
        "segments": [
            {
                "id": "seg-001",
                "narration": narration_text,
                "shots": [
                    {
                        "shot_id": "red",
                        "source_in_sec": 0,
                        "source_out_sec": 1.5,
                        "timeline_in_sec": 0,
                        "timeline_out_sec": 1.5,
                    },
                    {
                        "shot_id": "blue",
                        "source_in_sec": 2,
                        "source_out_sec": 3.5,
                        "timeline_in_sec": 1.5,
                        "timeline_out_sec": 3,
                    },
                ],
            }
        ],
    }

    order_path = tmp_path / "order.json"
    order_bytes = json.dumps(order_data, ensure_ascii=False, indent=2).encode("utf-8")
    order_path.write_bytes(order_bytes)
    order_hash = hashlib.sha256(order_bytes).hexdigest()

    manifest_data: Dict[str, Any] = {
        "sample": True,
        "order_sha256": order_hash,
        "provider": "local_import",
        "segments": [
            {
                "id": "seg-001",
                "narration_sha256": narration_hash,
                "path": "voice.wav",
                "sha256": wav_hash,
            }
        ],
    }
    manifest_path = audio_dir / "audio_manifest.json"
    manifest_bytes = json.dumps(manifest_data, ensure_ascii=False, indent=2).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)

    outdir = tmp_path / "out"

    return {
        "tmp_path": tmp_path,
        "media_root": media_root,
        "video_path": video_path,
        "video_hash": video_hash,
        "audio_dir": audio_dir,
        "wav_path": wav_path,
        "wav_hash": wav_hash,
        "order_path": order_path,
        "order_data": order_data,
        "manifest_path": manifest_path,
        "manifest_data": manifest_data,
        "outdir": outdir,
        "narration_text": narration_text,
    }


def test_render_success(test_environment):
    render = get_render()

    order_path = test_environment["order_path"]
    media_root = test_environment["media_root"]
    manifest_path = test_environment["manifest_path"]
    outdir = test_environment["outdir"]

    render(order_path, media_root, manifest_path, outdir, ffmpeg="ffmpeg", ffprobe="ffprobe")

    sample_mp4 = outdir / "sample.mp4"
    assert sample_mp4.is_file(), "Expected out/sample.mp4 to exist"

    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(sample_mp4),
    ]
    probe_res = subprocess.run(probe_cmd, check=True, timeout=15, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    probe_json = json.loads(probe_res.stdout.decode("utf-8"))

    streams = probe_json.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    assert len(video_streams) > 0, "Expected video stream in sample.mp4"
    assert len(audio_streams) > 0, "Expected audio stream in sample.mp4"

    v_stream = video_streams[0]
    a_stream = audio_streams[0]

    assert v_stream.get("codec_name", "").lower() == "h264"
    assert int(v_stream.get("width", 0)) == 1920
    assert int(v_stream.get("height", 0)) == 1080

    r_fps_str = v_stream.get("r_frame_rate", "0/1")
    fps_parts = r_fps_str.split("/")
    fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 and float(fps_parts[1]) != 0 else float(fps_parts[0])
    assert abs(fps - 25.0) < 0.1, f"Expected 25fps video, got {fps}"

    assert a_stream.get("codec_name", "").lower() == "aac"

    duration = float(probe_json.get("format", {}).get("duration", 0.0))
    assert abs(duration - 1.0) <= 0.08, f"Expected duration within 0.08s of 1.0s, got {duration}"

    audio_pcm = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(sample_mp4), '-vn', '-f', 's16le', '-ac', '1', '-ar', '22050', '-'], capture_output=True, check=True, timeout=15).stdout
    samples = struct.unpack('<' + 'h' * (len(audio_pcm)//2), audio_pcm)
    assert len(samples) >= 20000
    assert max(abs(v) for v in samples) > 1000, 'Voice audio must not be silently dropped'

    srt_files = list(outdir.glob("*.srt"))
    assert len(srt_files) > 0, "Expected at least one SRT subtitle file in outdir"
    srt_content = srt_files[0].read_text(encoding="utf-8")
    assert test_environment["narration_text"] in srt_content
    assert "00:00:01,000" in srt_content

    vt_path = outdir / "voice-timeline.json"
    assert vt_path.is_file(), "Expected out/voice-timeline.json to exist"
    vt_json = json.loads(vt_path.read_text(encoding="utf-8"))
    assert vt_json.get("timing_basis") == "voice_duration"

    r1, g1, b1 = extract_pixel_rgb(sample_mp4, 0.1)
    assert r1 > 150 and g1 < 80 and b1 < 80, f"Expected red dominant frame at 0.1s, got RGB=({r1}, {g1}, {b1})"

    r2, g2, b2 = extract_pixel_rgb(sample_mp4, 0.9)
    assert b2 > 150 and r2 < 80 and g2 < 80, f"Expected blue dominant frame at 0.9s, got RGB=({r2}, {g2}, {b2})"


def test_render_refuse_existing_output(test_environment):
    render = get_render()
    outdir = test_environment["outdir"]
    outdir.mkdir(parents=True, exist_ok=True)
    marker = outdir / "keep_existing.marker"
    marker.write_text("preserve_marker_payload", encoding="utf-8")

    with pytest.raises((FileExistsError, ValueError, RuntimeError)):
        render(
            test_environment["order_path"],
            test_environment["media_root"],
            test_environment["manifest_path"],
            outdir,
        )

    assert marker.is_file(), "Pre-existing output directory marker must be preserved"
    assert marker.read_text(encoding="utf-8") == "preserve_marker_payload"
    assert not (outdir / "sample.mp4").exists(), "sample.mp4 should not be created when output is refused"


def test_render_failing_ffmpeg_binary(test_environment):
    render = get_render()
    outdir = test_environment["outdir"]
    video_path = test_environment["video_path"]
    wav_path = test_environment["wav_path"]
    orig_video_hash = test_environment["video_hash"]
    orig_wav_hash = test_environment["wav_hash"]

    with pytest.raises((OSError, ValueError)):
        render(
            test_environment["order_path"],
            test_environment["media_root"],
            test_environment["manifest_path"],
            outdir,
            ffmpeg="nonexistent_ffmpeg_executable_bin_xyz",
        )

    assert not (outdir / "sample.mp4").exists(), "Failing ffmpeg must not leave completed sample.mp4"
    assert sha256_file(video_path) == orig_video_hash, "Original video input must remain unchanged"
    assert sha256_file(wav_path) == orig_wav_hash, "Original audio input must remain unchanged"


@pytest.mark.parametrize(
    "case",
    [
        "audiohashbad",
        "narrationhashbad",
        "orderhashbad",
        "sampleflagconflict",
        "absolute audiopath",
        "../escape.wav",
        "videohashbad",
    ],
)
def test_render_invalid_inputs(test_environment, case):
    render = get_render()

    order_data = test_environment["order_data"]
    manifest_data = test_environment["manifest_data"]
    order_path = test_environment["order_path"]
    manifest_path = test_environment["manifest_path"]
    media_root = test_environment["media_root"]
    wav_path = test_environment["wav_path"]
    video_path = test_environment["video_path"]
    orig_video_hash = test_environment["video_hash"]
    orig_wav_hash = test_environment["wav_hash"]
    outdir = test_environment["outdir"]

    if case == "audiohashbad":
        manifest_data["segments"][0]["sha256"] = "0" * 64
    elif case == "narrationhashbad":
        manifest_data["segments"][0]["narration_sha256"] = "0" * 64
    elif case == "orderhashbad":
        manifest_data["order_sha256"] = "0" * 64
    elif case == "sampleflagconflict":
        order_data["sample"] = False
        manifest_data["sample"] = True
    elif case == "absolute audiopath":
        manifest_data["segments"][0]["path"] = str(wav_path.resolve())
    elif case == "../escape.wav":
        manifest_data["segments"][0]["path"] = "../escape.wav"
    elif case == "videohashbad":
        order_data["source_sha256"] = "0" * 64
        # Modifying valid json must rebind orderhash in manifest for videohashbad scenario
        order_bytes = json.dumps(order_data, ensure_ascii=False, indent=2).encode("utf-8")
        order_path.write_bytes(order_bytes)
        manifest_data["order_sha256"] = hashlib.sha256(order_bytes).hexdigest()

    order_bytes = json.dumps(order_data, ensure_ascii=False, indent=2).encode("utf-8")
    order_path.write_bytes(order_bytes)

    if case in ('sampleflagconflict', 'videohashbad'):
        manifest_data['order_sha256'] = hashlib.sha256(order_bytes).hexdigest()
    manifest_bytes = json.dumps(manifest_data, ensure_ascii=False, indent=2).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)

    with pytest.raises(ValueError):
        render(order_path, media_root, manifest_path, outdir)

    assert not outdir.exists(), f"No output expected for invalid case: {case}"
    assert sha256_file(video_path) == orig_video_hash, "Original video input must remain intact"
    assert sha256_file(wav_path) == orig_wav_hash, "Original audio input must remain intact"


@pytest.mark.parametrize('case', ['quoted_parent', 'crlf'])
def test_render_path_and_multiline_narration(test_environment, case):
    env = test_environment
    if case == 'quoted_parent':
        out = env['tmp_path'] / "quote's folder" / 'rendered'
    else:
        text = '第一行\r\n第二行'
        env['order_data']['segments'][0]['narration'] = text
        env['order_path'].write_text(json.dumps(env['order_data'], ensure_ascii=False, indent=2))
        env['manifest_data']['order_sha256'] = sha256_file(env['order_path'])
        env['manifest_data']['segments'][0]['narration_sha256'] = sha256_text(text)
        env['manifest_path'].write_text(json.dumps(env['manifest_data']))
        out = env['outdir']
    get_render()(env['order_path'], env['media_root'], env['manifest_path'], out)
    assert (out / 'sample.mp4').is_file()
    if case == 'crlf':
        srt = (out / 'subtitles.srt').read_bytes()
        assert '第一行\n第二行'.encode() in srt
        assert b'\r' not in srt


def test_render_cli_roundtrip(test_environment):
    from vmv.cli import main
    env = test_environment
    audio_out = env['tmp_path'] / 'cli-audio'
    assert main(['audio-import', '--order', str(env['order_path']), '--audio', 'seg-001='+str(env['wav_path']), '--output', str(audio_out)]) == 0
    assert main(['render', '--order', str(env['order_path']), '--media-root', str(env['media_root']), '--audio-manifest', str(audio_out / 'audio_manifest.json'), '--output', str(env['outdir'])]) == 0
    assert (env['outdir'] / 'sample.mp4').is_file()


@pytest.mark.parametrize('entries', [['broken'], ['seg-001='], ['seg-001=a.wav', 'seg-001=b.wav']])
def test_audio_import_cli_rejects_bad_mapping(test_environment, entries):
    from vmv.cli import main
    env = test_environment
    args = ['audio-import', '--order', str(env['order_path']), '--output', str(env['outdir'])]
    for entry in entries:
        args += ['--audio', entry]
    assert main(args) == 1
    assert not env['outdir'].exists()


def test_render_missing_chinese_font_fails_without_output(test_environment):
    env = test_environment
    with pytest.raises(ValueError):
        get_render()(env['order_path'], env['media_root'], env['manifest_path'], env['outdir'], subtitle_font=str(env['tmp_path'] / 'missing-font.ttf'))
    assert not env['outdir'].exists()
