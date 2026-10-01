"""Stage 1 inspection of an existing manifest; never reruns scene detection."""

import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

from vmv.media import (
    AudioStreamInfo, MediaInfo, MediaProbeError, SceneItem, SubtitleStreamInfo,
    VideoStreamInfo, generate_summary_html, probe_media_file, scene_statistics,
    timecode_to_seconds,
)
from vmv.stages import StageResult


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_existing_manifests(manifest: Path, scenes_path: Path):
    data = json.loads(manifest.read_text(encoding="utf-8"))
    source = json.loads(scenes_path.read_text(encoding="utf-8"))
    raw = dict(data["media"])
    raw["video"] = VideoStreamInfo(**raw["video"]) if raw.get("video") else None
    raw["audio"] = AudioStreamInfo(**raw["audio"]) if raw.get("audio") else None
    raw["subtitles"] = [SubtitleStreamInfo(**s) for s in raw.get("subtitles", [])]
    media = MediaInfo(**raw)
    scenes = [SceneItem(**s) for s in source["scenes"]]
    fps = float(source["fps"])
    analyzed = float(source["analyzed_duration_sec"])
    if not math.isfinite(fps) or fps <= 0 or not media.video:
        raise ValueError("素材缺少有效视频帧率")
    if not math.isfinite(analyzed) or analyzed <= 0 or not scenes:
        raise ValueError("分析时长或区间清单无效")
    if source["media_id"] != media.media_id or data["scene_manifest_file"] != scenes_path.name:
        raise ValueError("素材清单与区间 JSON 的来源不一致")
    if source["total_scenes"] != len(scenes) or data["scene_count"] != len(scenes):
        raise ValueError("清单声明的总条数与实际完整数据不一致")
    tolerance = 1 / fps + 0.003
    if abs(media.video.fps - fps) > 0.001 or analyzed > media.duration_sec + tolerance:
        raise ValueError("分析帧率或时长与素材清单不一致")
    previous_end = 0.0
    previous_frame = 0
    for index, scene in enumerate(scenes, 1):
        numbers = (scene.start_sec, scene.end_sec, scene.duration_sec)
        if not all(math.isfinite(float(n)) for n in numbers):
            raise ValueError(f"第 {index} 条包含无效秒数")
        if scene.index != index or scene.end_sec <= scene.start_sec:
            raise ValueError(f"第 {index} 条序号或时间区间无效")
        if abs(scene.start_sec - previous_end) > 0.003 or scene.start_frame != previous_frame:
            raise ValueError(f"第 {index} 条与前一区间不连续")
        if abs(scene.duration_sec - (scene.end_sec - scene.start_sec)) > 0.003:
            raise ValueError(f"第 {index} 条时长与起止秒数不一致")
        for seconds, frame, timecode in (
            (scene.start_sec, scene.start_frame, scene.start_timecode),
            (scene.end_sec, scene.end_frame, scene.end_timecode),
        ):
            if abs(seconds * fps - frame) > 1.01 or abs(timecode_to_seconds(timecode, fps) - seconds) > tolerance:
                raise ValueError(f"第 {index} 条帧区间或时间码不一致")
        if scene.end_frame <= scene.start_frame:
            raise ValueError(f"第 {index} 条帧区间无效")
        previous_end, previous_frame = scene.end_sec, scene.end_frame
    if abs(previous_end - analyzed) > tolerance:
        raise ValueError("完整清单末尾与声明的分析时长不一致")
    return media, scenes, fps, analyzed


def run_stage1_preview(manifest: Path, scenes_path: Path, video: Path, output: Path) -> StageResult:
    """Validate all intervals, then extract local JPEGs for visual review."""
    try:
        media, scenes, fps, analyzed = read_existing_manifests(manifest, scenes_path)
        actual = probe_media_file(video)
        if (actual.media_id != media.media_id or actual.file_size_bytes != media.file_size_bytes
                or abs(actual.duration_sec - media.duration_sec) > 1 / fps + 0.003
                or not actual.video or abs(actual.video.fps - fps) > 0.001):
            raise ValueError("指定视频与现有素材清单不匹配，未生成预览")
        # The old manifest may have guessed hard subtitles from absence of a track.
        media.subtitle_summary = actual.subtitle_summary
        stats = scene_statistics(scenes)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise MediaProbeError("未找到 ffmpeg")
        frames = output / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        previews = {}
        for scene in scenes:
            detailed = scene.duration_sec >= 30 or scene.index == stats["longest_scene_index"]
            fractions = [0, 0.25, 0.5, 0.75, 1] if detailed else [0]
            last_frame_time = max(scene.start_sec, scene.end_sec - 1 / fps)
            times = sorted({round(scene.start_sec + (last_frame_time - scene.start_sec) * f, 3) for f in fractions})
            items = []
            for number, seconds in enumerate(times):
                filename = f"scene-{scene.index:04d}-{number}.jpg"
                destination = frames / filename
                try:
                    subprocess.run([
                        ffmpeg, "-nostdin", "-v", "error", "-y", "-ss", str(seconds),
                        "-i", str(video), "-frames:v", "1", "-vf", "scale=320:-2",
                        "-q:v", "4", str(destination),
                    ], check=True, capture_output=True, timeout=20)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                    raise MediaProbeError(f"第 {scene.index} 条在 {seconds} 秒的预览提取失败") from exc
                if not destination.is_file() or destination.stat().st_size == 0:
                    raise MediaProbeError(f"第 {scene.index} 条未生成有效预览图片")
                items.append({"file": f"frames/{filename}", "time_sec": seconds})
            previews[scene.index] = items
        verification = {
            "source_scenes_file": scenes_path.name,
            "source_scenes_sha256": file_hash(scenes_path),
            "source_media_manifest_sha256": file_hash(manifest),
            "source_video_sha256": file_hash(video),
            "fps": fps, "analyzed_duration_sec": analyzed,
            "statistics": stats,
            "numeric_validation": "passed",
            "human_visual_review": "not_verified",
            "preview_image_count": sum(len(images) for images in previews.values()),
            "sampled_frames": {str(k): v for k, v in previews.items()},
        }
        report = output / "verification.json"
        report.write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
        html = output / "summary.html"
        generate_summary_html(media, scenes, html, previews=previews,
                              source_note=f"来源：{scenes_path.name}；SHA256：{verification['source_scenes_sha256']}；完整数据数值核对通过，画面质量待抽查。")
        note = output / "verification.md"
        note.write_text(
            "# 阶段 1 完整清单核对\n\n"
            f"- 数据来源：{scenes_path.name}\n- 来源 SHA256：{verification['source_scenes_sha256']}\n"
            f"- 总条数：{len(scenes)}\n- 总区间时长：{stats['total_duration_sec']} 秒\n"
            f"- 平均/最短/最长：{stats['average_duration_sec']} / {stats['min_duration_sec']} / {stats['max_duration_sec']} 秒\n"
            f"- 最长区间序号：{stats['longest_scene_index']}\n"
            "- 时间码、帧区间、相邻连续性：数值核对通过\n"
            "- 真实视频画面抽查：尚未验证；请查看所有长区间的多点预览及前后相邻区间\n"
            "- 未重新运行镜头检测、未改阈值、未改写原 JSON 或原视频\n"
            "- 210.90 秒与历史报告 58.88 秒的差异：待对照本次统计和历史文件来源说明\n",
            encoding="utf-8",
        )
        return StageResult(stage="stage1_preview", status="passed",
                           artifacts=[str(html), str(report), str(note)], details=verification)
    except (OSError, ValueError, TypeError, KeyError, MediaProbeError) as exc:
        return StageResult(stage="stage1_preview", status="failed", artifacts=[],
                           errors=[f"完整清单预览失败：{exc}"], details={})
