"""Tests for CLI status and environment verification."""

import json
import os
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


def test_status_cli_rejects_non_json_output_r1(tmp_path: Path, capsys):
    """
    R1 regression: Reject non-.json output (e.g. environment.html) before writing.
    Preserve existing sentinel file and exit non-zero.
    """
    html_target = tmp_path / "environment.html"
    sentinel_content = "<!-- SENTINEL CONTENT: DO NOT OVERWRITE -->"
    html_target.write_text(sentinel_content, encoding="utf-8")

    exit_code = main(["status", "--output", str(html_target)])
    assert exit_code != 0

    # Ensure sentinel content was preserved and not overwritten
    assert html_target.read_text(encoding="utf-8") == sentinel_content

    captured = capsys.readouterr()
    assert ".json" in captured.out
    assert "输出报告路径必须以 .json 结尾" in captured.out
    assert "所有环境依赖检查通过" not in captured.out


def test_status_cli_filesystem_error_handling_r2(tmp_path: Path, capsys):
    """
    R2 regression: Handle filesystem errors (e.g. target is a directory or parent is a file).
    Return non-zero and output clear Chinese error without claiming success.
    """
    # Case A: output path is an existing directory with .json suffix
    conflict_dir = tmp_path / "conflict.json"
    conflict_dir.mkdir()

    exit_code_a = main(["status", "--output", str(conflict_dir)])
    assert exit_code_a != 0
    captured_a = capsys.readouterr()
    assert "文件系统异常" in captured_a.out or "写入 JSON 报告失败" in captured_a.out
    assert "所有环境依赖检查通过" not in captured_a.out

    # Case B: parent directory is a regular file
    file_as_dir = tmp_path / "blocker_file"
    file_as_dir.write_text("i am a file", encoding="utf-8")
    blocked_target = file_as_dir / "env.json"

    exit_code_b = main(["status", "--output", str(blocked_target)])
    assert exit_code_b != 0
    captured_b = capsys.readouterr()
    assert "无法创建输出目录" in captured_b.out or "文件系统异常" in captured_b.out
    assert "所有环境依赖检查通过" not in captured_b.out


def test_status_cli_python_version_insufficient(tmp_path: Path):
    """Verify check_environment fails when Python version < 3.12."""
    def mock_probe(cmd: list[str], timeout_sec: float = 5.0):
        tool = cmd[0]
        return True, f"{tool} 1.0.0", None

    old_py_version_info = (3, 11, 5, "final", 0)
    out_file = tmp_path / "env_old_py.json"

    with patch("sys.version_info", old_py_version_info):
        with patch("vmv.report.probe_tool_version", side_effect=mock_probe):
            exit_code = main(["status", "--output", str(out_file)])
            assert exit_code == 1

            assert out_file.exists()
            data = json.loads(out_file.read_text(encoding="utf-8"))
            assert data["overall_status"] == "failed"
            assert "Python >= 3.12" in data["missing_items"]
            assert any("3.12" in err for err in data["errors"])


def test_status_cli_html_directory_failure_r2a(tmp_path: Path, capsys):
    """
    R2a regression: When HTML destination is a directory, writing HTML fails.
    Assert non-zero exit, Chinese explanation, no success message,
    artifacts list is empty, and any residual JSON has overall_status="failed".
    """
    def mock_probe(cmd: list[str], timeout_sec: float = 5.0):
        tool = cmd[0]
        return True, f"{tool} 1.0.0", None

    html_dir = tmp_path / "env.html"
    html_dir.mkdir()
    target_json = tmp_path / "env.json"

    with patch("vmv.report.probe_tool_version", side_effect=mock_probe):
        # 1. Test CLI main()
        exit_code = main(["status", "--output", str(target_json)])
        assert exit_code != 0

        # Assert user directory is preserved
        assert html_dir.is_dir()

        captured = capsys.readouterr()
        assert "文件系统异常" in captured.out or "写入 HTML 报告失败" in captured.out
        assert "所有环境依赖检查通过" not in captured.out

        # If a JSON exists, assert it does NOT claim overall_status="passed"
        if target_json.exists():
            data = json.loads(target_json.read_text(encoding="utf-8"))
            assert data["overall_status"] == "failed"
            assert "report_generation_status" in data
            assert data["report_generation_status"] == "failed"

        # 2. Test run_status_stage directly
        res = run_status_stage(target_json)
        assert res.status == "failed"
        assert res.artifacts == []
        assert res.details.get("overall_status") == "failed"
        assert any("HTML" in e or "文件系统" in e for e in res.errors)


def test_status_cli_html_permission_error_r2a(tmp_path: Path, capsys):
    """
    R2a regression: When publishing HTML raises PermissionError during os.replace.
    Assert non-zero exit, no success output, and no misleading success JSON.
    """
    def mock_probe(cmd: list[str], timeout_sec: float = 5.0):
        tool = cmd[0]
        return True, f"{tool} 1.0.0", None

    target_json = tmp_path / "test_perm.json"
    html_target = tmp_path / "test_perm.html"

    real_replace = os.replace

    def fake_replace(src, dst):
        if str(dst).endswith(".html"):
            raise PermissionError("模拟写入 HTML 权限被拒绝")
        return real_replace(src, dst)

    with patch("vmv.report.probe_tool_version", side_effect=mock_probe):
        with patch("os.replace", side_effect=fake_replace):
            exit_code = main(["status", "--output", str(target_json)])
            assert exit_code != 0

            captured = capsys.readouterr()
            assert "写入 HTML 报告失败" in captured.out or "文件系统异常" in captured.out
            assert "所有环境依赖检查通过" not in captured.out

            if target_json.exists():
                data = json.loads(target_json.read_text(encoding="utf-8"))
                assert data["overall_status"] == "failed"


def test_status_cli_symlink_loop_r2b(tmp_path: Path, capsys):
    """
    R2b regression: Symlink loop must be caught as a Chinese error, not unhandled RuntimeError.
    """
    loop_target = tmp_path / "loop.json"
    try:
        os.symlink(str(loop_target), str(loop_target))
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not supported on this filesystem")

    exit_code = main(["status", "--output", str(loop_target)])
    assert exit_code != 0

    captured = capsys.readouterr()
    assert "路径解析失败" in captured.out or "符号链接循环" in captured.out
    assert "所有环境依赖检查通过" not in captured.out


def test_status_cli_resolve_permission_error_r2b(tmp_path: Path, capsys):
    """
    R2b regression: Path.resolve raising OSError/PermissionError must be caught gracefully.
    """
    target = tmp_path / "resolve_fail.json"

    with patch.object(Path, "resolve", side_effect=PermissionError("模拟路径解析无权限")):
        exit_code = main(["status", "--output", str(target)])
        assert exit_code != 0

        captured = capsys.readouterr()
        assert "路径解析失败" in captured.out or "权限异常" in captured.out
        assert "所有环境依赖检查通过" not in captured.out
