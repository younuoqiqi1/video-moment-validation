"""Fixed Mac jobs and safe receipts; never interpret task text as shell code."""
import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = 'younuoqiqi1/video-moment-validation'
STAGE1_SHA = '39c48d9a87167decb3ab53d5da5d79d6e3bd9c05'
LOCAL_CONFIG = Path.home() / '.local/share/vmv-actions-runner/vmv-local.json'


def validate_task(task):
    keys = {'version', 'task_id', 'mode', 'nonce', 'pr_number', 'code_sha'}
    if not isinstance(task, dict) or set(task) != keys or type(task['version']) is not int or task['version'] != 1:
        raise ValueError('invalid_task')
    if not isinstance(task['task_id'], str) or not re.fullmatch(r'[a-z0-9-]{1,80}', task['task_id']):
        raise ValueError('invalid_task_id')
    if not isinstance(task['nonce'], str) or not re.fullmatch(r'[a-f0-9]{64}', task['nonce']):
        raise ValueError('invalid_nonce')
    if type(task['pr_number']) is not int:
        raise ValueError('invalid_pr')
    if task['mode'] == 'probe' and task['pr_number'] == 3 and task['code_sha'] == '':
        return task
    if task['mode'] in ('stage1-preview', 'stage1-numeric') and task['pr_number'] == 5 and task['code_sha'] == STAGE1_SHA:
        return task
    raise ValueError('unauthorized_task')


def gh_json(args):
    # Reuse this Mac user's existing gh login. No workflow token or credentials in output.
    env = dict(os.environ)
    env.pop('GH_TOKEN', None)
    env.pop('GITHUB_TOKEN', None)
    process = subprocess.run(['gh', *args], capture_output=True, text=True, env=env, timeout=60)
    if process.returncode:
        raise RuntimeError('github_request_failed')
    return json.loads(process.stdout)


def post_receipt(task, result, phase):
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    revision = os.environ.get('GITHUB_SHA', '')
    if not run_id.isdigit() or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('missing_actions_context')
    if os.environ.get('GITHUB_REPOSITORY') != REPO:
        raise ValueError('wrong_repository')
    run_url = f'https://github.com/{REPO}/actions/runs/{run_id}'
    marker = f'<!-- vmv-actions:{run_id}:{os.environ.get("GITHUB_RUN_ATTEMPT", "1")}:{phase} -->'
    comments = gh_json(['api', f'repos/{REPO}/issues/{task["pr_number"]}/comments', '--paginate', '--slurp'])
    if any(marker in comment.get('body', '') for page in comments for comment in page):
        return
    text = {'started': 'Mac 已开始执行', 'completed': 'Mac 执行完成',
            'failed': 'Mac 执行失败', 'blocked': 'Mac 执行阻塞'}[phase]
    proof = {key: result[key] for key in ('task_id', 'mode', 'nonce', 'platform',
        'workflow_sha', 'code_sha', 'execution_status', 'started_at') if key in result}
    for key in ('completed_at', 'probe_sha256', 'statistics', 'preview_image_count',
                'numeric_validation', 'human_visual_review', 'error_code',
                'adjacent_scenes', 'source_scenes_sha256', 'source_media_manifest_sha256',
                'fps', 'analyzed_duration_sec'):
        if key in result:
            proof[key] = result[key]
    body = f'{marker}\nAGY 协同回执：{text}（GitHub 官方执行器）\n\n'
    body += f'任务：`{task["task_id"]}`；运行证据：[GitHub Actions]({run_url})。\n\n'
    body += '```json\n' + json.dumps(proof, ensure_ascii=False, indent=2) + '\n```\n'
    body += '\n仅表示本次任务执行状态；不表示画面已人工验收，不合并 PR，不进入阶段 2。'
    gh_json(['api', '--method', 'POST', f'repos/{REPO}/issues/{task["pr_number"]}/comments', '-f', f'body={body}'])


def preview(config_path, output):
    config = json.loads(config_path.read_text(encoding='utf-8'))
    root = Path(config['project_root']).resolve()
    python = Path(config['python']).resolve()
    target = Path('target').resolve()
    if subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip() != STAGE1_SHA:
        raise ValueError('wrong_code_revision')
    manifest = root / 'outputs/stage1/media_manifest.json'
    name = json.loads(manifest.read_text(encoding='utf-8'))['scene_manifest_file']
    if not isinstance(name, str) or Path(name).name != name or not name.endswith('.json'):
        raise ValueError('invalid_scene_manifest')
    video = root / 'data/input/qianfu_ep18.mp4'
    for item in (python, manifest, manifest.parent / name, video):
        if not item.is_file():
            raise ValueError('missing_local_input')
    env = dict(os.environ, PYTHONPATH=str(target / 'src'))
    env.pop('GH_TOKEN', None)
    env.pop('GITHUB_TOKEN', None)
    command = [str(python), '-m', 'vmv', 'preview', '--media-manifest', str(manifest),
        '--scenes', str(manifest.parent / name), '--video', str(video), '--output', str(output)]
    process = subprocess.run(command, cwd=target, env=env, capture_output=True, timeout=2700)
    if process.returncode:
        raise RuntimeError('stage1_execution_failed')
    verification = json.loads((output / 'verification.json').read_text(encoding='utf-8'))
    # Upload only selected numbers, never frame images, filenames, source paths or raw logs.
    stats = verification['statistics']
    allowed = ('total_scenes', 'total_duration_sec', 'average_duration_sec', 'min_duration_sec',
               'max_duration_sec', 'longest_scene_index')
    numeric = {key: stats[key] for key in allowed}
    if any(type(value) not in (int, float) for value in numeric.values()):
        raise ValueError('invalid_statistics')
    return {'statistics': numeric, 'preview_image_count': int(verification['preview_image_count']),
            'numeric_validation': 'passed', 'human_visual_review': 'not_verified'}


def numeric_check(config_path):
    """Read the entire original JSON without opening, hashing or decoding video."""
    try:
        config = json.loads(config_path.read_text(encoding='utf-8'))
        target = Path('target').resolve()
        if subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'],
                                   text=True, timeout=10).strip() != STAGE1_SHA:
            raise ValueError('wrong_code_revision')
        manifest = Path(config['project_root']).resolve() / 'outputs/stage1/media_manifest.json'
        manifest_bytes = manifest.read_bytes()
        data = json.loads(manifest_bytes)
        name = data['scene_manifest_file']
        if not isinstance(name, str) or Path(name).name != name or not name.endswith('.json'):
            raise ValueError('invalid_scene_manifest')
        scenes_bytes = (manifest.parent / name).read_bytes()
        source = json.loads(scenes_bytes)
        scenes = source['scenes']
        fps = source['fps']
        analyzed = source['analyzed_duration_sec']
        if (type(fps) not in (int, float) or not math.isfinite(fps) or fps <= 0
                or type(analyzed) not in (int, float) or not math.isfinite(analyzed) or analyzed <= 0
                or not scenes or source['total_scenes'] != len(scenes)
                or data['scene_count'] != len(scenes)
                or source['media_id'] != data['media']['media_id']
                or abs(data['media']['video']['fps'] - fps) > .001
                or analyzed > data['media']['duration_sec'] + 1 / fps + .003):
            raise ValueError('invalid_source')
        fields = ('index', 'start_sec', 'end_sec', 'duration_sec', 'start_frame',
                  'end_frame', 'start_timecode', 'end_timecode')
        previous_sec, previous_frame = 0, 0
        safe_rows = []
        for index, row in enumerate(scenes, 1):
            for key in ('start_sec', 'end_sec', 'duration_sec'):
                if type(row[key]) not in (int, float) or not math.isfinite(row[key]):
                    raise ValueError('invalid_number')
            if (type(row['index']) is not int or row['index'] != index
                    or type(row['start_frame']) is not int or type(row['end_frame']) is not int
                    or row['end_sec'] <= row['start_sec'] or row['end_frame'] <= row['start_frame']
                    or abs(row['start_sec'] - previous_sec) > .003
                    or row['start_frame'] != previous_frame
                    or abs(row['duration_sec'] - (row['end_sec'] - row['start_sec'])) > .003):
                raise ValueError('invalid_interval')
            for prefix in ('start', 'end'):
                tc = row[prefix + '_timecode']
                if not isinstance(tc, str) or not re.fullmatch(r'\d{2,}:\d{2}:\d{2}:\d{2}', tc):
                    raise ValueError('invalid_timecode')
                h, m, s, f = map(int, tc.split(':'))
                if m >= 60 or s >= 60 or f >= math.ceil(fps):
                    raise ValueError('invalid_timecode')
                seconds = row[prefix + '_sec']
                if (abs(seconds * fps - row[prefix + '_frame']) > 1.01
                        or abs(h*3600 + m*60 + s + f/fps - seconds) > 1/fps + .003):
                    raise ValueError('invalid_frame')
            previous_sec, previous_frame = row['end_sec'], row['end_frame']
            if 81 <= index <= 84:
                safe_rows.append({key: row[key] for key in fields})
        if abs(previous_sec - analyzed) > 1/fps + .003:
            raise ValueError('invalid_end')
        durations = [row['duration_sec'] for row in scenes]
        statistics = {'total_scenes': len(scenes), 'total_duration_sec': round(sum(durations), 3),
            'average_duration_sec': round(sum(durations)/len(scenes), 2),
            'min_duration_sec': round(min(durations), 2), 'max_duration_sec': round(max(durations), 2),
            'longest_scene_index': max(scenes, key=lambda row: row['duration_sec'])['index']}
        return {'statistics': statistics, 'adjacent_scenes': safe_rows, 'fps': fps,
            'analyzed_duration_sec': analyzed, 'source_scenes_sha256': hashlib.sha256(scenes_bytes).hexdigest(),
            'source_media_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'preview_image_count': 0, 'numeric_validation': 'passed', 'human_visual_review': 'not_verified'}
    except Exception:
        raise RuntimeError('stage1_numeric_failed') from None


def execute(task, output, config_path):
    validate_task(task)
    result = {'task_id': task['task_id'], 'mode': task['mode'], 'nonce': task['nonce'],
        'code_sha': task['code_sha'], 'workflow_sha': os.environ.get('GITHUB_SHA', ''),
        'run_id': os.environ.get('GITHUB_RUN_ID', ''), 'platform': platform.system(),
        'architecture': platform.machine(), 'started_at': datetime.now(timezone.utc).isoformat(),
        'execution_status': 'started', 'notification_status': 'sent'}
    if result['platform'] != 'Darwin':
        return dict(result, execution_status='blocked', notification_status='not_sent', error_code='not_macos')
    try:
        post_receipt(task, result, 'started')
    except Exception:
        result['notification_status'] = 'failed'
    try:
        output.mkdir(parents=True, exist_ok=True)
        if task['mode'] == 'probe':
            with tempfile.TemporaryDirectory(prefix='vmv-probe-') as folder:
                probe = Path(folder) / 'challenge.txt'
                probe.write_text(task['nonce'], encoding='ascii')
                result['probe_sha256'] = hashlib.sha256(probe.read_bytes()).hexdigest()
        elif task['mode'] == 'stage1-numeric':
            result.update(numeric_check(config_path or LOCAL_CONFIG))
        else:
            result.update(preview(config_path or LOCAL_CONFIG, output / 'local-preview'))
        result['execution_status'] = 'completed'
    except Exception:
        result.update(execution_status='failed', error_code='execution_failed')
    result['completed_at'] = datetime.now(timezone.utc).isoformat()
    try:
        post_receipt(task, result, result['execution_status'])
    except Exception:
        result['notification_status'] = 'failed'
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('data/work/actions-result'))
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    try:
        task = validate_task(json.loads(args.task.read_text(encoding='utf-8')))
        if args.validate_only:
            return 0
        result = execute(task, args.output, None)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('执行状态：' + result['execution_status'] + '；回传状态：' + result['notification_status'])
        return 0 if result['execution_status'] == 'completed' and result['notification_status'] == 'sent' else 1
    except Exception:
        print('任务阻塞：配置或输入无效；请查看任务和本机配置。')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
