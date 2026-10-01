"""Catch unsafe dispatch, false completion, and disclosure in Mac receipts."""
import hashlib
import importlib
import json
from pathlib import Path

import pytest


def api():
    return importlib.import_module('scripts.mac_actions')


def task(mode='probe'):
    return {'version': 1, 'task_id': 'mac-probe-20261001-1', 'mode': mode,
            'nonce': 'a' * 64, 'pr_number': 3, 'code_sha': ''}


@pytest.mark.parametrize('change', [
    {'mode': 'shell', 'command': 'touch /tmp/not-authorized'},
    {'pr_number': 99}, {'nonce': '../secret'}, {'version': 2},
])
def test_dispatch_rejects_out_of_scope_work(change):
    with pytest.raises(ValueError):
        api().validate_task({**task(), **change})


def test_stage1_rejects_unreviewed_revision():
    with pytest.raises(ValueError):
        api().validate_task({**task('stage1-preview'), 'pr_number': 5, 'code_sha': 'b' * 40})


def test_probe_has_real_file_evidence_and_sanitized_receipts(tmp_path, monkeypatch):
    m = api()
    monkeypatch.setattr(m.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(m.platform, 'machine', lambda: 'arm64')
    receipts = []
    monkeypatch.setattr(m, 'post_receipt', lambda t, r, phase: receipts.append((phase, dict(r))))
    result = m.execute(task(), tmp_path, None)
    assert result['execution_status'] == 'completed'
    assert result['probe_sha256'] == hashlib.sha256(b'a' * 64).hexdigest()
    assert result['notification_status'] == 'sent'
    assert [phase for phase, _ in receipts] == ['started', 'completed']
    assert str(tmp_path) not in json.dumps(result)
    assert not list(tmp_path.glob('**/*.mp4'))


def test_linux_cannot_claim_mac_completion(tmp_path, monkeypatch):
    m = api()
    monkeypatch.setattr(m.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(m, 'post_receipt', lambda *args: pytest.fail('not a Mac receipt'))
    result = m.execute(task(), tmp_path, None)
    assert result['execution_status'] == 'blocked'
    assert result['error_code'] == 'not_macos'


def test_receipt_failure_does_not_claim_chain_success(tmp_path, monkeypatch):
    m = api()
    monkeypatch.setattr(m.platform, 'system', lambda: 'Darwin')
    def unavailable(*args):
        raise RuntimeError('/private/user/token=secret')
    monkeypatch.setattr(m, 'post_receipt', unavailable)
    result = m.execute(task(), tmp_path, None)
    assert result['execution_status'] == 'completed'
    assert result['notification_status'] == 'failed'
    assert 'secret' not in json.dumps(result)


def test_preview_failure_is_safe_and_not_completed(tmp_path, monkeypatch):
    m = api()
    monkeypatch.setattr(m.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(m, 'post_receipt', lambda *args: None)
    def broken(*args):
        raise RuntimeError('/Users/private/input.mp4 SECRET_TOKEN')
    monkeypatch.setattr(m, 'preview', broken)
    t = {**task('stage1-preview'), 'pr_number': 5, 'code_sha': m.STAGE1_SHA}
    result = m.execute(t, tmp_path, Path('local-only.json'))
    assert result['execution_status'] == 'failed'
    assert result['error_code'] == 'execution_failed'
    assert 'SECRET_TOKEN' not in json.dumps(result)
    assert 'input.mp4' not in json.dumps(result)


def test_runner_download_requires_official_checksum():
    m = importlib.import_module('scripts.install_mac_actions')
    release = {'body': '', 'assets': [{'name': 'actions-runner-osx-arm64-2.0.0.tar.gz',
        'browser_download_url': 'https://github.com/actions/runner/releases/download/v2.0.0/actions-runner-osx-arm64-2.0.0.tar.gz',
        'digest': 'sha256:' + 'a' * 64}]}
    assert m.select_archive(release, 'arm64')[1] == 'a' * 64
    release['assets'][0]['digest'] = None
    with pytest.raises(ValueError):
        m.select_archive(release, 'arm64')


def test_runner_download_rejects_wrong_host():
    m = importlib.import_module('scripts.install_mac_actions')
    release = {'body': '', 'assets': [{'name': 'actions-runner-osx-arm64-2.0.0.tar.gz',
        'browser_download_url': 'https://evil.example/runner.tar.gz', 'digest': 'sha256:' + 'a' * 64}]}
    with pytest.raises(ValueError):
        m.select_archive(release, 'arm64')
