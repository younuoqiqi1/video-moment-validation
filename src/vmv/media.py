"""Media probing, timecode utilities, and scene detection for Stage 1."""

import hashlib
from html import escape
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from vmv.stages import StageResult
from vmv.scene_detection import read_frame_scores, select_cutpoints


class MediaProbeError(Exception):
    """Raised when probing media fails or format is invalid."""


def seconds_to_timecode(seconds: float, fps: float = 25.0, format_type: str = "broadcast") -> str:
    """
    Convert floating seconds to standard timecode string.
    - broadcast: HH:MM:SS:FF (frame-based)
    - ms: HH:MM:SS.mmm (millisecond-based)
    """
    if seconds < 0:
        raise ValueError(f"Seconds cannot be negative: {seconds}")
    if fps <= 0:
        raise ValueError(f"FPS must be positive: {fps}")

    total_seconds = int(seconds)
    remainder = seconds - total_seconds

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if format_type == "ms":
        millis = int(round(remainder * 1000))
        if millis >= 1000:
            millis = 0
            secs += 1
            if secs >= 60:
                secs = 0
                minutes += 1
                if minutes >= 60:
                    minutes = 0
                    hours += 1
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    else:
        # Default broadcast HH:MM:SS:FF (SMPTE frame convention)
        frame = int(remainder * fps + 1e-5)
        if frame >= int(round(fps)):
            frame = 0
            secs += 1
            if secs >= 60:
                secs = 0
                minutes += 1
                if minutes >= 60:
                    minutes = 0
                    hours += 1
        return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frame:02d}"


def timecode_to_seconds(timecode: str, fps: float = 25.0) -> float:
    """
    Parse HH:MM:SS:FF or HH:MM:SS.mmm into floating seconds.
    """
    if fps <= 0:
        raise ValueError(f"FPS must be positive: {fps}")

    # Check HH:MM:SS.mmm
    ms_match = re.match(r"^(\d{2,}):(\d{2}):(\d{2})\.(\d{1,6})$", timecode)
    if ms_match:
        h, m, s, frac = ms_match.groups()
        fraction = float(f"0.{frac}")
        return int(h) * 3600 + int(m) * 60 + int(s) + fraction

    # Check HH:MM:SS:FF
    ff_match = re.match(r"^(\d{2,}):(\d{2}):(\d{2}):(\d{2})$", timecode)
    if ff_match:
        h, m, s, f = ff_match.groups()
        return int(h) * 3600 + int(m) * 60 + int(s) + (int(f) / fps)

    raise ValueError(f"Invalid timecode format: '{timecode}'. Expected HH:MM:SS:FF or HH:MM:SS.mmm")


@dataclass
class VideoStreamInfo:
    codec: str
    width: int
    height: int
    fps: float
    aspect_ratio: str
    pix_fmt: str
    bit_rate: int | None
    total_frames: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AudioStreamInfo:
    codec: str
    sample_rate: int
    channels: int
    channel_layout: str
    bit_rate: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SubtitleStreamInfo:
    codec: str
    language: str | None
    title: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MediaInfo:
    media_id: str
    filename: str
    relative_path: str
    file_size_bytes: int
    file_size_mb: float
    duration_sec: float
    duration_timecode: str
    format_name: str
    video: VideoStreamInfo | None
    audio: AudioStreamInfo | None
    subtitles: list[SubtitleStreamInfo]
    subtitle_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "media_id": self.media_id,
            "filename": self.filename,
            "relative_path": self.relative_path,
            "file_size_bytes": self.file_size_bytes,
            "file_size_mb": self.file_size_mb,
            "duration_sec": self.duration_sec,
            "duration_timecode": self.duration_timecode,
            "format_name": self.format_name,
            "video": self.video.to_dict() if self.video else None,
            "audio": self.audio.to_dict() if self.audio else None,
            "subtitles": [s.to_dict() for s in self.subtitles],
            "subtitle_summary": self.subtitle_summary,
        }


@dataclass
class SceneItem:
    index: int
    start_sec: float
    start_timecode: str
    end_sec: float
    end_timecode: str
    duration_sec: float
    start_frame: int
    end_frame: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_stable_media_id(file_path: Path, video_info: VideoStreamInfo | None) -> str:
    """Generate deterministic, sanitized media ID."""
    stem = re.sub(r"[^a-zA-Z0-9_-]", "_", file_path.stem)
    if video_info:
        fps_int = int(round(video_info.fps))
        return f"{stem}_{video_info.height}p_{fps_int}fps"
    return stem


def probe_media_file(file_path: Path, repo_root: Path | None = None) -> MediaInfo:
    """Probe a media file using ffprobe and extract structured metadata."""
    if not file_path.exists():
        raise MediaProbeError(f"媒体文件不存在: {file_path}")

    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        raise MediaProbeError("系统未找到 ffprobe 工具，请检查 PATH 设置")

    cmd = [
        ffprobe_bin,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
        data = json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        raise MediaProbeError("ffprobe 读取媒体元数据超时 (超过 15 秒)")
    except subprocess.CalledProcessError as exc:
        raise MediaProbeError(f"ffprobe 解析媒体文件失败: {exc.stderr.strip() or exc.stdout.strip()}")
    except Exception as exc:
        raise MediaProbeError(f"读取媒体文件发生异常: {exc}")

    streams = data.get("streams", [])
    format_info = data.get("format", {})

    if not streams:
        raise MediaProbeError(f"文件未包含任何有效音频或视频流: {file_path}")

    # Parse video stream
    video_info: VideoStreamInfo | None = None
    audio_info: AudioStreamInfo | None = None
    subtitles: list[SubtitleStreamInfo] = []

    for s in streams:
        stype = s.get("codec_type")
        if stype == "video" and video_info is None:
            # Parse fps
            fps_str = s.get("r_frame_rate", "25/1")
            try:
                num, den = fps_str.split("/")
                fps_val = float(num) / float(den) if float(den) > 0 else 25.0
            except Exception:
                fps_val = 25.0

            width = int(s.get("width", 0))
            height = int(s.get("height", 0))
            dar = s.get("display_aspect_ratio")
            if not dar and width and height:
                dar = f"{width}:{height}"

            br = s.get("bit_rate")
            bitrate = int(br) if br and br.isdigit() else None

            nf = s.get("nb_frames")
            total_frames = int(nf) if nf and nf.isdigit() else None

            video_info = VideoStreamInfo(
                codec=s.get("codec_name", "unknown"),
                width=width,
                height=height,
                fps=round(fps_val, 2),
                aspect_ratio=dar or "16:9",
                pix_fmt=s.get("pix_fmt", "unknown"),
                bit_rate=bitrate,
                total_frames=total_frames,
            )
        elif stype == "audio" and audio_info is None:
            sr = s.get("sample_rate", "0")
            sample_rate = int(sr) if sr.isdigit() else 0
            channels = int(s.get("channels", 0))
            br = s.get("bit_rate")
            bitrate = int(br) if br and br.isdigit() else None

            audio_info = AudioStreamInfo(
                codec=s.get("codec_name", "unknown"),
                sample_rate=sample_rate,
                channels=channels,
                channel_layout=s.get("channel_layout", "stereo"),
                bit_rate=bitrate,
            )
        elif stype == "subtitle":
            tags = s.get("tags", {})
            subtitles.append(
                SubtitleStreamInfo(
                    codec=s.get("codec_name", "unknown"),
                    language=tags.get("language"),
                    title=tags.get("title"),
                )
            )

    # Determine duration
    duration_str = format_info.get("duration") or (streams[0].get("duration") if streams else "0")
    try:
        duration_sec = float(duration_str)
    except Exception:
        duration_sec = 0.0

    fps = video_info.fps if video_info else 25.0
    duration_timecode = seconds_to_timecode(duration_sec, fps=fps, format_type="broadcast")

    # File size
    size_bytes = file_path.stat().st_size
    size_mb = round(size_bytes / (1024 * 1024), 2)

    # Subtitle summary
    if subtitles:
        subtitle_summary = f"检测到 {len(subtitles)} 个软字幕轨 (" + ", ".join(s.codec for s in subtitles) + ")"
    else:
        subtitle_summary = "未检测到软字幕轨；画面内字幕需查看视频确认"

    rel_path = str(file_path.relative_to(repo_root)) if repo_root and file_path.is_relative_to(repo_root) else file_path.name
    media_id = generate_stable_media_id(file_path, video_info)

    return MediaInfo(
        media_id=media_id,
        filename=file_path.name,
        relative_path=rel_path,
        file_size_bytes=size_bytes,
        file_size_mb=size_mb,
        duration_sec=round(duration_sec, 3),
        duration_timecode=duration_timecode,
        format_name=format_info.get("format_name", "mp4"),
        video=video_info,
        audio=audio_info,
        subtitles=subtitles,
        subtitle_summary=subtitle_summary,
    )


def detect_scenes(
    video_path: Path,
    total_duration_sec: float,
    fps: float = 25.0,
    max_duration_sec: float | None = None,
    threshold: float = 0.35,
    min_scene_duration: float = 0.5,
    mode: str = "adaptive",
) -> list[SceneItem]:
    """
    Detect scene cutpoints using ffmpeg select filter and return a contiguous list of SceneItems.
    """
    if (mode not in ("adaptive", "fixed") or not math.isfinite(threshold)
            or not 0 < threshold <= 1 or not math.isfinite(fps) or fps <= 0
            or not math.isfinite(total_duration_sec) or total_duration_sec <= 0
            or not math.isfinite(min_scene_duration) or min_scene_duration <= 0):
        raise MediaProbeError("镜头检测参数无效")
    effective_duration = total_duration_sec
    if max_duration_sec is not None:
        if not math.isfinite(max_duration_sec) or max_duration_sec <= 0:
            raise MediaProbeError("最大分析时长必须为正数")
        effective_duration = min(max_duration_sec, total_duration_sec)
    try:
        rows = read_frame_scores(video_path, effective_duration)
        tolerance = 1 / fps + .003
        if (not rows or abs(rows[0][0]) > .003
                or abs(rows[-1][0] + 1/fps - effective_duration) > tolerance
                or any(not 0 < right[0]-left[0] <= 1.5/fps
                       for left, right in zip(rows, rows[1:]))):
            exc = ValueError("帧时间戳或分析范围覆盖不完整（需要恒定帧率素材）")
            exc.safe_code = 'incomplete_coverage'
            exc.safe_numbers = {'score_frame_count': len(rows),
                'first_score_sec': rows[0][0] if rows else 0,
                'last_score_sec': rows[-1][0] if rows else 0}
            raise exc
        filtered_cuts = select_cutpoints(rows, fps, effective_duration, threshold,
                                         mode, min_duration=min_scene_duration)
    except (ValueError, subprocess.SubprocessError, OSError) as exc:
        raise MediaProbeError("ffmpeg 场景切分失败（分数读取或执行异常）") from exc

    # Build scene items
    scenes: list[SceneItem] = []
    boundaries = [0.0] + filtered_cuts + [effective_duration]

    for idx in range(len(boundaries) - 1):
        s_start = boundaries[idx]
        s_end = boundaries[idx + 1]
        dur = s_end - s_start

        if dur <= 0:
            continue

        start_frame = int(round(s_start * fps))
        end_frame = max(start_frame + 1, int(round(s_end * fps)))

        scenes.append(
            SceneItem(
                index=idx + 1,
                start_sec=round(s_start, 3),
                start_timecode=seconds_to_timecode(s_start, fps=fps, format_type="broadcast"),
                end_sec=round(s_end, 3),
                end_timecode=seconds_to_timecode(s_end, fps=fps, format_type="broadcast"),
                duration_sec=round(dur, 3),
                start_frame=start_frame,
                end_frame=end_frame,
            )
        )

    return scenes


def scene_statistics(scenes: list[SceneItem]) -> dict[str, Any]:
    """Use the complete list for every displayed/exported statistic."""
    durations = [s.duration_sec for s in scenes]
    return {
        "total_scenes": len(scenes),
        "total_duration_sec": round(sum(durations), 3),
        "average_duration_sec": round(sum(durations) / len(scenes), 2) if scenes else 0,
        "min_duration_sec": round(min(durations), 2) if scenes else 0,
        "max_duration_sec": round(max(durations), 2) if scenes else 0,
        "longest_scene_index": max(scenes, key=lambda s: s.duration_sec).index if scenes else None,
    }


def generate_summary_html(
    media: MediaInfo,
    scenes: list[SceneItem],
    output_html: Path,
    previews: dict[int, list[dict[str, Any]]] | None = None,
    source_note: str = "",
) -> None:
    """Generate pure, clean, professional verification HTML report."""
    output_html.parent.mkdir(parents=True, exist_ok=True)

    # Calculate scene stats
    stats = scene_statistics(scenes)
    total_scenes = stats["total_scenes"]
    avg_scene_dur = stats["average_duration_sec"]
    min_scene_dur = stats["min_duration_sec"]
    max_scene_dur = stats["max_duration_sec"]

    scene_rows = []
    for sc in scenes:
        images = (previews or {}).get(sc.index, [])
        preview_html = "".join(
            f'<a href="{escape(str(p["file"]), quote=True)}" target="_blank">'
            f'<img loading="lazy" width="160" src="{escape(str(p["file"]), quote=True)}" '
            f'alt="区间 {sc.index}，{p["time_sec"]:.3f} 秒"></a>'
            f'<small>{p["time_sec"]:.3f}s</small>' for p in images
        ) or "待生成预览"
        if len(images) > 1:
            preview_html = f'<details><summary>重点核对：{len(images)} 处画面</summary>{preview_html}</details>'
        scene_rows.append(
            f"""<tr>
                <td>#{sc.index:03d}</td>
                <td><code>{sc.start_timecode}</code></td>
                <td><code>{sc.end_timecode}</code></td>
                <td>{sc.duration_sec:.2f}s</td>
                <td>{sc.start_frame} ~ {sc.end_frame}</td>
                <td>{preview_html}</td>
            </tr>"""
        )

    # Media metadata can contain attacker-controlled text (for example a filename).
    # Escape every metadata string before interpolating it into this HTML document.
    filename = escape(media.filename, quote=True)
    media_id = escape(media.media_id, quote=True)
    relative_path = escape(media.relative_path, quote=True)
    v_codec = escape(media.video.codec, quote=True) if media.video else "N/A"
    v_res = escape(
        f"{media.video.width}x{media.video.height} ({media.video.aspect_ratio})", quote=True
    ) if media.video else "N/A"
    v_fps = escape(f"{media.video.fps} fps", quote=True) if media.video else "N/A"
    a_codec = escape(
        f"{media.audio.codec} ({media.audio.channel_layout}, {media.audio.sample_rate}Hz)",
        quote=True,
    ) if media.audio else "N/A"
    subtitle_summary = escape(media.subtitle_summary, quote=True)

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>阶段 1 素材导入与时间码清单 · 核验报告</title>
    <style>
        :root {{
            --bg: #0f1117;
            --surface: #1a1d27;
            --surface-hover: #222634;
            --border: #2a2f42;
            --text-primary: #e6edf3;
            --text-secondary: #8b949e;
            --accent: #58a6ff;
            --success: #3fb950;
            --warning: #d29922;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            padding: 40px 20px;
        }}
        .container {{
            max-width: 1080px;
            margin: 0 auto;
        }}
        header {{
            margin-bottom: 32px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 20px;
        }}
        h1 {{ font-size: 28px; font-weight: 600; margin-bottom: 8px; }}
        .badge {{
            display: inline-block;
            background: rgba(63, 185, 80, 0.15);
            color: var(--success);
            border: 1px solid var(--success);
            padding: 4px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 600;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }}
        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 20px;
        }}
        .card-label {{
            font-size: 13px;
            color: var(--text-secondary);
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .card-value {{
            font-size: 20px;
            font-weight: 600;
            color: var(--text-primary);
        }}
        .card-sub {{
            font-size: 12px;
            color: var(--text-secondary);
            margin-top: 4px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
            margin-top: 16px;
        }}
        th, td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid var(--border);
            font-size: 14px;
        }}
        th {{
            background: rgba(255, 255, 255, 0.03);
            color: var(--text-secondary);
            font-weight: 600;
        }}
        tr:hover td {{
            background: var(--surface-hover);
        }}
        code {{
            font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
            color: var(--accent);
            background: rgba(88, 166, 255, 0.1);
            padding: 2px 6px;
            border-radius: 4px;
        }}
        footer {{
            margin-top: 40px;
            text-align: center;
            font-size: 13px;
            color: var(--text-secondary);
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h1>阶段 1 素材导入与时间码清单</h1>
                <span class="badge">清单已生成 · 画面待核对</span>
            </div>
            <p style="color: var(--text-secondary); margin-top: 6px;">
                素材: <strong>{filename}</strong> (ID: <code>{media_id}</code>)
            </p>
        </header>

        <section class="grid">
            <div class="card">
                <div class="card-label">时长与总帧数</div>
                <div class="card-value">{media.duration_timecode}</div>
                <div class="card-sub">{media.duration_sec:.2f} 秒 · {media.video.total_frames if media.video else 'N/A'} 帧</div>
            </div>
            <div class="card">
                <div class="card-label">画质与分辨率</div>
                <div class="card-value">{v_res}</div>
                <div class="card-sub">{v_codec} 编码 · {v_fps}</div>
            </div>
            <div class="card">
                <div class="card-label">音频与采样率</div>
                <div class="card-value">{a_codec}</div>
                <div class="card-sub">双声道立体声</div>
            </div>
            <div class="card">
                <div class="card-label">字幕状态</div>
                <div class="card-value">{len(media.subtitles)} 轨软字幕</div>
                <div class="card-sub">{subtitle_summary}</div>
            </div>
        </section>

        <section class="grid">
            <div class="card">
                <div class="card-label">镜头总数</div>
                <div class="card-value">{total_scenes} 个镜头</div>
                <div class="card-sub">已切分时间码区间</div>
            </div>
            <div class="card">
                <div class="card-label">平均镜头时长</div>
                <div class="card-value">{avg_scene_dur}s</div>
                <div class="card-sub">最短 {min_scene_dur}s · 最长 {max_scene_dur}s</div>
            </div>
            <div class="card">
                <div class="card-label">文件大小</div>
                <div class="card-value">{media.file_size_mb} MB</div>
                <div class="card-sub">{media.file_size_bytes:,} 字节</div>
            </div>
            <div class="card">
                <div class="card-label">素材相对路径</div>
                <div class="card-value" style="font-size: 15px; word-break: break-all;"><code>{relative_path}</code></div>
                <div class="card-sub">本地安全隔离</div>
            </div>
        </section>

        <h2 style="font-size: 20px; font-weight: 600; margin-top: 32px; margin-bottom: 8px;">候选区间清单（完整 {total_scenes} 项）</h2>
        <p>根据画面变化生成候选区间，时长不固定；长区间可能是长镜头，也可能有漏切，需看画面确认。帧区间按起点包含、终点不包含计。</p>
        <p style="color: var(--text-secondary); font-size: 13px; margin-bottom: 12px;">{escape(source_note, quote=True)}</p>

        <table>
            <thead>
                <tr>
                    <th style="width: 80px;">序号</th>
                    <th>起入点时间码</th>
                    <th>出点时间码</th>
                    <th>镜头时长</th>
                    <th>对应帧数区间</th>
                    <th>本机画面预览（点击放大）</th>
                </tr>
            </thead>
            <tbody>
                {''.join(scene_rows)}
            </tbody>
        </table>

        <footer>
            数智博主视频镜头检索技术验证 · 阶段 1 交付物
        </footer>
    </div>
</body>
</html>
"""
    output_html.write_text(html_content, encoding="utf-8")


def run_stage1_media_import(
    input_dir: Path,
    output_dir: Path,
    target_pattern: str | None = "qianfu",
    max_duration_sec: float | None = 1800.0,  # 30 mins
    scene_threshold: float = 0.35,
    repo_root: Path | None = None,
    scene_mode: str = "adaptive",
) -> StageResult:
    """
    Execute Stage 1 media import pipeline:
    1. Scan input_dir for valid video media
    2. Probe video metadata with ffprobe
    3. Run scene detection with ffmpeg
    4. Generate sanitized JSON manifests and summary HTML
    """
    root = (repo_root or Path.cwd()).resolve()
    input_p = (input_dir if input_dir.is_absolute() else (root / input_dir)).resolve()
    output_p = (output_dir if output_dir.is_absolute() else (root / output_dir)).resolve()
    output_p.mkdir(parents=True, exist_ok=True)

    # 1. Scan for candidates
    supported_exts = {".mp4", ".mov", ".mkv", ".flv", ".avi"}
    candidates: list[Path] = []
    if input_p.exists() and input_p.is_dir():
        for f in input_p.iterdir():
            if f.is_file() and f.suffix.lower() in supported_exts:
                candidates.append(f)

    def safe_rel(p: Path) -> str:
        try:
            return str(p.relative_to(root))
        except ValueError:
            return str(p)

    if not candidates:
        blocked_info = {
            "status": "blocked",
            "reason": f"未在素材目录 '{input_p}' 中找到任何有效视频文件 (.mp4, .mov 等)",
            "scanned_path": str(input_p),
            "recommendation": "请将测试视频素材放置于 data/input/ 目录下，再重新执行阶段 1 导入。",
        }
        blocked_file = output_p / "import_blocked.json"
        blocked_file.write_text(json.dumps(blocked_info, ensure_ascii=False, indent=2), encoding="utf-8")
        return StageResult(
            stage="stage1",
            status="blocked",
            artifacts=[safe_rel(blocked_file)],
            errors=[blocked_info["reason"]],
            details=blocked_info,
        )

    # Select target video
    chosen_video: Path | None = None
    if target_pattern:
        for c in candidates:
            if target_pattern.lower() in c.name.lower():
                chosen_video = c
                break

    if not chosen_video:
        chosen_video = candidates[0]

    # 2. Probe media
    try:
        media_info = probe_media_file(chosen_video, repo_root=root)
    except MediaProbeError as exc:
        err_msg = f"素材探测解析失败: {exc}"
        return StageResult(
            stage="stage1",
            status="failed",
            artifacts=[],
            errors=[err_msg],
            details={"video_path": str(chosen_video)},
        )

    # 3. Detect scenes
    fps = media_info.video.fps if media_info.video else 25.0
    try:
        scenes = detect_scenes(
            video_path=chosen_video,
            total_duration_sec=media_info.duration_sec,
            fps=fps,
            max_duration_sec=max_duration_sec,
            threshold=scene_threshold,
            mode=scene_mode,
        )
    except MediaProbeError as exc:
        err_msg = f"镜头场景切分失败: {exc}"
        return StageResult(
            stage="stage1",
            status="failed",
            artifacts=[],
            errors=[err_msg],
            details={"video_path": str(chosen_video)},
        )

    # 4. Generate manifests and HTML report
    manifest_path = output_p / "media_manifest.json"
    manifest_data = {
        "version": 1,
        "stage": "stage1_media_import",
        "media": media_info.to_dict(),
        "scene_count": len(scenes),
        "scene_manifest_file": f"scenes_{media_info.media_id}.json",
    }
    manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")

    scenes_path = output_p / f"scenes_{media_info.media_id}.json"
    scenes_data = {
        "media_id": media_info.media_id,
        "fps": fps,
        "total_scenes": len(scenes),
        "analyzed_duration_sec": max_duration_sec if (max_duration_sec and max_duration_sec < media_info.duration_sec) else media_info.duration_sec,
        "detector": {"version": 4, "mode": scene_mode, "threshold": scene_threshold,
                     "adaptive_floor": .04, "adaptive_ratio": 3.0, "window_sec": 1.0,
                     "fade_trough_max_luma": 20, "fade_recovery_luma": 12,
                     "low_score_delta_gate_below": .06, "low_score_delta_ratio": 3.0,
                     "min_scene_duration": .5},
        "scenes": [s.to_dict() for s in scenes],
    }
    scenes_path.write_text(json.dumps(scenes_data, ensure_ascii=False, indent=2), encoding="utf-8")

    html_path = output_p / "summary.html"
    generate_summary_html(media_info, scenes, html_path)

    artifacts = [
        safe_rel(manifest_path),
        safe_rel(scenes_path),
        safe_rel(html_path),
    ]

    return StageResult(
        stage="stage1",
        status="passed",
        artifacts=artifacts,
        details={
            "media_id": media_info.media_id,
            "filename": media_info.filename,
            "duration_sec": media_info.duration_sec,
            "duration_timecode": media_info.duration_timecode,
            "total_scenes": len(scenes),
            "video_codec": media_info.video.codec if media_info.video else None,
            "resolution": f"{media_info.video.width}x{media_info.video.height}" if media_info.video else None,
            "fps": media_info.video.fps if media_info.video else None,
            "audio_codec": media_info.audio.codec if media_info.audio else None,
            "subtitles": media_info.subtitle_summary,
        },
    )
