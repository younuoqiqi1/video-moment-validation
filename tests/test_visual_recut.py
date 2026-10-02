import os, shutil, subprocess, pytest
from vmv.visual_recut import render_recut
from vmv.generation_process import run_generation

FFMPEG = os.getenv("VMV_TEST_FFMPEG") or shutil.which("ffmpeg")
FFPROBE = os.getenv("VMV_TEST_FFPROBE") or shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="missing ffmpeg/ffprobe")

def pcm_hash(path):
    return run_generation([FFMPEG, "-v", "error", "-i", str(path), "-map", "0:a:0", "-c:a", "pcm_s16le", "-f", "hash", "-hash", "sha256", "-"], timeout=10).stdout.strip()

@pytest.fixture
def test_setup(tmp_path):
    src, base = tmp_path / "src.mp4", tmp_path / "base.mp4"
    run_generation([FFMPEG, "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=2", "-c:v", "libx264", str(src)], timeout=10)
    run_generation([FFMPEG, "-y", "-f", "lavfi", "-i", "color=s=1920x1080:r=25:d=1", "-f", "lavfi", "-i", "sine=sample_rate=48000:duration=1", "-c:v", "libx264", "-c:a", "aac", "-ac", "1", str(base)], timeout=10)
    manifest = {
        "media": str(src), "baseline": str(base), "ffmpeg": FFMPEG, "ffprobe": FFPROBE, "fps": 25, "expected_frames": 25,
        "clips": [{"kind": "video", "start_sec": 1.0, "frames": 12, "job": "reaction"}, {"kind": "video", "start_sec": 0.0, "frames": 13, "job": "setup"}],
    }
    return manifest, tmp_path

def test_render_recut_success(test_setup):
    manifest, tmp = test_setup
    outdir = tmp / "out"
    res = render_recut(manifest, outdir)
    assert (outdir / "output.mp4").is_file() and (outdir / "plan.json").is_file()
    assert res["status"] == "needs_content_review" and res["frame_count"] == 25 and res["audio_hash_equal"] is True
    assert pcm_hash(manifest["baseline"]) == pcm_hash(outdir / "output.mp4")

def test_render_recut_source_overlap_raises(test_setup):
    manifest, tmp = test_setup
    outdir = tmp / "overlap_out"
    bad = dict(manifest, clips=[{"kind": "video", "start_sec": 0.0, "frames": 12, "job": "reaction"}, {"kind": "video", "start_sec": 0.0, "frames": 13, "job": "setup"}])
    with pytest.raises(ValueError):
        render_recut(bad, outdir)
    assert not outdir.exists()

def test_render_recut_existing_dest_raises(test_setup):
    manifest, tmp = test_setup
    dest = tmp / "existing"
    dest.mkdir()
    sentinel = dest / "sentinel.txt"
    sentinel.write_text("keep")
    with pytest.raises(FileExistsError):
        render_recut(manifest, dest)
    assert sentinel.read_text() == "keep"

def test_baseline_frame_mismatch(test_setup):
    m, tmp = test_setup
    bad = dict(m, expected_frames=24, clips=[m["clips"][0], dict(m["clips"][1], frames=12)])
    out = tmp / "mismatch"
    with pytest.raises(ValueError): render_recut(bad, out)
    assert not out.exists()

def test_unsupported_subtitle_extension(test_setup):
    m, tmp = test_setup
    txt = tmp / "x.txt"; txt.write_text("sub")
    out = tmp / "bad_ext"
    with pytest.raises(ValueError): render_recut(dict(m, subtitles=str(txt)), out)
    assert not out.exists()

@pytest.mark.parametrize("ext", [".srt", ".SRT", ".SrT"])
def test_render_recut_srt(test_setup, ext):
    from vmv.subtitle_support import DEFAULT_FONTS
    font = next((f for f in DEFAULT_FONTS if os.path.exists(f)), None)
    if not font: pytest.skip("no default font found")
    m, tmp = test_setup
    cue = "1\n00:00:00,000 --> 00:00:01,000\nsyntheticcaption\n"
    srt = tmp / ("sub" + ext)
    srt.write_text(cue)
    out = tmp / "out_srt"
    res = render_recut(dict(m, subtitles=str(srt), font=font), out)
    assert res["frame_count"] == 25 and (out / "subtitles.srt").read_text() == cue
