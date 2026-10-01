"""Exercise the actual Git worktree refresh with a narrow fetch configuration."""

import subprocess
from pathlib import Path

import pytest

from vmv.runner_bootstrap import refresh_runner


def test_poll_failure_reports_safe_status_and_deduplicates(tmp_path, monkeypatch):
    from vmv import runner_bootstrap
    from vmv.runner import LocalTaskRunner
    comments = []
    monkeypatch.setattr(LocalTaskRunner, "post_pr_comment", lambda self, pr, body: comments.append((pr, body)) or True)
    def fail_refresh(*args):
        raise RuntimeError("token=secret-personal-value /Users/private-owner/project")
    monkeypatch.setattr(runner_bootstrap, "refresh_runner", fail_refresh)
    args = ["--repo", str(tmp_path), "--code-root", str(tmp_path / "code")]
    assert runner_bootstrap.main(args) == 1
    assert runner_bootstrap.main(args) == 1
    assert len(comments) == 1
    assert comments[0][0] == 3
    assert "AGY 协同回执" in comments[0][1]
    assert "更新失败" in comments[0][1]
    assert "secret-personal-value" not in comments[0][1]
    assert "/Users/" not in comments[0][1]


def test_poll_reports_new_code_and_blocked_task_without_uploading_logs(tmp_path, monkeypatch):
    from vmv import runner_bootstrap
    from vmv.runner import LocalTaskRunner, TaskState
    comments = []
    monkeypatch.setattr(LocalTaskRunner, "post_pr_comment", lambda self, pr, body: comments.append((pr, body)) or True)
    monkeypatch.setattr(runner_bootstrap, "refresh_runner", lambda *args: "a" * 40)
    runner = LocalTaskRunner(tmp_path)
    runner.save_state({"stage1-preview-followup:r1": TaskState(
        task_id="stage1-preview-followup", revision=1, status="blocked", pr_number=5,
        last_error="工作区准备失败: 本机视频或阶段 1 完整清单目录缺失 token=private",
    )})
    monkeypatch.setattr(runner_bootstrap.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1))
    args = ["--repo", str(tmp_path), "--code-root", str(tmp_path / "code")]
    assert runner_bootstrap.main(args) == 1
    assert runner_bootstrap.main(args) == 1
    assert len(comments) == 2
    assert "轮询已启动" in comments[0][1]
    assert "blocked" in comments[1][1]
    assert "本机素材或清单缺失" in comments[1][1]
    assert "private" not in comments[1][1]
    assert "AGY 已开始" not in comments[0][1]


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
