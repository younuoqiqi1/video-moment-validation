import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import wave
import pytest

RAW_ORDER = {
    "state": "ready_for_tts", "sample": True, "media_id": "test",
    "source_sha256": "a" * 64, "document_sha256": "b" * 64,
    "source_path": "input.mp4", "timing_basis": "source_clip_duration_not_voice",
    "duration_sec": 2, "segments": [{"id": "seg-001", "narration": "合成测试。",
        "shots": [{"shot_id": "red", "source_in_sec": 0, "source_out_sec": 2,
                   "timeline_in_sec": 0, "timeline_out_sec": 2}]}],
}


def _get_import_audio():
    try:
        from vmv.voice_import import import_audio

        return import_audio
    except (ImportError, ModuleNotFoundError) as err:
        pytest.fail(f"vmv.voice_import module missing: {err}", pytrace=False)


@pytest.fixture(autouse=True)
def check_ffprobe():
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe unavailable")


@pytest.fixture
def sine_audio(tmp_path: Path) -> Path:
    wav_path = tmp_path / "source_seg001.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        frames = b"".join(
            struct.pack(
                "<h", int(16000 * math.sin(2 * math.pi * 440 * i / 22050))
            )
            for i in range(22050)
        )
        wf.writeframes(frames)
    return wav_path


def make_order_file(path: Path, ready_for_tts: bool = True) -> bytes:
    order = dict(RAW_ORDER, state="ready_for_tts" if ready_for_tts else "draft")
    data = json.dumps(order, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(data)
    return data


def test_import_audio_success(tmp_path: Path, sine_audio: Path):
    fn = _get_import_audio()
    order_path = tmp_path / "order.json"
    order_bytes = make_order_file(order_path, ready_for_tts=True)
    outdir = tmp_path / "out"

    fn(order_path, {"seg-001": sine_audio}, outdir)

    manifest_path = outdir / "audio_manifest.json"
    assert manifest_path.is_file()
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert m["sample"] is True
    assert m["provider"] == "local_import"
    assert m["order_sha256"] == hashlib.sha256(order_bytes).hexdigest()

    seg = m["segments"][0]
    assert seg["id"] == "seg-001"
    assert (
        seg["narration_sha256"]
        == hashlib.sha256("合成测试。".encode("utf-8")).hexdigest()
    )

    copied = outdir / seg["path"]
    orig_bytes = sine_audio.read_bytes()
    assert copied.read_bytes() == orig_bytes
    assert seg["sha256"] == hashlib.sha256(orig_bytes).hexdigest()


def test_import_audio_nonexistent_segment(tmp_path: Path, sine_audio: Path):
    fn = _get_import_audio()
    order_path = tmp_path / "order.json"
    make_order_file(order_path, ready_for_tts=True)
    outdir = tmp_path / "out"

    with pytest.raises((ValueError, KeyError)):
        fn(order_path, {"unknown-seg": sine_audio}, outdir)


def test_import_audio_missing_file(tmp_path: Path):
    fn = _get_import_audio()
    order_path = tmp_path / "order.json"
    make_order_file(order_path, ready_for_tts=True)
    outdir = tmp_path / "out"

    with pytest.raises((OSError, ValueError)):
        fn(order_path, {"seg-001": tmp_path / "not_found.wav"}, outdir)
    assert not outdir.exists()


def test_import_audio_existing_output_marker_preserved(
    tmp_path: Path, sine_audio: Path
):
    fn = _get_import_audio()
    order_path = tmp_path / "order.json"
    make_order_file(order_path, ready_for_tts=True)
    outdir = tmp_path / "out"
    outdir.mkdir(parents=True)
    marker = outdir / "audio_manifest.json"
    marker.write_text("sentinel_marker", encoding="utf-8")

    with pytest.raises(FileExistsError):
        fn(order_path, {"seg-001": sine_audio}, outdir)
    assert marker.read_text(encoding="utf-8") == "sentinel_marker"


def test_import_audio_unconfirmed_order_rejects(
    tmp_path: Path, sine_audio: Path
):
    fn = _get_import_audio()
    order_path = tmp_path / "order.json"
    make_order_file(order_path, ready_for_tts=False)
    outdir = tmp_path / "out"

    with pytest.raises(ValueError):
        fn(order_path, {"seg-001": sine_audio}, outdir)
    assert not outdir.exists()
