"""Tests for CLI status and environment verification."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from vmv.cli import main
from vmv.report import check_environment, run_status_stage, probe_tool_version


def test_probe_tool_version_timeout():
    """Verify probe_tool_version handles subprocess timeout gracefully."""
    with patch("shutil.which", return_value="/fake/agy"):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["agy", "--version"], timeout=0.1)):
            success, ver, err = probe_tool_version(["agy", "--version"], timeout_sec=0.1)
            assert not success
            assert ver is None
            assert "探测超时" in err


def test_probe_tool_version_not_found():
    """Verify probe_tool_version handles nonexistent tool."""
    with patch("shutil.which", return_value=None):
        success, ver, err = probe_tool_version(["nonexistent_tool_xyz", "--version"])
        assert not success
        assert ver is None
        assert "未在环境变量 PATH 中找到" in err


def test_check_environment_missing_ffmpeg(tmp_path: Path):
    """Verify check_environment fails when ffmpeg is missing."""
    def mock_probe(cmd: list[str], timeout_sec: float = 5.0):
        tool = cmd[0]
        if tool in ("ffmpeg", "ffprobe"):
            return False, None, f"未在环境变量 PATH 中找到可执行命令: {tool}"
        return True, f"{tool} 1.0.0", None

    with patch("vmv.report.probe_tool_version", side_effect=mock_probe):
        env = check_environment()
        assert env["overall_status"] == "failed"
        assert "ffmpeg" in env["missing_items"]
        assert "ffprobe" in env["missing_items"]
        assert any("ffmpeg" in err.lower() for err in env["errors"])


def test_status_cli_all_passed(tmp_path: Path):
    """Verify status command returns 0 when all required tools pass."""
    def mock_probe(cmd: list[str], timeout_sec: float = 5.0):
        tool = cmd[0]
        return True, f"{tool} version 1.0.0", None

    out_file = tmp_path / "stage0" / "environment.json"

    with patch("vmv.report.probe_tool_version", side_effect=mock_probe):
        exit_code = main(["status", "--output", str(out_file)])
        assert exit_code == 0

        assert out_file.exists()
        html_file = out_file.with_suffix(".html")
        assert html_file.exists()

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["overall_status"] == "passed"
        assert len(data["missing_items"]) == 0
        assert data["system"]["platform"] != ""
        assert "python" in data["tools"]
        assert "ffmpeg" in data["tools"]
        assert "ffprobe" in data["tools"]
        assert "git" in data["tools"]
        assert "agy" in data["tools"]

        html_text = html_file.read_text(encoding="utf-8")
        assert "数智博主视频镜头检索 - 本地环境核验报告" in html_text
        assert "通过 (All Passed)" in html_text


def test_status_cli_chinese_and_spaces_path(tmp_path: Path):
    """Verify status generation works with Chinese and spaced path names."""
    spaced_dir = tmp_path / "测试 输出 目录" / "子 阶段 0"
    out_file = spaced_dir / "环境 核验.json"

    def mock_probe(cmd: list[str], timeout_sec: float = 5.0):
        tool = cmd[0]
        return True, f"{tool} version 1.0.0", None

    with patch("vmv.report.probe_tool_version", side_effect=mock_probe):
        exit_code = main(["status", "--output", str(out_file)])
        assert exit_code == 0
        assert out_file.exists()
        assert out_file.with_suffix(".html").exists()

        content = out_file.read_text(encoding="utf-8")
        assert "overall_status" in content


def test_status_cli_missing_tool_exit_code_1(tmp_path: Path):
    """Verify status command returns exit code 1 when required tools are missing."""
    def mock_probe(cmd: list[str], timeout_sec: float = 5.0):
        tool = cmd[0]
        if tool == "ffmpeg":
            return False, None, "未找到 ffmpeg"
        return True, f"{tool} version 1.0.0", None

    out_file = tmp_path / "env.json"
    with patch("vmv.report.probe_tool_version", side_effect=mock_probe):
        exit_code = main(["status", "--output", str(out_file)])
        assert exit_code == 1
        assert out_file.exists()

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["overall_status"] == "failed"
        assert "ffmpeg" in data["missing_items"]

        html_text = out_file.with_suffix(".html").read_text(encoding="utf-8")
        assert "待修复/安装项清单" in html_text
        assert "未通过" in html_text
