"""An inherited pipe must not keep a cancelled local job alive."""
import importlib
import json
import subprocess
import sys
import time

import pytest


def test_timeout_returns_even_when_grandchild_holds_stdout():
    module = importlib.import_module('scripts.mac_actions')
    code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print('checkpoint:read_scenes',flush=True); time.sleep(30)"
    before = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        module.run_process([sys.executable, '-c', code], timeout=.15)
    assert time.monotonic() - before < 3
    assert 'checkpoint:read_scenes' in caught.value.output


def test_started_result_exists_before_network_receipt(tmp_path, monkeypatch):
    module = importlib.import_module('scripts.mac_actions')
    monkeypatch.setattr(module.platform, 'system', lambda: 'Darwin')
    def receipt(task, result, phase):
        saved = json.loads((tmp_path / 'result.json').read_text())
        assert saved['execution_status'] == result['execution_status']
        assert saved['checkpoint'] == 'receipt_' + phase
    monkeypatch.setattr(module, 'post_receipt', receipt)
    task = {'version': 1, 'task_id': 'probe-timeout-check', 'mode': 'probe',
            'nonce': 'a'*64, 'pr_number': 3, 'code_sha': ''}
    result = module.execute(task, tmp_path, None)
    assert result['notification_status'] == 'sent'
    assert result['execution_status'] == 'completed'
