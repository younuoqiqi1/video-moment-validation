import copy
import math
import re


def _is_safe_ascii(s: str) -> bool:
    return isinstance(s, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]+", s))


def _is_finite_num(val) -> bool:
    return (
        type(val) in (int, float)
        and not isinstance(val, bool)
        and math.isfinite(val)
    )


def plan_timeline(order: dict, audio_durations: dict, fps: int = 25) -> dict:
    try:
        if not isinstance(order, dict):
            raise ValueError("Order must be a dict")
        if order.get("state") != "ready_for_tts":
            raise ValueError("Order state must be 'ready_for_tts'")
        if type(order.get("sample")) is not bool:
            raise ValueError("Order sample must be an exact bool")
        if not _is_safe_ascii(order.get("media_id")):
            raise ValueError("Order media_id must be safe ASCII")

        for key in ("source_sha256", "document_sha256"):
            sha = order.get(key)
            if not (
                isinstance(sha, str)
                and len(sha) == 64
                and re.match(r"^[0-9a-f]{64}$", sha)
            ):
                raise ValueError(f"{key} must be 64-char lowercase hex")

        if not (
            isinstance(order.get("source_path"), str) and order["source_path"]
        ):
            raise ValueError("source_path must be a non-empty string")
        if order.get("timing_basis") != "source_clip_duration_not_voice":
            raise ValueError("Invalid timing_basis")

        dur_sec = order.get("duration_sec")
        if not _is_finite_num(dur_sec) or dur_sec <= 0:
            raise ValueError("duration_sec must be a finite positive number")

        segments = order.get("segments")
        if not isinstance(segments, list) or len(segments) == 0:
            raise ValueError("segments must be a non-empty list")

        if type(fps) is not int or isinstance(fps, bool) or not (1 <= fps <= 120):
            raise ValueError("fps must be an exact integer between 1 and 120")

        if not isinstance(audio_durations, dict):
            raise ValueError("audio_durations must be a dict")

        seg_ids = set()
        for seg in segments:
            if not isinstance(seg, dict):
                raise ValueError("Segment must be a dict")
            sid = seg.get("id")
            if not _is_safe_ascii(sid) or sid in seg_ids:
                raise ValueError(f"Invalid or duplicate segment id: {sid}")
            seg_ids.add(sid)

            narr = seg.get("narration")
            if not isinstance(narr, str) or not narr.strip():
                raise ValueError("Segment narration must be a non-blank string")

            shots = seg.get("shots")
            if not isinstance(shots, list) or len(shots) == 0:
                raise ValueError("Segment shots must be a non-empty list")

            shot_ids = set()
            for shot in shots:
                if not isinstance(shot, dict):
                    raise ValueError("Shot must be a dict")
                shid = shot.get("shot_id")
                if not _is_safe_ascii(shid) or shid in shot_ids:
                    raise ValueError(f"Invalid or duplicate shot_id: {shid}")
                shot_ids.add(shid)

                for num_key in (
                    "source_in_sec",
                    "source_out_sec",
                    "timeline_in_sec",
                    "timeline_out_sec",
                ):
                    if not _is_finite_num(shot.get(num_key)):
                        raise ValueError(f"Shot {num_key} must be finite number")

                if not (0 <= shot["source_in_sec"] < shot["source_out_sec"]):
                    raise ValueError("Invalid source_in_sec/source_out_sec bounds")

        if set(audio_durations.keys()) != seg_ids:
            raise ValueError("audio_durations keys must match segment ids exactly")
        for sid, adur in audio_durations.items():
            if not _is_finite_num(adur) or adur <= 0:
                raise ValueError(f"Invalid audio duration for segment {sid}")

        curr_orig_tl = 0.0
        total_src_cap = 0.0
        for seg in segments:
            for shot in seg["shots"]:
                t_in = shot["timeline_in_sec"]
                t_out = shot["timeline_out_sec"]
                cap = shot["source_out_sec"] - shot["source_in_sec"]
                if abs(t_in - curr_orig_tl) > 1e-6:
                    raise ValueError("Input timeline is not contiguous")
                if abs((t_out - t_in) - cap) > 1e-6:
                    raise ValueError("Timeline duration does not match capacity")
                curr_orig_tl = t_out
                total_src_cap += cap

        if abs(curr_orig_tl - dur_sec) > 1e-6 or abs(total_src_cap - dur_sec) > 1e-6:
            raise ValueError("Input timeline length does not match duration_sec")

        global_frame_count = 0
        res_segments = []

        for seg in segments:
            sid = seg["id"]
            voice_dur = audio_durations[sid]
            target_frames = math.ceil(voice_dur * fps - 1e-9)

            caps = [
                math.floor((sh["source_out_sec"] - sh["source_in_sec"]) * fps + 1e-9)
                for sh in seg["shots"]
            ]
            num_shots = len(seg["shots"])
            sum_caps = sum(caps)

            for c in caps:
                if c < 1:
                    raise ValueError("Each shot capacity must be at least 1 frame")
            if not (num_shots <= target_frames <= sum_caps):
                raise ValueError(
                    f"Target frames {target_frames} out of bounds [{num_shots}, {sum_caps}]"
                )

            alloc = [1] * num_shots
            rem_frames = target_frames - num_shots
            spare_caps = [c - 1 for c in caps]
            total_spare = sum(spare_caps)

            if total_spare > 0 and rem_frames > 0:
                add_list = [(rem_frames * s) // total_spare for s in spare_caps]
                rem_list = [(rem_frames * s) % total_spare for s in spare_caps]
                for i in range(num_shots):
                    alloc[i] += add_list[i]
                leftovers = rem_frames - sum(add_list)
                sort_order = sorted(range(num_shots), key=lambda i: (-rem_list[i], i))
                for idx in sort_order:
                    if leftovers <= 0:
                        break
                    if alloc[idx] < caps[idx]:
                        alloc[idx] += 1
                        leftovers -= 1

            seg_start_frame = global_frame_count
            res_shots = []
            for i, shot in enumerate(seg["shots"]):
                sh_frames = alloc[i]
                sh_start = global_frame_count
                sh_end = global_frame_count + sh_frames
                global_frame_count = sh_end

                src_in = round(shot["source_in_sec"], 6)
                src_out = round(shot["source_in_sec"] + sh_frames / fps, 6)
                if src_out > shot["source_out_sec"] + 1e-6:
                    raise ValueError("Rounded source_out_sec overflows original bounds")

                res_shots.append(
                    {
                        "shot_id": shot["shot_id"],
                        "source_in_sec": src_in,
                        "source_out_sec": src_out,
                        "timeline_in_sec": round(sh_start / fps, 6),
                        "timeline_out_sec": round(sh_end / fps, 6),
                    }
                )

            seg_end_frame = global_frame_count
            res_segments.append(
                {
                    "id": sid,
                    "narration": seg["narration"],
                    "audio_duration_sec": voice_dur,
                    "timeline_in_sec": round(seg_start_frame / fps, 6),
                    "timeline_out_sec": round(seg_end_frame / fps, 6),
                    "shots": res_shots,
                }
            )

        total_dur_sec = round(global_frame_count / fps, 6)
        if total_dur_sec > 180.0 + 1e-6:
            raise ValueError(f"Total duration {total_dur_sec} exceeds 180 seconds")

        result = copy.deepcopy(order)
        result.update(
            {
                "state": "ready_for_render",
                "timing_basis": "voice_duration",
                "fps": fps,
                "duration_sec": total_dur_sec,
                "segments": res_segments,
            }
        )

        curr_verify = 0.0
        for s in result["segments"]:
            if abs(s["timeline_in_sec"] - curr_verify) > 1e-6:
                raise ValueError("Output segment timeline non-contiguous")
            curr_sh = s["timeline_in_sec"]
            for sh in s["shots"]:
                if abs(sh["timeline_in_sec"] - curr_sh) > 1e-6:
                    raise ValueError("Output shot timeline non-contiguous")
                if sh["source_in_sec"] >= sh["source_out_sec"]:
                    raise ValueError("Output shot invalid source range")
                curr_sh = sh["timeline_out_sec"]
            if abs(s["timeline_out_sec"] - curr_sh) > 1e-6:
                raise ValueError("Segment end mismatch with last shot")
            curr_verify = s["timeline_out_sec"]

        if abs(curr_verify - total_dur_sec) > 1e-6:
            raise ValueError("Output total duration mismatch")

        return result
    except (TypeError, KeyError, AttributeError) as exc:
        raise ValueError(f"Invalid input data structure: {exc}") from exc
