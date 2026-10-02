import copy
import math

def validate_plan(plan, source_duration):
    if not isinstance(plan, dict):
        raise ValueError("plan must be a dict")
    if type(source_duration) not in (int, float) or not math.isfinite(source_duration) or source_duration <= 0:
        raise ValueError("source_duration must be finite int/float > 0")
    fps = plan.get("fps")
    if type(fps) is not int or not (1 <= fps <= 120):
        raise ValueError("fps must be an int between 1 and 120")
    expected_frames = plan.get("expected_frames")
    if type(expected_frames) is not int or expected_frames <= 0:
        raise ValueError("expected_frames must be an int > 0")
    clips = plan.get("clips")
    if type(clips) is not list or not clips:
        raise ValueError("clips must be a non-empty list")
    out = copy.deepcopy(plan)
    summed_frames = _validate_clips(out, fps, source_duration)
    if summed_frames != expected_frames:
        raise ValueError("summed frames does not match expected_frames")
    out["duration_sec"] = summed_frames / fps
    return out

def _validate_clips(out, fps, source_duration):
    def finite(x):
        return type(x) in (int, float) and math.isfinite(x)

    if not (finite(fps) and fps > 0 and finite(source_duration) and source_duration >= 0):
        raise ValueError
    if not isinstance(out, dict) or not isinstance(out.get("clips"), list):
        raise ValueError

    cum, intervals = 0, []
    for c in out["clips"]:
        if not isinstance(c, dict):
            raise ValueError
        frames = c.get("frames")
        if type(frames) is not int or frames <= 0:
            raise ValueError
        c["timeline_in_frame"], c["timeline_out_frame"] = cum, cum + frames
        cum += frames

        kind = c.get("kind")
        if kind == "color":
            if c.get("color") not in ("black", "white"):
                raise ValueError
        elif kind == "video":
            start, job = c.get("start_sec"), c.get("job")
            if not (finite(start) and start >= 0 and isinstance(job, str) and job.strip()):
                raise ValueError
            end = start + frames / fps
            if end > source_duration + 1e-9:
                raise ValueError
            c["source_out_sec"] = end

            cin, cout = c.get("critical_in_sec"), c.get("critical_out_sec")
            if "critical_in_sec" in c or "critical_out_sec" in c:
                if not (finite(cin) and finite(cout) and start - 1e-9 <= cin < cout <= end + 1e-9):
                    raise ValueError
            intervals.append((start, end))
        else:
            raise ValueError

    cur_end = -math.inf
    for s, e in sorted(intervals):
        if s < cur_end - 1e-9:
            raise ValueError
        cur_end = max(cur_end, e)

    return cum
