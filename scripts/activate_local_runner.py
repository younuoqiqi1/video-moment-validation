"""One-time Mac activation; kept outside the user's working tree."""

import platform
import subprocess
import sys
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=45
    )
    if result.returncode:
        raise RuntimeError(f"git {args[0]} 失败（退出码 {result.returncode}）")
    return result.stdout.strip()


def activate(repo: Path) -> str:
    if platform.system() != "Darwin":
        raise RuntimeError("此安装入口只能在用户 Mac 上执行")
    repo = repo.resolve()
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise RuntimeError("请从项目 Git 根目录执行，未更改现有工作区")
    runner_dir = repo / ".vmv-runner"
    code_root = runner_dir / "code"
    runner_dir.mkdir(exist_ok=True)
    git(repo, "fetch", "origin",
        "+refs/heads/main:refs/remotes/origin/main",
        "+refs/heads/feat/local-task-runner:refs/remotes/origin/feat/local-task-runner",
        "+refs/heads/feat/stage1-media-import:refs/remotes/origin/feat/stage1-media-import")
    sha = git(repo, "rev-parse", "origin/feat/local-task-runner")
    if not code_root.exists():
        git(repo, "worktree", "add", "--detach", str(code_root), sha)
    elif not (code_root / ".git").is_file():
        raise RuntimeError("独立代码目录已存在且并非本项目的 worktree，未覆盖")
    else:
        repo_common = (repo / git(repo, "rev-parse", "--git-common-dir")).resolve()
        code_common = (code_root / git(code_root, "rev-parse", "--git-common-dir")).resolve()
        if repo_common != code_common or Path(git(code_root, "rev-parse", "--show-toplevel")).resolve() != code_root:
            raise RuntimeError("独立代码目录不属于当前项目，未覆盖")
        if git(code_root, "status", "--porcelain"):
            raise RuntimeError("独立代码目录有未提交改动，未覆盖")
        if git(code_root, "rev-parse", "HEAD") != sha:
            git(code_root, "switch", "--detach", sha)

    sys.path.insert(0, str(code_root / "src"))
    from vmv.runner_bootstrap import refresh_runner
    from vmv.runner_service import install_service

    sha = refresh_runner(repo, code_root)
    python = repo / ".venv" / "bin" / "python"
    if not python.is_file():
        raise RuntimeError("项目虚拟环境 .venv/bin/python 不存在，未更改后台服务")
    success, message = install_service(
        repo_root=repo, python_bin=str(python), interval_sec=120, code_root=code_root
    )
    if not success:
        raise RuntimeError(message)
    return f"{message}；代码版本 {sha[:12]}。请查看 .vmv-runner/runner.log 的新记录。"


if __name__ == "__main__":
    try:
        print(activate(Path.cwd()))
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
