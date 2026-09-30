"""Unit tests for offline probe verification controller and worker."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from scripts.verify_offline_probe import (
    verify_probe_bytes,
    check_host_app_closed,
    run_worker,
    run_controller,
    cleanup_launchd_service,
    HOST_APP_SIGNATURE,
)


def test_verify_probe_bytes_exact_match(tmp_path: Path):
    """Verify strict byte equality matches expected PROBE_RESULT={token}\\n exactly."""
    token = "MY_SECRET_TOKEN_123"
    target_file = tmp_path / "probe-result.txt"
    target_file.write_bytes(f"PROBE_RESULT={token}\n".encode("utf-8"))

    assert verify_probe_bytes(target_file, token) is True


def test_verify_probe_bytes_rejects_wrong_prefix_or_suffix(tmp_path: Path):
    """Verify any extra prefix, suffix, or containing string is strictly rejected."""
    token = "TOKEN_TEST"
    target_file = tmp_path / "probe-result.txt"

    # In legacy shell script, this would match `*TOKEN_TEST*`, but strict bytes must reject it
    target_file.write_bytes(f"WRONG PREFIX {token} WRONG SUFFIX\n".encode("utf-8"))
    assert verify_probe_bytes(target_file, token) is False

    target_file.write_bytes(f"PROBE_RESULT={token}_EXTRA\n".encode("utf-8"))
    assert verify_probe_bytes(target_file, token) is False

    target_file.write_bytes(f"PREFIX_PROBE_RESULT={token}\n".encode("utf-8"))
    assert verify_probe_bytes(target_file, token) is False


def test_verify_probe_bytes_rejects_multiline_and_quotes(tmp_path: Path):
    """Verify multiline output or quotes around result are rejected."""
    token = "TOKEN_QUOTED"
    target_file = tmp_path / "probe-result.txt"

    target_file.write_bytes(f'"PROBE_RESULT={token}"\n'.encode("utf-8"))
    assert verify_probe_bytes(target_file, token) is False

    target_file.write_bytes(f"PROBE_RESULT={token}\nEXTRA LINE\n".encode("utf-8"))
    assert verify_probe_bytes(target_file, token) is False


def test_check_host_app_closed_detects_gui_process():
    """Verify detection of running GUI application."""
    fake_ps_output = (
        "  PID COMMAND\n"
        "    1 /sbin/launchd\n"
        f"12345 {HOST_APP_SIGNATURE} --flag\n"
        "54321 /bin/bash\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_ps_output, stderr="")
        app_closed, app_closed_verified, evidence = check_host_app_closed()

        assert app_closed is False
        assert app_closed_verified is True
        assert "12345" in evidence


def test_check_host_app_closed_distinguishes_cli_process():
    """Verify CLI agy process is NOT confused with GUI Antigravity.app."""
    fake_ps_output = (
        "  PID COMMAND\n"
        "    1 /sbin/launchd\n"
        "22222 /Users/yoyotaozhou/.local/bin/agy --print hello\n"
        "33333 python3 -m pytest\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_ps_output, stderr="")
        app_closed, app_closed_verified, evidence = check_host_app_closed()

        assert app_closed is True
        assert app_closed_verified is True
        assert "未检测到" in evidence


def test_worker_execution_success(tmp_path: Path):
    """Verify worker invokes CLI, checks byte equality, and writes structured JSON."""
    token = "TEST_TOKEN_XYZ"
    result_file = tmp_path / "result.json"
    target_file = tmp_path / "probe-result.txt"

    # Pre-populate target file as if CLI created it
    target_file.write_bytes(f"PROBE_RESULT={token}\n".encode("utf-8"))

    args = argparse.Namespace(
        probe_dir=str(tmp_path),
        result_file=str(result_file),
        token=token,
        delay_seconds=0,
        agy_bin="fake_agy",
        model="gemini-3.8-flash-high",
    )

    with patch("subprocess.Popen") as mock_popen, patch(
        "scripts.verify_offline_probe.check_host_app_closed",
        return_value=(True, True, "Host app confirmed closed"),
    ):
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        exit_code = run_worker(args)
        assert exit_code == 0
        assert result_file.exists()

        data = json.loads(result_file.read_text(encoding="utf-8"))
        assert data["cli_passed"] is True
        assert data["token_verified"] is True
        assert data["app_closed"] is True
        assert data["app_closed_verified"] is True
        assert data["actual_content"] == f"PROBE_RESULT={token}\n"


def test_worker_handles_cli_timeout(tmp_path: Path):
    """Verify worker handles timeout expired safely."""
    token = "TIMEOUT_TOKEN"
    result_file = tmp_path / "result.json"

    args = argparse.Namespace(
        probe_dir=str(tmp_path),
        result_file=str(result_file),
        token=token,
        delay_seconds=0,
        agy_bin="fake_agy",
        model="gemini-3.8-flash-high",
    )

    with patch("subprocess.Popen") as mock_popen, patch(
        "scripts.verify_offline_probe.check_host_app_closed",
        return_value=(True, True, "Host app closed"),
    ):
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd=["fake_agy"], timeout=600.0)
        mock_popen.return_value = mock_proc

        exit_code = run_worker(args)
        assert exit_code == 1
        assert result_file.exists()

        data = json.loads(result_file.read_text(encoding="utf-8"))
        assert data["cli_passed"] is False
        assert data["exit_code"] == 124
        assert "超时" in (data.get("error") or "")


def test_controller_always_unloads_and_unlinks_plist(tmp_path: Path):
    """Verify controller always unloads and deletes plist in finally block even on error."""
    fake_plist_dir = tmp_path / "LaunchAgents"
    fake_plist_dir.mkdir(parents=True)

    args = argparse.Namespace(
        delay_seconds=0,
        timeout=1,
        agy_bin="fake_agy",
        model="gemini-3.8-flash-high",
    )

    with patch("pathlib.Path.home", return_value=tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            exit_code = run_controller(args)
            assert exit_code == 1  # Timed out waiting for result

            # Verify launchctl unload was called
            unload_calls = [
                call for call in mock_run.call_args_list if "unload" in call[0][0]
            ]
            assert len(unload_calls) >= 1
            # Verify no .plist files remain in fake_plist_dir
            remaining_plists = list(fake_plist_dir.glob("*.plist"))
            assert len(remaining_plists) == 0


def test_cleanup_launchd_service_preserves_plist_when_unload_fails(tmp_path: Path):
    """Keep the plist for recovery and report failure if launchctl cannot unload."""
    plist_path = tmp_path / "probe.plist"
    plist_path.write_text("recovery data", encoding="utf-8")

    with patch(
        "scripts.verify_offline_probe.subprocess.run",
        return_value=MagicMock(returncode=5, stdout="", stderr="service busy"),
    ):
        with pytest.raises(RuntimeError, match="卸载失败"):
            cleanup_launchd_service(plist_path)

    assert plist_path.read_text(encoding="utf-8") == "recovery data"


def test_cleanup_launchd_service_unloads_before_removing_plist(tmp_path: Path):
    """Remove the plist only after launchctl reports a successful unload."""
    plist_path = tmp_path / "probe.plist"
    plist_path.write_text("temporary config", encoding="utf-8")

    with patch(
        "scripts.verify_offline_probe.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    ) as mock_run:
        cleanup_launchd_service(plist_path)

    mock_run.assert_called_once()
    assert mock_run.call_args.args[0][:3] == ["launchctl", "unload", "-w"]
    assert not plist_path.exists()
