"""Local-only stage 1 rerun; safe numbers do not imply visual acceptance."""
import argparse
import json
import math
import subprocess
from pathlib import Path

from vmv.media import detect_scenes, scene_statistics, generate_summary_html
from vmv.preview import file_hash, read_existing_manifests, run_stage1_preview


def _match(predictions, references, tolerance):
    available = sorted(predictions)
    matched = []
    missing = []
    for reference in sorted(references):
        candidate = next((p for p in available if abs(p-reference) <= tolerance), None)
        if candidate is None:
            missing.append(reference)
        else:
            matched.append(candidate)
            available.remove(candidate)
    return matched, missing


def compare_cutpoints(before, after, references, tolerance_frames=1):
    for values in (before, after, references):
        if any(type(f) is not int or f < 0 for f in values) or len(set(values)) != len(values):
            raise ValueError('切点帧号无效或重复')
    if type(tolerance_frames) is not int or tolerance_frames < 0:
        raise ValueError('切点容差无效')
    matched_before, _ = _match(before, references, tolerance_frames)
    matched_after, missing = _match(after, references, tolerance_frames)
    added = sorted(set(after)-set(before))
    return {'reference_count': len(references),
        'reference_matched_before': len(matched_before),
        'reference_matched_after': len(matched_after),
        'reference_unmatched_frames': missing,
        'added_candidate_frames': added,
        'removed_candidate_frames': sorted(set(before)-set(after)),
        'unlabelled_added_frames': sorted(set(added)-set(matched_after)),
        'false_cut_rate': None, 'human_visual_review': 'not_verified',
        'reference_status': 'AGY_reported_not_independently_verified',
        'tolerance_frames': tolerance_frames}


def rerun(video, manifest, source_scenes, reference_path, output, *, progress=lambda stage: None):
    """Preserve original files and bind all comparisons to their content hashes."""
    progress("read_reference")
    reference = json.loads(reference_path.read_text())
    progress("read_manifests")
    media, original, fps, analyzed = read_existing_manifests(manifest, source_scenes)
    progress("verify_source_hashes")
    hashes = {'source_scenes_sha256': file_hash(source_scenes),
              'source_media_manifest_sha256': file_hash(manifest),
              'source_video_sha256': file_hash(video)}
    if any(hashes[k] != reference[k] for k in hashes):
        raise ValueError('原始输入与已指定证据不匹配')
    progress("verify_analysis_range")
    if fps != reference['fps'] or analyzed != reference['analyzed_duration_sec']:
        raise ValueError('分析范围不匹配')
    refs = reference['reference_frames']
    compare_cutpoints([], [], refs)
    if any(f <= 0 or f >= round(analyzed*fps) for f in refs):
        raise ValueError('参考切点超出分析范围')
    # A fresh directory is mandatory. Never replace original reports or previews.
    progress("create_candidate_directory")
    output.mkdir(parents=True, exist_ok=False)
    progress("fixed_detection")
    before = detect_scenes(video, media.duration_sec, fps, analyzed, mode='fixed')
    progress("adaptive_detection")
    after = detect_scenes(video, media.duration_sec, fps, analyzed, mode='adaptive')
    before_frames = [s.start_frame for s in before[1:]]
    after_frames = [s.start_frame for s in after[1:]]
    original_frames = [s.start_frame for s in original[1:]]
    result = {**hashes, **compare_cutpoints(before_frames, after_frames, refs),
        'baseline_reproduced': original_frames == before_frames,
        'before_statistics': scene_statistics(before),
        'after_statistics': scene_statistics(after),
        'fps': fps, 'analyzed_duration_sec': analyzed,
        'numeric_validation': 'pending', 'preview_image_count': 0}
    # Every candidate remains available locally for review.
    progress("write_candidate_manifests")
    data = json.loads(manifest.read_text())
    data['scene_count'] = len(after)
    (output / 'media_manifest.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
    candidate = output / source_scenes.name
    candidate.write_text(json.dumps({'media_id': media.media_id, 'fps': fps,
        'analyzed_duration_sec': analyzed, 'total_scenes': len(after),
        'detector': {'version': 2, 'mode': 'adaptive', 'threshold': .35,
            'adaptive_floor': .04, 'adaptive_ratio': 3, 'window_sec': 1,
            'min_scene_duration': .5},
        'scenes': [s.to_dict() for s in after]}, ensure_ascii=False, indent=2))
    generate_summary_html(media, after, output / 'summary.html')
    progress("candidate_preview")
    preview = run_stage1_preview(output / 'media_manifest.json', candidate, video, output / 'preview')
    if preview.status != 'passed':
        raise ValueError('候选清单数值核对或本机预览失败')
    result.update(numeric_validation='passed',
                  preview_image_count=preview.details['preview_image_count'])
    progress("verify_source_unchanged")
    if any(file_hash(path) != hashes[key] for path, key in
           ((manifest, 'source_media_manifest_sha256'), (source_scenes, 'source_scenes_sha256'),
            (video, 'source_video_sha256'))):
        raise ValueError('运行期间原始输入发生变化')
    progress("comparison_complete")
    (output / 'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def failure_diagnostic(exc):
    cause = exc.__cause__ or exc
    codes = {'incomplete_coverage'}
    if getattr(cause, 'safe_code', None) in codes:
        result = {'error_code': cause.safe_code}
        for key, value in getattr(cause, 'safe_numbers', {}).items():
            if key in {'score_frame_count', 'first_score_sec', 'last_score_sec'} and type(value) in (int, float) and math.isfinite(value):
                result[key] = value
        return result
    if isinstance(cause, subprocess.CalledProcessError):
        return {'error_code': 'ffmpeg_process_failed'}
    if isinstance(cause, subprocess.TimeoutExpired):
        return {'error_code': 'ffmpeg_timeout'}
    known = {'未找到 ffmpeg': 'ffmpeg_missing',
        '帧变化分数缺失或无效': 'invalid_frame_scores',
        '帧变化分数不连续': 'noncontiguous_frame_scores',
        '未读取到帧变化分数': 'empty_frame_scores'}
    if isinstance(cause, ValueError) and str(cause) in known:
        return {'error_code': known[str(cause)]}
    return {'error_code': ('missing_input' if isinstance(exc, FileNotFoundError) else
        'output_exists' if isinstance(exc, FileExistsError) else
        'invalid_data' if isinstance(exc, ValueError) else 'execution_error')}


def main():
    parser = argparse.ArgumentParser(description='阶段 1 漏切修正本机对照')
    for name in ('video', 'manifest', 'scenes', 'reference', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    stage = "read_reference"
    def progress(name):
        nonlocal stage
        stage = name
        print("checkpoint:" + name, flush=True)
    try:
        result = rerun(args.video, args.manifest, args.scenes, args.reference, args.output, progress=progress)
    except Exception as exc:
        # Fixed codes only: exception messages may contain source paths/logs.
        print(json.dumps({'execution_status': 'failed', 'failure_stage': stage,
                          **failure_diagnostic(exc)}), flush=True)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
