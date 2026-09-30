"""User-level launchd service installer and manager for Mac."""

import html
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SERVICE_LABEL = "com.vmv.runner"


def get_launch_agent_plist_path() -> Path:
    """Return path to user's launchd agent plist."""
    return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"


def generate_plist_xml(
    python_bin: str,
    repo_root: Path,
    interval_sec: int = 120,
) -> str:
    """Generate launchd XML string with proper escaping and absolute paths."""
    resolved_python = html.escape(str(Path(python_bin).absolute()))
    resolved_repo = html.escape(str(repo_root.resolve()))
    src_dir = html.escape(str((repo_root / "src").resolve()))
    log_file = html.escape(str((repo_root / ".vmv-runner" / "runner.log").resolve()))

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{SERVICE_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{resolved_python}</string>
        <string>-m</string>
        <string>vmv</string>
        <string>runner</string>
        <string>once</string>
        <string>--repo</string>
        <string>{resolved_repo}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{resolved_repo}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>{src_dir}</string>
    </dict>
    <key>StartInterval</key>
    <integer>{interval_sec}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_file}</string>
    <key>StandardErrorPath</key>
    <string>{log_file}</string>
</dict>
</plist>
"""


def install_service(
    repo_root: Path,
    python_bin: str | None = None,
    interval_sec: int = 120,
) -> tuple[bool, str]:
    """
    Install and load the user-level launchd agent.
    Returns (success, message).
    """
    if python_bin:
        py_exec = python_bin
    elif (repo_root / ".venv" / "bin" / "python").exists():
        py_exec = str(repo_root / ".venv" / "bin" / "python")
    else:
        py_exec = sys.executable
    plist_path = get_launch_agent_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure log directory exists
    (repo_root / ".vmv-runner").mkdir(parents=True, exist_ok=True)

    xml_content = generate_plist_xml(py_exec, repo_root, interval_sec=interval_sec)

    try:
        # If already loaded, unload first
        if plist_path.exists():
            unload_res = subprocess.run(
                ["launchctl", "unload", "-w", str(plist_path)],
                capture_output=True,
                text=True,
            )
            if unload_res.returncode != 0:
                err = unload_res.stderr.strip() or unload_res.stdout.strip()
                if "Could not find" not in err and "No such process" not in err:
                    return False, f"安装失败: 卸载既有服务失败: {err or '退出码 ' + str(unload_res.returncode)}"

        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(xml_content)

        # Load service
        res = subprocess.run(
            ["launchctl", "load", "-w", str(plist_path)],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return True, f"成功安装并启用后台轮询服务: {SERVICE_LABEL} (周期 {interval_sec} 秒)"
        else:
            err = res.stderr.strip() or res.stdout.strip()
            return False, f"launchctl load 失败: {err}"
    except Exception as exc:
        return False, f"安装后台服务异常: {exc}"


def stop_service() -> tuple[bool, str]:
    """Unload and remove the launchd service."""
    plist_path = get_launch_agent_plist_path()
    if not plist_path.exists():
        return True, "后台服务未安装或已移除。"

    try:
        res = subprocess.run(
            ["launchctl", "unload", "-w", str(plist_path)],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            if "Could not find" not in err and "No such process" not in err:
                return False, f"停止后台服务失败: launchctl unload 失败: {err or '退出码 ' + str(res.returncode)}"

        try:
            plist_path.unlink()
        except OSError as exc:
            return False, f"删除配置文件失败: {exc}"

        return True, f"已成功停止并卸载后台服务: {SERVICE_LABEL}"
    except Exception as exc:
        return False, f"停止后台服务失败: {exc}"


def get_service_status() -> dict[str, Any]:
    """Check service registration status via launchctl."""
    plist_path = get_launch_agent_plist_path()
    installed = plist_path.exists()

    running = False
    pid = None
    last_exit_code = None

    if installed:
        try:
            res = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if SERVICE_LABEL in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        pid_str, exit_str = parts[0], parts[1]
                        running = pid_str != "-"
                        pid = int(pid_str) if running else None
                        last_exit_code = int(exit_str) if exit_str.isdigit() else 0
                        break
        except Exception:
            pass

    return {
        "service_label": SERVICE_LABEL,
        "plist_path": str(plist_path) if installed else None,
        "installed": installed,
        "running": running,
        "pid": pid,
        "last_exit_code": last_exit_code,
    }
