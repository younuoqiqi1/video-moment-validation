import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from vmv.generation_process import run_generation
from vmv.voice_timeline import plan_timeline
from vmv.subtitle_support import prepare_subtitle_assets, normalize_subtitle_text


def render(order_path, media_root, audio_manifest_path, outdir, ffmpeg='ffmpeg', ffprobe='ffprobe', subtitle_font=None, subtitle_font_name=None):
    deadline = time.monotonic() + 60.0

    def remaining_timeout():
        rem = deadline - time.monotonic()
        if rem <= 0:
            raise ValueError("Global execution deadline (60s) exceeded")
        return min(rem, 60.0)

    def run_cmd(argv, cwd=None):
        try:
            return run_generation(argv, timeout=remaining_timeout(), cwd=cwd)
        except OSError:
            raise
        except Exception:
            raise ValueError(f"Subprocess execution failed: {Path(argv[0]).name}")

    def hash_file_streaming(filepath):
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            while True:
                remaining_timeout()
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def validate_safe_path(rel_path, base_dir):
        if not isinstance(rel_path, str) or not rel_path:
            raise ValueError("Invalid relative path string")
        if os.path.isabs(rel_path) or "\\" in rel_path or ":" in rel_path:
            raise ValueError(f"Unsafe path characters or absolute path: {rel_path}")
        parts = Path(rel_path).parts
        if any(p == ".." for p in parts):
            raise ValueError(f"Path escape forbidden: {rel_path}")

        base_res = base_dir.resolve()
        if os.path.islink(base_dir):
            raise ValueError(f"Base directory cannot be a symlink: {base_dir}")

        curr = base_dir
        for p in parts:
            curr = curr / p
            if os.path.islink(curr):
                raise ValueError(f"Symlinks forbidden: {curr}")

        res = curr.resolve()
        try:
            res.relative_to(base_res)
        except ValueError:
            raise ValueError(f"Path escapes root directory: {rel_path}")

        if not curr.is_file():
            raise ValueError(f"Target file does not exist: {curr}")
        return curr

    outdir = Path(outdir)
    if os.path.lexists(outdir):
        raise ValueError(f"Output directory or link already exists: {outdir}")

    order_p = Path(order_path)
    if os.path.islink(order_p) or not order_p.is_file():
        raise ValueError("Invalid or symlinked order path")
    order_sha256 = hash_file_streaming(order_p)

    try:
        with open(order_p, "r", encoding="utf-8") as f:
            order = json.load(f)
    except Exception as e:
        raise ValueError(f"Malformed order JSON: {e}")

    if not isinstance(order, dict):
        raise ValueError("Order root must be a JSON object")

    req_order_keys = [
        "state", "sample", "media_id", "source_sha256", "source_path",
        "document_sha256", "timing_basis", "duration_sec", "segments"
    ]
    if any(k not in order for k in req_order_keys):
        raise ValueError("Order missing required fields")
    if type(order["sample"]) is not bool:
        raise ValueError("Invalid sample flag in order")
    if order.get("timing_basis") != "source_clip_duration_not_voice":
        raise ValueError(f"Unsupported timing_basis: {order.get('timing_basis')}")
    if not isinstance(order["segments"], list) or not order["segments"]:
        raise ValueError("Order segments must be a non-empty list")

    seg_ids = set()
    for s in order["segments"]:
        if not isinstance(s, dict) or "id" not in s or "narration" not in s or "shots" not in s:
            raise ValueError("Malformed order segment")
        if s["id"] in seg_ids:
            raise ValueError(f"Duplicate segment ID: {s['id']}")
        seg_ids.add(s["id"])
        if not isinstance(s["narration"], str) or not isinstance(s["shots"], list) or not s["shots"]:
            raise ValueError(f"Invalid segment narration or shots in segment {s.get('id')}")

    manifest_p = Path(audio_manifest_path)
    if os.path.islink(manifest_p) or not manifest_p.is_file():
        raise ValueError("Invalid or symlinked audio manifest path")
    manifest_sha256 = hash_file_streaming(manifest_p)

    try:
        with open(manifest_p, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        raise ValueError(f"Malformed audio manifest JSON: {e}")

    if not isinstance(manifest, dict):
        raise ValueError("Audio manifest root must be a JSON object")

    for k in ["sample", "order_sha256", "provider", "segments"]:
        if k not in manifest:
            raise ValueError(f"Audio manifest missing field: {k}")

    if type(manifest["sample"]) is not bool or manifest["sample"] != order["sample"]:
        raise ValueError("Manifest sample flag invalid or does not match order")
    if manifest["order_sha256"] != order_sha256:
        raise ValueError("Manifest order_sha256 does not match actual order bytes")
    if not isinstance(manifest["provider"], str) or not manifest["provider"].strip():
        raise ValueError("Manifest provider must be a non-empty string")
    if not isinstance(manifest["segments"], list) or len(manifest["segments"]) != len(order["segments"]):
        raise ValueError("Manifest segments length mismatch with order")

    audio_paths = {}
    manifest_seg_map = {}
    for o_seg, m_seg in zip(order["segments"], manifest["segments"]):
        if not isinstance(m_seg, dict) or m_seg.get("id") != o_seg["id"]:
            raise ValueError("Manifest segment ID or ordering mismatch")
        for k in ["id", "narration_sha256", "path", "sha256"]:
            if k not in m_seg:
                raise ValueError(f"Manifest segment missing key: {k}")

        narr_hash = hashlib.sha256(o_seg["narration"].encode("utf-8")).hexdigest()
        if m_seg["narration_sha256"] != narr_hash:
            raise ValueError(f"Narration SHA256 mismatch in segment {o_seg['id']}")

        a_file = validate_safe_path(m_seg["path"], manifest_p.parent)
        if a_file.suffix.lower() not in ('.wav', '.aiff', '.aif', '.mp3'):
            raise ValueError(f"Unsupported audio extension: {a_file.suffix}")
        if a_file.stat().st_size == 0:
            raise ValueError(f"Zero-byte audio file rejected: {a_file}")

        actual_a_hash = hash_file_streaming(a_file)
        if actual_a_hash != m_seg["sha256"]:
            raise ValueError(f"Audio file hash mismatch in segment {o_seg['id']}")

        audio_paths[o_seg["id"]] = a_file
        manifest_seg_map[o_seg["id"]] = m_seg

    media_root_p = Path(media_root)
    source_video_p = validate_safe_path(order["source_path"], media_root_p)
    actual_source_sha = hash_file_streaming(source_video_p)
    if actual_source_sha != order["source_sha256"]:
        raise ValueError("Source video SHA256 mismatch")

    res = run_cmd([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source_video_p)])
    try:
        v_probe = json.loads(res.stdout if hasattr(res, "stdout") else str(res))
        v_stream = next(s for s in v_probe.get("streams", []) if s.get("codec_type") == "video")
        v_dur = float(v_stream.get("duration") or v_probe.get("format", {}).get("duration", 0))
    except Exception:
        raise ValueError("Failed to probe source video stream and duration")

    if not (math.isfinite(v_dur) and v_dur > 0):
        raise ValueError("Source video duration not positive finite")

    max_source_out = max(float(shot["source_out_sec"]) for seg in order["segments"] for shot in seg["shots"])
    if max_source_out > v_dur + (1.0 / 25.0):
        raise ValueError(f"Selected source out ({max_source_out}s) exceeds source video duration ({v_dur}s)")

    audio_durations = {}
    for sid, a_file in audio_paths.items():
        a_res = run_cmd([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(a_file)])
        try:
            a_probe = json.loads(a_res.stdout if hasattr(a_res, "stdout") else str(a_res))
            a_stream = next(s for s in a_probe.get("streams", []) if s.get("codec_type") == "audio")
            dur = float(a_stream.get("duration") or a_probe.get("format", {}).get("duration", 0))
        except Exception:
            raise ValueError(f"Failed to probe audio duration for segment {sid}")
        if not (math.isfinite(dur) and dur > 0):
            raise ValueError(f"Audio duration not positive finite for segment {sid}")
        audio_durations[sid] = dur

    try:
        timeline = plan_timeline(order, audio_durations, fps=25)
    except Exception as e:
        raise ValueError(f"plan_timeline failed: {e}")

    if not isinstance(timeline, dict) or timeline.get("state") != "ready_for_render":
        raise ValueError("Timeline state not ready_for_render")
    if timeline.get("timing_basis") != "voice_duration":
        raise ValueError("Timeline timing_basis must be voice_duration")

    timeline_dur = float(timeline.get("duration_sec", 0))
    if not (0 < timeline_dur <= 180.0):
        raise ValueError(f"Timeline duration out of bounds (max 180s): {timeline_dur}")

    outdir.parent.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(dir=outdir.parent, prefix="vmv_tmp_"))

    try:
        with open(tmpdir / "voice-timeline.json", "w", encoding="utf-8") as f:
            json.dump(timeline, f, indent=2)

        def fmt_srt(sec):
            ms = int(round(sec * 1000.0))
            h = ms // 3600000
            ms %= 3600000
            m = ms // 60000
            ms %= 60000
            s = ms // 1000
            ms %= 1000
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        srt_lines = []
        for idx, seg in enumerate(timeline["segments"], 1):
            clean_narr = normalize_subtitle_text(seg["narration"])

            t_in = float(seg["timeline_in_sec"])
            t_out = t_in + float(seg.get("audio_duration_sec", audio_durations[seg["id"]]))
            srt_lines.append(f"{idx}\n{fmt_srt(t_in)} --> {fmt_srt(t_out)}\n{clean_narr}\n")

        subtitles_path = tmpdir / "subtitles.srt"
        with open(subtitles_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines) + "\n")

        all_shots = []
        for seg in timeline["segments"]:
            all_shots.extend(seg.get("shots", []))
        if not all_shots and "shots" in timeline:
            all_shots = timeline["shots"]

        clip_names = []
        for i, shot in enumerate(all_shots):
            c_name = f"clip-{i}.mp4"
            c_path = tmpdir / c_name
            s_in = float(shot["source_in_sec"])
            if "timeline_out_sec" in shot and "timeline_in_sec" in shot:
                s_dur = float(shot["timeline_out_sec"]) - float(shot["timeline_in_sec"])
            elif "duration_sec" in shot:
                s_dur = float(shot["duration_sec"])
            else:
                s_dur = float(shot["source_out_sec"]) - float(shot["source_in_sec"])

            frames = int(round(s_dur * 25.0))
            cmd = [
                ffmpeg, "-nostdin", "-v", "error", "-ss", f"{s_in:.6f}",
                "-i", str(source_video_p.resolve()), "-t", f"{s_dur:.6f}", "-an",
                "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25,format=yuv420p",
                "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                str(c_path.resolve())
            ]
            run_cmd(cmd)
            clip_names.append(c_name)

        audio_names = []
        for i, seg in enumerate(timeline["segments"]):
            a_name = f"audio-{i}.wav"
            a_path = tmpdir / a_name
            seg_target_dur = max(
                float(seg.get("timeline_out_sec", 0)) - float(seg.get("timeline_in_sec", 0)),
                float(seg.get("audio_duration_sec", 0))
            )
            cmd = [
                ffmpeg, "-nostdin", "-v", "error",
                "-i", str(audio_paths[seg["id"]].resolve()),
                "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
                "-af", "apad", "-t", f"{seg_target_dur:.6f}",
                str(a_path.resolve())
            ]
            run_cmd(cmd)
            audio_names.append(a_name)

        v_list_path = tmpdir / "video-list.txt"
        with open(v_list_path, "w", encoding="utf-8") as f:
            for n in clip_names:
                f.write(f"file '{n}'\n")

        a_list_path = tmpdir / "audio-list.txt"
        with open(a_list_path, "w", encoding="utf-8") as f:
            for n in audio_names:
                f.write(f"file '{n}'\n")

        subtitle_filter, font_name = prepare_subtitle_assets(tmpdir, None if subtitle_font is None else str(subtitle_font), subtitle_font_name)
        sample_path = tmpdir / "sample.mp4"

        final_cmd = [
            ffmpeg, "-nostdin", "-v", "info",
            "-f", "concat", "-safe", "1", "-i", str(v_list_path.resolve()),
            "-f", "concat", "-safe", "1", "-i", str(a_list_path.resolve()),
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", subtitle_filter,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "1",
            "-t", f"{timeline_dur:.6f}", "-movflags", "+faststart",
            str(sample_path.resolve())
        ]
        final_result = run_cmd(final_cmd, cwd=tmpdir.resolve())
        if 'failed to find any fallback with glyph' in final_result.stderr.lower():
            raise ValueError('字幕字体缺少所需字符，请提供支持对应文字的 --subtitle-font')

        verify_res = run_cmd([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(sample_path.resolve())])
        try:
            ver_data = json.loads(verify_res.stdout if hasattr(verify_res, "stdout") else str(verify_res))
            v_st = next(s for s in ver_data.get("streams", []) if s.get("codec_type") == "video")
            a_st = next(s for s in ver_data.get("streams", []) if s.get("codec_type") == "audio")
            actual_dur = float(ver_data.get("format", {}).get("duration") or v_st.get("duration", 0))
        except Exception:
            raise ValueError("Failed to probe final rendered output")

        if v_st.get("codec_name", "").lower() != "h264" or v_st.get("width") != 1920 or v_st.get("height") != 1080:
            raise ValueError("Final video must be H.264 1920x1080")
        if a_st.get("codec_name", "").lower() != "aac":
            raise ValueError("Final audio must be AAC")
        if not (timeline_dur - 0.08 <= actual_dur <= timeline_dur + 0.1):
            raise ValueError(f"Actual duration {actual_dur}s out of tolerance for timeline {timeline_dur}s")

        run_cmd([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(sample_path.resolve()), "-f", "null", "-"])

        report = {
            "status": "rendered",
            "voice_provider": manifest["provider"],
            "order_sha256": order_sha256,
            "audiomanifest_sha256": manifest_sha256,
            "source_sha256": order["source_sha256"],
            "audio_sha256_by_segment": {
                s["id"]: manifest_seg_map[s["id"]]["sha256"] for s in order["segments"]
            },
            "planned_duration_sec": timeline_dur,
            "actual_duration_sec": actual_dur,
            "codecs": {"video": "h264", "audio": "aac"},
            "resolution": "1920x1080",
            "fps": 25,
            "subtitle_font": font_name,
            "subtitle_glyphs_verified": True,
        }
        with open(tmpdir / "render-report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        keep = {"sample.mp4", "subtitles.srt", "voice-timeline.json", "render-report.json"}
        for item in list(tmpdir.iterdir()):
            if item.name not in keep:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)

        if os.path.lexists(outdir):
            raise ValueError(f"Output path was created externally during render: {outdir}")

        remaining_timeout()
        os.rename(tmpdir, outdir)

        return report

    finally:
        if tmpdir.exists():
            shutil.rmtree(tmpdir, ignore_errors=True)
