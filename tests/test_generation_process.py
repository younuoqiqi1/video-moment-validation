import os
import signal
import subprocess
import sys
import time
import pytest
from vmv.generation_process import run_generation


def test_timeout_cleans_child_that_inherits_output_pipe(tmp_path):
    pid_file = tmp_path / 'child.pid'
    code = 'import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); open(sys.argv[1],"w").write(str(p.pid)); time.sleep(30)'
    start = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_generation([sys.executable, '-c', code, str(pid_file)], timeout=0.5)
        assert time.monotonic() - start < 4
        pid = int(pid_file.read_text())
        result = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True, timeout=2)
        assert not result.stdout.strip() or result.stdout.strip().startswith('Z')
    finally:
        if pid_file.exists():
            try: os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError: pass


def test_success_returns_stdout_and_restores_signal_handler():
    old = signal.getsignal(signal.SIGTERM)
    result = run_generation([sys.executable, '-c', 'print("ok")'])
    assert result.stdout == 'ok\n'
    assert signal.getsignal(signal.SIGTERM) == old


def test_process_working_directory_and_stderr(tmp_path):
    result = run_generation([sys.executable, '-c', 'from pathlib import Path; import sys; print(Path.cwd()); print("diagnostic",file=sys.stderr)'], cwd=tmp_path)
    assert result.stdout.strip() == str(tmp_path)
    assert result.stderr.strip() == 'diagnostic'
