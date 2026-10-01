"""Frame score collection and conservative adaptive hard-cut candidates."""
import math
import re
import shutil
import subprocess
from statistics import median
from pathlib import Path


def read_frame_scores(video: Path, duration: float):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ValueError('未找到 ffmpeg')
    # YDIF is needed because select's scene score can be zero on a flash's
    # return frame. Decode original frames (no sampling or scaling).
    # One AVIO writer is essential: two metadata writers buffer independently
    # and interleave headers/value lines once stdout exceeds their buffers.
    filters = "signalstats,select='gte(scene,0)',metadata=print:file=-"
    result = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-t', str(duration),
        '-i', str(video), '-map', '0:v:0', '-an', '-sn', '-vf', filters,
        '-f', 'null', '-'], capture_output=True, text=True, check=True, timeout=2700)
    frames = {}
    current = None
    for line in result.stdout.splitlines():
        header = re.search(r'frame:(\d+).*pts_time:([\d.eE+-]+)', line)
        if header:
            current = int(header[1])
            frames.setdefault(current, {'time': float(header[2])})
        elif current is not None and '=' in line:
            key, value = line.split('=', 1)
            if key in ('lavfi.scene_score', 'lavfi.signalstats.YDIF', 'lavfi.signalstats.YAVG'):
                frames[current][key] = float(value)
    rows = []
    for index, item in sorted(frames.items()):
        score = item.get('lavfi.scene_score')
        delta = item.get('lavfi.signalstats.YDIF')
        brightness = item.get('lavfi.signalstats.YAVG')
        if score is None or delta is None or brightness is None or not all(
                math.isfinite(v) and v >= 0 for v in (item['time'], score, delta, brightness)):
            raise ValueError('帧变化分数缺失或无效')
        if index != len(rows):
            raise ValueError('帧变化分数不连续')
        rows.append((item['time'], score, delta / 100, brightness))
    if not rows:
        raise ValueError('未读取到帧变化分数')
    return rows


def select_cutpoints(rows, fps, duration, threshold=.35, mode='adaptive',
                     floor=.04, ratio=3.0, min_duration=.5):
    """Adaptive additions require a local peak three times nearby activity.

    The fixed mode intentionally retains the old threshold and spacing for
    reproducible comparisons. A one-frame pulse is suppressed only in adaptive
    mode. These are candidates; movement and fades still need visual review.
    """
    radius = max(1, round(fps))
    candidates = []
    for i, (time, score, delta, brightness) in enumerate(rows):
        if not 0 < time < duration:
            continue
        if mode == 'adaptive' and duration-time < min_duration:
            # The analysis endpoint must obey the same half-second minimum as
            # internal candidates. No evidence beyond the final frame is claimed.
            continue
        if mode == 'fixed':
            accepted = score > threshold
        else:
            neighbors = [r[1] for r in rows[max(0, i-radius):i]]
            neighbors += [r[1] for r in rows[i+1:i+radius+1]]
            background = median(neighbors) if neighbors else 0
            # Equal peaks choose the earliest frame deterministically.
            peak = ((i == 0 or score > rows[i-1][1])
                    and (i+1 == len(rows) or score >= rows[i+1][1]))
            accepted = peak and (score > threshold or score >= max(floor, ratio*background))
            # A gradual fade has no large single-frame score. Treat its
            # sustained near-black trough as a transition candidate. Require
            # recovery on both sides and smooth adjacent steps, so a single
            # black pulse, monotonic fade or permanently dark shot is excluded.
            before = [r[3] for r in rows[max(0, i-radius):i]]
            after = [r[3] for r in rows[i+1:i+radius+1]]
            fade = (bool(before) and bool(after) and brightness <= 20
                and brightness < min(before) and brightness <= min(after)
                and rows[i-1][3] <= 24 and rows[i+1][3] <= 24
                and abs(rows[i-1][3]-brightness) <= 6
                and abs(rows[i+1][3]-brightness) <= 6
                and max(before) >= brightness+12
                and max(after) >= brightness+12)
            accepted = accepted or fade
            if (accepted and i+2 < len(rows) and delta >= floor
                    and rows[i+1][2] >= .8*delta and rows[i+2][2] <= .2*delta):
                accepted = False
        if accepted:
            candidates.append(time)
    cuts = []
    last = 0.0
    for time in candidates:
        if time-last >= min_duration:
            cuts.append(time)
            last = time
    return cuts
