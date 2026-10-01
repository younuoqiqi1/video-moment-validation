import importlib
import json
import subprocess

import pytest


def task(m):
    return {'version': 1, 'task_id': 'stage1-cut-check', 'mode': 'stage1-cut-check',
            'nonce': 'a'*64, 'pr_number': 5, 'code_sha': m.CUT_CHECK_SHA}


def test_fixed_cut_job_accepts_only_reviewed_revision():
    m = importlib.import_module('scripts.mac_actions')
    t = task(m)
    assert m.validate_task(t) == t
    for changes in ({'code_sha': 'b'*40}, {'pr_number': 3}, {'command': 'evil'}):
        with pytest.raises(ValueError):
            m.validate_task({**t, **changes})


def test_mac_routes_fixed_job_and_records_actual_failure(tmp_path, monkeypatch):
    m = importlib.import_module('scripts.mac_actions')
    monkeypatch.setattr(m.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(m, 'post_receipt', lambda *a: None)
    seen = []
    def compare(config, output):
        seen.append(output)
        return {'reference_matched_after': 9, 'human_visual_review': 'not_verified'}
    monkeypatch.setattr(m, 'cut_check', compare)
    result = m.execute(task(m), tmp_path, None)
    assert result['execution_status'] == 'completed'
    assert result['reference_matched_after'] == 9
    assert seen and str(tmp_path) not in json.dumps(result)
    def fail(*a):
        raise ValueError('/private/media SECRET_TOKEN')
    monkeypatch.setattr(m, 'cut_check', fail)
    result = m.execute(task(m), tmp_path, None)
    assert result['execution_status'] == 'failed'
    assert 'SECRET_TOKEN' not in json.dumps(result)


def test_only_safe_comparison_fields_are_returned(tmp_path, monkeypatch):
    m = importlib.import_module('scripts.mac_actions')
    target = tmp_path / 'target'
    target.mkdir()
    output = tmp_path / 'output'
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'private'
    manifest = root / 'outputs/stage1/media_manifest.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'scene_manifest_file': 'scenes.json'}))
    (manifest.parent / 'scenes.json').write_text('{}')
    video = root / 'data/input/qianfu_ep18.mp4'
    video.parent.mkdir(parents=True)
    video.write_bytes(b'local')
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'project_root': str(root), 'python': '/usr/bin/python3'}))
    monkeypatch.setattr(m.subprocess, 'check_output', lambda *a, **kw: m.CUT_CHECK_SHA)
    def run(command, **kwargs):
        assert command[2] == 'vmv.cut_comparison'
        assert 'GH_TOKEN' not in kwargs['env']
        destination = root / 'outputs/stage1/cut-recheck' / output.name
        destination.mkdir(parents=True)
        stats = dict(total_scenes=131, total_duration_sec=1800, average_duration_sec=13.7,
            min_duration_sec=.52, max_duration_sec=100, longest_scene_index=80)
        result = dict(before_statistics=stats, after_statistics=stats,
            reference_count=14, reference_matched_before=0, reference_matched_after=9,
            reference_unmatched_frames=[50], added_candidate_frames=[55],
            removed_candidate_frames=[], unlabelled_added_frames=[55], tolerance_frames=1,
            source_scenes_sha256='a'*64, source_media_manifest_sha256='b'*64,
            source_video_sha256='c'*64, baseline_reproduced=True,
            numeric_validation='passed', preview_image_count=200,
            human_visual_review='not_verified', false_cut_rate=None,
            private_path=str(root), token='SECRET_TOKEN')
        (destination / 'comparison.json').write_text(json.dumps(result))
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(m, 'run_process', run)
    result = m.cut_check(config, output)
    assert result['reference_matched_after'] == 9
    assert 'SECRET_TOKEN' not in json.dumps(result)
    assert str(root) not in json.dumps(result)


def test_safe_failure_diagnostics_are_allowlisted():
    m = importlib.import_module('scripts.mac_actions')
    result = m.safe_cut_failure('checkpoint:fixed_detection\n' + json.dumps({
        'failure_stage': 'fixed_detection', 'error_code': 'invalid_data',
        'token': 'SECRET_TOKEN', 'path': '/private/media'}))
    assert result == {'failure_stage': 'fixed_detection', 'error_code': 'invalid_data'}
    assert m.safe_cut_failure(json.dumps({'failure_stage': '/private/media',
        'error_code': 'SECRET_TOKEN'})) == {'error_code': 'stage1_cut_check_failed'}
