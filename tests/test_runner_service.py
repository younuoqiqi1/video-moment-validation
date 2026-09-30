"""Unit tests for Mac launchd runner service installer and manager."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from vmv.runner_service import (
    generate_plist_xml,
    install_service,
    stop_service,
    get_service_status,
    SERVICE_LABEL,
)


def test_generate_plist_xml_chinese_and_spaces(tmp_path: Path):
    """Verify plist generation handles paths with Chinese characters and spaces."""
    repo = tmp_path / "测试 空间 目录" / "视频 验证 项目"
    py_exec = "/usr/local/bin/python 3.12"

    xml = generate_plist_xml(python_bin=py_exec, repo_root=repo, interval_sec=120)

    assert f"<string>{SERVICE_LABEL}</string>" in xml
    assert "<integer>120</integer>" in xml
    assert "<key>RunAtLoad</key>" in xml
    assert "<true/>" in xml
    assert "测试 空间 目录" in xml
    assert "视频 验证 项目" in xml
    assert "runner.log" in xml


def test_install_and_stop_service_flow(tmp_path: Path):
    """Verify install_service and stop_service call launchctl appropriately."""
    fake_plist = tmp_path / "LaunchAgents" / f"{SERVICE_LABEL}.plist"

    with patch("vmv.runner_service.get_launch_agent_plist_path", return_value=fake_plist):
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=0, stdout="", stderr="")

            # 1. Install
            success, msg = install_service(repo_root=tmp_path, interval_sec=120)
            assert success is True
            assert "成功安装" in msg
            assert fake_plist.exists()

            # 2. Stop
            stop_success, stop_msg = stop_service()
            assert stop_success is True
            assert "已成功停止" in stop_msg
            assert not fake_plist.exists()


def test_get_service_status(tmp_path: Path):
    """Verify get_service_status parses launchctl list output correctly."""
    fake_plist = tmp_path / f"{SERVICE_LABEL}.plist"
    fake_plist.write_text("dummy", encoding="utf-8")

    with patch("vmv.runner_service.get_launch_agent_plist_path", return_value=fake_plist):
        mock_output = f"12345\t0\t{SERVICE_LABEL}\n67890\t0\tcom.apple.other\n"
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")

            status = get_service_status()
            assert status["installed"] is True
            assert status["running"] is True
            assert status["pid"] == 12345
            assert status["last_exit_code"] == 0


def test_stop_service_fails_when_launchctl_fails(tmp_path: Path):
    """Verify stop_service retains plist and returns False when launchctl unload fails."""
    fake_plist = tmp_path / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
    fake_plist.parent.mkdir(parents=True, exist_ok=True)
    fake_plist.write_text("dummy", encoding="utf-8")

    with patch("vmv.runner_service.get_launch_agent_plist_path", return_value=fake_plist):
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=1, stdout="", stderr="Permission denied or unknown error")

            success, msg = stop_service()
            assert success is False
            assert "launchctl unload 失败" in msg
            assert fake_plist.exists()  # Plist must be retained on failure!

