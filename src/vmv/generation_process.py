import atexit
import os
import signal
import subprocess
import threading
from types import SimpleNamespace


def run_generation(argv, timeout=60):
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    def cleanup():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass

    atexit.register(cleanup)
    is_main = threading.current_thread() is threading.main_thread()
    old_sigterm = None
    if is_main:
        def sigterm_handler(signum, frame):
            cleanup()
            raise SystemExit(143)

        old_sigterm = signal.signal(signal.SIGTERM, sigterm_handler)

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    finally:
        cleanup()
        proc.stdout.close()
        proc.stderr.close()
        atexit.unregister(cleanup)
        if is_main:
            signal.signal(signal.SIGTERM, old_sigterm)

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, argv, output=stdout)

    return SimpleNamespace(stdout=stdout)
