import os, sys, time, json, tempfile, shutil, atexit
from pathlib import Path
from vmv.editorial_plan import validate_plan
from vmv.generation_process import run_generation

def render_recut(m, output_directory):
    if os.path.exists(output_directory): raise FileExistsError
    if m.get("fps") != 25: raise ValueError
    for k in ("media", "baseline", "ffmpeg", "ffprobe"):
        if not os.path.isfile(str(m.get(k))): raise ValueError
    for k in ("subtitles", "font"):
        if m.get(k) and not os.path.isfile(m[k]): raise ValueError

    if m.get("subtitles") and Path(m["subtitles"]).suffix.lower() not in (".srt", ".ass"):
        raise ValueError("unsupported subtitle extension")

    deadline = time.monotonic() + 60
    def run(argv, cwd=None):
        rem = deadline - time.monotonic()
        if rem <= 0: raise TimeoutError
        res = run_generation(argv, cwd=cwd, timeout=rem)
        return res.stdout if hasattr(res, "stdout") else res

    def probe(p):
        return json.loads(run([m["ffprobe"], "-v", "error"] + (["-count_frames"] if p != m["media"] else []) + ["-show_streams", "-show_format", "-of", "json", p]))

    src_dur = float(probe(m["media"])["format"]["duration"])
    plan = validate_plan(m, src_dur)
    exp_f = plan["expected_frames"]

    def check(info, res=False):
        st = info.get("streams", [])
        v = next((s for s in st if s.get("codec_type") == "video"), None)
        a = next((s for s in st if s.get("codec_type") == "audio"), None)
        if not v or not a: raise ValueError
        frames = int(v.get("nb_read_frames") or v.get("nb_frames") or 0)
        fps = v.get("r_frame_rate") or v.get("avg_frame_rate") or ""
        if fps not in ("25/1", "25") or frames != exp_f: raise ValueError
        if res and (v.get("width") != 1920 or v.get("height") != 1080): raise ValueError

    check(probe(m["baseline"]))

    tmp = tempfile.mkdtemp(dir=os.path.dirname(os.path.abspath(output_directory)))
    clean = lambda: shutil.rmtree(tmp, ignore_errors=True)
    atexit.register(clean)
    try:
        out_mp4 = _render_clips(m, plan, tmp, run)
        check(probe(out_mp4), res=True)
        run([m["ffmpeg"], "-v", "error", "-xerror", "-i", out_mp4, "-f", "null", "-"])

        def ahash(p):
            out = run([m["ffmpeg"], "-v", "error", "-i", p, "-map", "0:a:0", "-c:a", "pcm_s16le", "-f", "hash", "-hash", "sha256", "-"])
            return str(out).strip().split("=")[-1].strip()

        base_h, out_h = ahash(m["baseline"]), ahash(out_mp4)
        if base_h != out_h: raise ValueError

        ver = {"status": "needs_content_review", "frame_count": exp_f, "fps": 25,
               "duration_sec": exp_f / 25.0, "audio_hash_equal": True, "audio_sha256": out_h}
        with open(os.path.join(tmp, "plan.json"), "w") as f: json.dump(plan, f)
        with open(os.path.join(tmp, "verification.json"), "w") as f: json.dump(ver, f)

        if os.path.exists(output_directory): raise FileExistsError
        os.rename(tmp, output_directory)
        return ver
    finally:
        atexit.unregister(clean)
        clean()


def _render_clips(m, plan, tmp, run):
    tmp = Path(tmp)
    ffmpeg, fps = m["ffmpeg"], plan["fps"]
    clip_files = []
    for i, c in enumerate(plan["clips"]):
        cp = tmp / f"clip-{i}.mp4"
        clip_files.append(cp)
        if c.get("kind") == "color":
            cmd = [ffmpeg, "-y", "-f", "lavfi", "-i", f"color={c.get('color', 'black')}:s=1920x1080:r={fps}", "-frames:v", str(c["frames"]), "-vf", "setsar=1", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(cp)]
        else:
            cmd = [ffmpeg, "-y", "-ss", str(c["start_sec"]), "-i", m["media"], "-frames:v", str(c["frames"]), "-vf", f"scale=1920:1080,setsar=1,fps={fps}", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(cp)]
        run(cmd, cwd=tmp)
    list_txt = tmp / "concat.txt"
    list_txt.write_text("".join(f"file '{c.name}'\n" for c in clip_files))
    sub_vf = []
    if m.get("subtitles"):
        sp = Path(m["subtitles"])
        if sp.suffix.lower() == ".ass":
            shutil.copy(sp, tmp / "subtitles.ass")
            if m.get("font"):
                (tmp / "fonts").mkdir(exist_ok=True)
                shutil.copy(m["font"], tmp / "fonts/font.ttc")
            sub_vf = ["-vf", "subtitles=filename=subtitles.ass:fontsdir=fonts"]
        elif sp.suffix.lower() == ".srt":
            shutil.copy(sp, tmp / "subtitles.srt")
            from vmv.subtitle_support import prepare_subtitle_assets
            sub_vf = ["-vf", prepare_subtitle_assets(tmp, m.get("font"))[0]]
    out = tmp / "output.mp4"
    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_txt), "-i", m["baseline"], "-map", "0:v:0", "-map", "1:a:0"] + sub_vf + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy", "-frames:v", str(plan["expected_frames"]), "-movflags", "+faststart", str(out)]
    run(cmd, cwd=tmp)
    for cp in clip_files:
        cp.unlink(missing_ok=True)
    list_txt.unlink(missing_ok=True)
    shutil.rmtree(tmp / "fonts", ignore_errors=True)
    return out

if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        render_recut(json.load(f), sys.argv[2])
