"""
Offline Probe Verification Controller & Worker (Pure Python Implementation).
Allows verifying AGY CLI execution after quitting the Antigravity GUI App.

Usage:
  # Normal execution (starts controller, schedules launchd worker, waits for result)
  python3 scripts/verify_offline_probe.py

  # Worker mode (invoked automatically by launchd)
  python3 scripts/verify_offline_probe.py --worker --probe-dir <dir> --result-file <file> --token <token>
"""

import argparse
import json
import os
import plistlib
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


HOST_APP_SIGNATURE = "/Applications/Antigravity.app/Contents/MacOS/Antigravity"
DEFAULT_AGY_BIN = "/Users/yoyotaozhou/.local/bin/agy"
DEFAULT_MODEL = "gemini-3.8-flash-high"


def check_host_app_closed(app_signature: str = HOST_APP_SIGNATURE) -> tuple[bool, bool, str]:
    """
    Check whether the host GUI application is completely closed.
    Distinguishes host GUI process from CLI processes (agy).
    Returns (app_closed, app_closed_verified, evidence_str).
    """
    try:
        res = subprocess.run(
            ["ps", "-eo", "pid,command"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode != 0:
            return False, False, f"ps 命令执行失败: {res.stderr.strip()}"

        gui_pids = []
        for line in res.stdout.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            # Match the exact GUI executable signature, exclude self or CLI runner
            if app_signature in line_str and "verify_offline_probe.py" not in line_str:
                parts = line_str.split(None, 1)
                gui_pids.append(parts[0])

        if gui_pids:
            return False, True, f"检测到宿主 GUI 进程运行中 (PID: {', '.join(gui_pids)})"
        return True, True, "未检测到 Antigravity GUI 进程运行"
    except Exception as exc:
        return False, False, f"检测宿主应用进程异常: {exc}"


def verify_probe_bytes(file_path: Path, expected_token: str) -> bool:
    """
    Strict byte-for-byte verification.
    Expected: PROBE_RESULT={expected_token}\n
    Rejects any prefix, suffix, multiline, quotes, or partial match.
    """
    if not file_path.exists() or not file_path.is_file():
        return False
    try:
        content = file_path.read_bytes()
        expected = f"PROBE_RESULT={expected_token}\n".encode("utf-8")
        return content == expected
    except Exception:
        return False


def run_worker(args: argparse.Namespace) -> int:
    """Worker entry point, executed via launchd in background."""
    probe_dir = Path(args.probe_dir).resolve()
    result_file = Path(args.result_file).resolve()
    token = args.token
    agy_bin = args.agy_bin or DEFAULT_AGY_BIN
    model = args.model or DEFAULT_MODEL
    delay_seconds = args.delay_seconds

    # Wait for the user to quit the host app if specified
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    start_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    app_closed, app_closed_verified, app_check_evidence = check_host_app_closed()

    prompt = (
        f"只在当前目录创建 probe-result.txt，文件内容严格且仅写入单行：PROBE_RESULT={token}\n，"
        f"严禁包含额外前后缀、引号或操作任何其他文件。"
    )

    cmd = [
        agy_bin,
        "--print",
        prompt,
        "--model",
        model,
        "--dangerously-skip-permissions",
    ]

    target_file = probe_dir / "probe-result.txt"
    stdout_file = probe_dir / "stdout.log"
    stderr_file = probe_dir / "stderr.log"

    cli_exit_code = 1
    cli_error: str | None = None
    if not app_closed or not app_closed_verified:
        cli_exit_code = 125
        cli_error = f"未启动 AGY CLI：宿主 GUI 未确认关闭（{app_check_evidence}）"
    else:
        try:
            with open(stdout_file, "w", encoding="utf-8") as out_f, open(
                stderr_file, "w", encoding="utf-8"
            ) as err_f:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(probe_dir),
                    stdout=out_f,
                    stderr=err_f,
                )
                cli_exit_code = proc.wait(timeout=600.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5.0)
            except Exception:
                pass
            cli_exit_code = 124
            cli_error = "AGY CLI 执行超时 (600s)"
        except Exception as exc:
            cli_exit_code = 1
            cli_error = f"启动或执行 AGY CLI 异常: {exc}"
    
    end_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    token_match = verify_probe_bytes(target_file, token)

    actual_content = ""
    if target_file.exists():
        try:
            actual_content = target_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    payload = {
        "step": "app_closed_offline_probe",
        "cli_passed": (cli_exit_code == 0),
        "token_verified": token_match,
        "app_closed": app_closed,
        "app_closed_verified": app_closed_verified,
        "app_check_evidence": app_check_evidence,
        "exit_code": cli_exit_code,
        "start_time": start_time,
        "end_time": end_time,
        "target_file_exists": target_file.exists(),
        "actual_content": actual_content,
        "error": cli_error,
    }

    result_file.parent.mkdir(parents=True, exist_ok=True)
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return 0 if (cli_exit_code == 0 and token_match and app_closed and app_closed_verified) else 1



def cleanup_launchd_service(plist_path: Path) -> None:
    """Unload the temporary launchd job before removing its recovery plist.

    If launchctl cannot confirm the unload, keep the plist so the job can still
    be inspected or unloaded manually, and fail the verification run.
    """
    result = subprocess.run(
        ["launchctl", "unload", "-w", str(plist_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"launchctl 卸载失败；保留 plist 供排查: {detail}")

    try:
        plist_path.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError(f"launchd 已卸载，但无法删除 plist {plist_path}: {exc}") from exc

    if plist_path.exists():
        raise RuntimeError(f"launchd 已卸载，但 plist 仍存在: {plist_path}")

def run_controller(args: argparse.Namespace) -> int:
    """Controller entry point, sets up environment and launchd service, monitors and cleans up."""
    print("==================================================")
    print("AGY 闭门/离线后台执行能力独立验证控制器 (Pure Python)")
    print("==================================================")

    token = f"TOKEN_OFFLINE_{secrets.token_hex(16)}"
    probe_dir = Path(tempfile.mkdtemp(prefix="vmv_probe_")).resolve()

    subprocess.run(["git", "init"], cwd=str(probe_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "offline-probe@example.com"], cwd=str(probe_dir), check=True)
    subprocess.run(["git", "config", "user.name", "Offline Probe Controller"], cwd=str(probe_dir), check=True)

    result_file = probe_dir / "probe_result.json"
    label = f"com.vmv.probe_offline_{secrets.token_hex(4)}"
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / f"{label}.plist"

    script_path = Path(__file__).resolve()

    plist_data = {
        "Label": label,
        "ProgramArguments": [
            sys.executable,
            str(script_path),
            "--worker",
            "--probe-dir",
            str(probe_dir),
            "--result-file",
            str(result_file),
            "--token",
            token,
            "--delay-seconds",
            str(args.delay_seconds),
            "--agy-bin",
            args.agy_bin or DEFAULT_AGY_BIN,
            "--model",
            args.model or DEFAULT_MODEL,
        ],
        "RunAtLoad": True,
        "StandardOutPath": f"/tmp/{label}.stdout.log",
        "StandardErrorPath": f"/tmp/{label}.stderr.log",
    }

    try:
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_data, f)

        # Ensure unloaded prior to loading
        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        res = subprocess.run(["launchctl", "load", "-w", str(plist_path)], capture_output=True, text=True)
        if res.returncode != 0:
            print(f"[-] launchctl 加载服务失败: {res.stderr.strip() or res.stdout.strip()}")
            return 1

        print(f"[+] 离线验证后台任务已通过 launchd 成功排期！")
        print(f"[+] 任务 Label: {label}")
        print(f"[+] 验证令牌: {token}")
        print(f"[+] 临时工作区: {probe_dir}")
        print(f"[+] 倒计时 {args.delay_seconds} 秒内请完全退出 Antigravity / 宿主 IDE (Cmd + Q)！")
        print(f"[+] 控制器正在等待 worker 完成写入结果（最长等待 {args.timeout} 秒）...")

        # Poll result file
        start_wait = time.time()
        completed = False
        while time.time() - start_wait < args.timeout:
            if result_file.exists():
                try:
                    with open(result_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if "step" in data:
                        completed = True
                        break
                except Exception:
                    pass
            time.sleep(2)

        if not completed:
            print(f"[-] 等待超时（超过 {args.timeout} 秒），未读取到有效结果。")
            return 1

        with open(result_file, "r", encoding="utf-8") as f:
            result_data = json.load(f)

        print("\n================ 离线验证结果 ================")
        print(f"CLI 进程退出状态: {'PASS (退出码 0)' if result_data.get('cli_passed') else 'FAIL'}")
        print(f"令牌全量精确匹配: {'PASS (字节全等)' if result_data.get('token_verified') else 'FAIL'}")
        print(f"宿主 GUI 真实关闭: {'PASS (未运行)' if result_data.get('app_closed') else 'FAIL (仍在运行)'}")
        print(f"关闭核验有效性: {'PASS' if result_data.get('app_closed_verified') else 'UNVERIFIED'}")
        print(f"进程检查证据: {result_data.get('app_check_evidence')}")
        if result_data.get("error"):
            print(f"诊断错误: {result_data.get('error')}")
        print("==============================================")

        all_ok = (
            result_data.get("cli_passed")
            and result_data.get("token_verified")
            and result_data.get("app_closed")
            and result_data.get("app_closed_verified")
        )
        return 0 if all_ok else 1

    finally:
        # Fail closed: do not delete the recovery plist or claim success if
        # launchctl cannot unload the job.
        print(f"[+] 正在清理本次离线验证临时服务: {label}...")
        try:
            cleanup_launchd_service(plist_path)
        except RuntimeError as exc:
            print(f"[-] 临时服务清理失败: {exc}", file=sys.stderr)
            raise
        print("[+] 临时服务已卸载，plist 已删除。")


def main() -> int:
    parser = argparse.ArgumentParser(description="AGY Offline Probe Verification")
    parser.add_argument("--worker", action="store_true", help="Run in worker mode (launched by launchd)")
    parser.add_argument("--probe-dir", type=str, help="Directory for probe execution")
    parser.add_argument("--result-file", type=str, help="Path to write JSON result")
    parser.add_argument("--token", type=str, help="Expected token string")
    parser.add_argument("--delay-seconds", type=int, default=15, help="Delay before starting worker execution")
    parser.add_argument("--timeout", type=int, default=600, help="Controller timeout in seconds")
    parser.add_argument("--agy-bin", type=str, default=DEFAULT_AGY_BIN, help="Path to agy executable")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Model name for agy CLI")

    args = parser.parse_args()

    if args.worker:
        if not args.probe_dir or not args.result_file or not args.token:
            print("Error: --worker requires --probe-dir, --result-file, and --token", file=sys.stderr)
            return 2
        return run_worker(args)
    else:
        return run_controller(args)


if __name__ == "__main__":
    sys.exit(main())
