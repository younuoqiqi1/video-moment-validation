"""Refresh the isolated runner checkout before each launchd poll."""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RUNNER_REF = "refs/heads/feat/local-task-runner:refs/remotes/origin/feat/local-task-runner"
MAIN_REF = "refs/heads/main:refs/remotes/origin/main"
TASK_REF = "refs/heads/feat/stage1-media-import:refs/remotes/origin/feat/stage1-media-import"


def report_coordination(repo: Path, event: str, sha: str | None = None, exit_code: int = 0) -> bool:
    """Send only fixed status fields; never upload paths, errors or CLI output."""
    from vmv.runner import LocalTaskRunner
    runner = LocalTaskRunner(repo)
    version = sha[:12] if sha and re.fullmatch(r"[0-9a-f]{40}", sha) else "unknown"
    messages = {
        "installed": "后台服务已安装；仍需轮询回执证明程序运行。",
        "poll_ready": "轮询已启动，正在核对已授权任务；尚不能据此认定 AGY 已开工。",
        "refresh_failed": "接单程序更新失败；未派发任务。请查看本机 runner 日志。",
        "worker_failed": "任务轮询异常退出；请查看本机 runner 日志。",
        "worker_timeout": "任务轮询超时；请核对本机任务状态与 AGY 进程。",
    }
    if event == "poll_result":
        try:
            states = runner.load_state()
            task = states.get("stage1-preview-followup:r1") or states.get("stage1-preview-followup:pr5")
            allowed = {"ready", "running", "awaiting_review", "blocked", "interrupted", "quota_wait", "done", "discovered_readonly"}
            status = task.status if task and task.status in allowed else "unknown"
            reason = ""
            if task and status in {"blocked", "interrupted"}:
                error = task.last_error or ""
                if "完整清单目录缺失" in error:
                    reason = "；原因类别：本机素材或清单缺失"
                elif "工作区" in error or "worktree" in error:
                    reason = "；原因类别：工作区准备失败"
                elif "CLI" in error:
                    reason = "；原因类别：AGY CLI 执行失败"
                else:
                    reason = "；原因类别：需查看本机日志"
            message = f"PR #5 任务状态：{status}{reason}；本轮退出码：{int(exit_code)}。仅为程序回报，尚未完成 Codex 独立验收。"
        except RuntimeError:
            message = "任务状态文件无法读取；程序停止派发，请检查本机状态文件。"
    else:
        message = messages[event]
    signature = f"{version}:{message}"
    receipt_path = runner.runner_dir / "coordination-receipts.json"
    try:
        receipts = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        if not isinstance(receipts, dict):
            receipts = {}
    except (OSError, ValueError):
        receipts = {}
    if receipts.get(event) == signature:
        return True
    body = (
        "AGY 协同回执\n\n"
        f"时间（UTC）：{datetime.now(timezone.utc).isoformat()}\n"
        f"接单代码版本：{version}\n\n{message}"
    )
    if not runner.post_pr_comment(3, body):
        print("[协同回执] GitHub 回报失败；请检查本机 GitHub 登录，未记录为已发送。", flush=True)
        return False
    receipts[event] = signature
    try:
        temporary = receipt_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(receipts, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, receipt_path)
    except OSError:
        print("[协同回执] 已发送，但本机去重记录无法保存。", flush=True)
    return True


def git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *args], capture_output=True, text=True, timeout=45
    )
    if result.returncode:
        raise RuntimeError(f"git {args[0]} 失败（退出码 {result.returncode}）")
    return result.stdout.strip()


def same_repository(repo: Path, checkout: Path) -> bool:
    try:
        primary = (repo / git(repo, "rev-parse", "--git-common-dir")).resolve()
        secondary = (checkout / git(checkout, "rev-parse", "--git-common-dir")).resolve()
        return primary == secondary and Path(git(checkout, "rev-parse", "--show-toplevel")).resolve() == checkout.resolve()
    except (OSError, RuntimeError):
        return False


def refresh_runner(repo: Path, code_root: Path) -> str:
    """Fail closed if the isolated checkout was modified or replaced."""
    if not same_repository(repo, code_root):
        raise RuntimeError("独立代码目录不是当前项目的 Git worktree，已停止")
    if git(code_root, "status", "--porcelain"):
        raise RuntimeError("独立代码目录有未提交改动，已停止，未覆盖任何文件")
    git(repo, "fetch", "origin", "+" + RUNNER_REF, "+" + MAIN_REF, "+" + TASK_REF)
    expected = git(repo, "rev-parse", "origin/feat/local-task-runner")
    current = git(code_root, "rev-parse", "HEAD")
    if current != expected:
        git(code_root, "switch", "--detach", expected)
    return expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="刷新隔离代码并执行一次本地任务轮询")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--code-root", required=True, type=Path)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    code_root = args.code_root.resolve()
    try:
        sha = refresh_runner(repo, code_root)
        print(f"[接单服务] 已更新隔离代码到 {sha[:12]}，开始检查已授权任务", flush=True)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"[接单服务] 更新失败：{exc}", flush=True)
        report_coordination(repo, "refresh_failed")
        return 1
    report_coordination(repo, "poll_ready", sha)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(code_root / "src")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "vmv", "runner", "once", "--repo", str(repo)],
            cwd=repo, env=env, timeout=660,
        )
        report_coordination(repo, "poll_result", sha, result.returncode)
        return result.returncode
    except subprocess.TimeoutExpired:
        print("[接单服务] 本轮超过 11 分钟，请核查任务状态与子进程", flush=True)
        report_coordination(repo, "worker_timeout", sha)
        return 1
    except OSError:
        report_coordination(repo, "worker_failed", sha)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
