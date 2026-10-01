"""Numeric checks must run without decoding video or exposing local metadata."""
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def local_inputs(tmp_path, monkeypatch):
    module = importlib.import_module('scripts.mac_actions')
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'revision.txt').write_text('pinned code fixture')
    subprocess.run(['git', 'init', '-q', str(target)], check=True)
    subprocess.run(['git', '-C', str(target), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(target), '-c', 'user.name=Test',
                    '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    revision = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
    monkeypatch.setattr(module, 'STAGE1_SHA', revision)
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'private-input'
    folder = root / 'outputs/stage1'
    folder.mkdir(parents=True)
    media = {'media_id': 'private-id', 'filename': 'SECRET_INPUT.mp4',
             'relative_path': '/private/SECRET_PATH', 'file_size_bytes': 1,
             'file_size_mb': 0, 'duration_sec': 84, 'duration_timecode': '00:01:24:00',
             'format_name': 'mp4', 'video': {'codec': 'h264', 'width': 320, 'height': 180,
             'fps': 25, 'aspect_ratio': '16:9', 'pix_fmt': 'yuv420p', 'bit_rate': None,
             'total_frames': 2100}, 'audio': None, 'subtitles': [], 'subtitle_summary': ''}
    rows = [{'index': i, 'start_sec': i-1, 'end_sec': i, 'duration_sec': 1,
             'start_frame': (i-1)*25, 'end_frame': i*25,
             'start_timecode': f'00:{(i-1)//60:02d}:{(i-1)%60:02d}:00',
             'end_timecode': f'00:{i//60:02d}:{i%60:02d}:00'} for i in range(1, 85)]
    (folder / 'media_manifest.json').write_text(json.dumps({'media': media,
        'scene_count': 84, 'scene_manifest_file': 'scenes_private.json'}))
    scenes = folder / 'scenes_private.json'
    scenes.write_text(json.dumps({'media_id': 'private-id', 'fps': 25,
        'total_scenes': 84, 'analyzed_duration_sec': 84, 'scenes': rows}))
    config = tmp_path / 'local.json'
    config.write_text(json.dumps({'project_root': str(root), 'python': sys.executable}))
    return module, config, scenes, rows


def test_numeric_task_is_authorized_only_for_pinned_stage1():
    module = importlib.import_module('scripts.mac_actions')
    task = {'version': 1, 'task_id': 'stage1-numeric-test', 'mode': 'stage1-numeric',
            'nonce': 'a'*64, 'pr_number': 5, 'code_sha': module.STAGE1_SHA}
    assert module.validate_task(task) == task
    with pytest.raises(ValueError):
        module.validate_task({**task, 'code_sha': 'b'*40})


def test_numeric_check_returns_real_neighbors_without_video(tmp_path, monkeypatch):
    module, config, scenes, rows = local_inputs(tmp_path, monkeypatch)
    before = scenes.read_bytes()
    result = module.numeric_check(config)
    assert result['statistics']['total_scenes'] == 84
    assert result['statistics']['total_duration_sec'] == 84
    assert result['statistics']['max_duration_sec'] == 1
    assert result['adjacent_scenes'] == rows[80:84]
    assert result['numeric_validation'] == 'passed'
    assert result['human_visual_review'] == 'not_verified'
    assert result['preview_image_count'] == 0
    assert scenes.read_bytes() == before
    assert not list(tmp_path.rglob('*.jpg'))
    assert not list(tmp_path.rglob('*.mp4'))
    serialized = json.dumps(result)
    assert 'SECRET' not in serialized and 'private-id' not in serialized
    assert str(tmp_path) not in serialized
    assert len(result['source_scenes_sha256']) == 64


def test_numeric_check_rejects_gap_in_original_json(tmp_path, monkeypatch):
    module, config, scenes, _ = local_inputs(tmp_path, monkeypatch)
    data = json.loads(scenes.read_text())
    data['scenes'][82]['start_sec'] += .2
    scenes.write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match='stage1_numeric_failed'):
        module.numeric_check(config)
