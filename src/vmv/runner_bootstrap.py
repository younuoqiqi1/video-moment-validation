"""Refresh the isolated runner checkout before each launchd poll."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

RUNNER_REF = "refs/heads/feat/local-task-runner:refs/remotes/origin/feat/local-task-runner"
MAIN_REF = "refs/heads/main:refs/remotes/origin/main"
TASK_REF = "refs/heads/feat/stage1-media-import:refs/remotes/origin/feat/stage1-media-import"


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
        return 1
    env = os.environ.copy()
    env["PYTHONPATH"] = str(code_root / "src")
    try:
        return subprocess.run(
            [sys.executable, "-m", "vmv", "runner", "once", "--repo", str(repo)],
            cwd=repo, env=env, timeout=660,
        ).returncode
    except subprocess.TimeoutExpired:
        print("[接单服务] 本轮超过 11 分钟，请核查任务状态与子进程", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
