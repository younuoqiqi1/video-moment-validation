"""Exercise the actual Git worktree refresh with a narrow fetch configuration."""

import subprocess
from pathlib import Path

import pytest

from vmv.runner_bootstrap import refresh_runner


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def test_refreshes_only_isolated_code_and_preserves_working_tree(tmp_path: Path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    repo = tmp_path / "project"
    subprocess.run(["git", "clone", str(bare), str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "sentinel").write_text("original")
    git(repo, "add", "sentinel")
    git(repo, "commit", "-m", "main")
    git(repo, "branch", "-M", "main")
    git(repo, "push", "-u", "origin", "main")
    git(repo, "branch", "feat/stage1-media-import")
    git(repo, "push", "origin", "feat/stage1-media-import")
    git(repo, "switch", "-c", "feat/local-task-runner")
    (repo / "runner-version").write_text("v1")
    git(repo, "add", "runner-version")
    git(repo, "commit", "-m", "v1")
    git(repo, "push", "-u", "origin", "feat/local-task-runner")
    git(repo, "switch", "main")
    git(repo, "config", "--replace-all", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main")
    code = repo / ".vmv-runner" / "code"
    git(repo, "worktree", "add", "--detach", str(code), "origin/feat/local-task-runner")
    (repo / "sentinel").write_text("user work")

    assert refresh_runner(repo, code) == git(code, "rev-parse", "HEAD")
    git(repo, "switch", "feat/local-task-runner")
    (repo / "runner-version").write_text("v2")
    git(repo, "add", "runner-version")
    git(repo, "commit", "-m", "v2")
    git(repo, "push", "origin", "feat/local-task-runner")
    git(repo, "switch", "main")

    assert refresh_runner(repo, code) == git(repo, "rev-parse", "origin/feat/local-task-runner")
    assert (code / "runner-version").read_text() == "v2"
    assert (repo / "sentinel").read_text() == "user work"
    (code / "runner-version").write_text("local change")
    with pytest.raises(RuntimeError, match="未提交改动"):
        refresh_runner(repo, code)
    assert (code / "runner-version").read_text() == "local change"
