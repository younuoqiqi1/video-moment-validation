"""Unit tests for local AGY task runner with strict Git isolation and R1-R3 verifications."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from vmv.runner import LocalTaskRunner, RunnerLock, TaskState, TaskItem


def create_git_repo(path: Path) -> Path:
    """Helper to initialize a real git repository with initial commit."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "Test Runner"], cwd=str(path), check=True)
    readme = path / "README.md"
    readme.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), check=True, capture_output=True)
    return path


def test_runner_lock_mutual_exclusion(tmp_path: Path):
    """Verify second lock attempt fails while first lock is held."""
    lock_file = tmp_path / "test.lock"
    lock1 = RunnerLock(lock_file)
    lock2 = RunnerLock(lock_file)

    assert lock1.acquire() is True
    assert lock2.acquire() is False

    lock1.release()
    assert lock2.acquire() is True
    lock2.release()


# ==============================================================================
# R1 Tests: Worktree & Branch Protection (Real Git Tests)
# ==============================================================================

def test_r1_prepare_worktree_preserves_existing_branch_commits(tmp_path: Path):
    """R1: Existing branch with extra commits must NOT be reset by worktree add (no -B)."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    # Create a feature branch with an extra commit
    subprocess.run(["git", "branch", "task/stage0-fixes"], cwd=str(repo), check=True)
    subprocess.run(["git", "checkout", "task/stage0-fixes"], cwd=str(repo), check=True, capture_output=True)
    extra_file = repo / "extra_work.txt"
    extra_file.write_text("Unique work that must not be lost\n", encoding="utf-8")
    subprocess.run(["git", "add", "extra_work.txt"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Extra feature commit"], cwd=str(repo), check=True, capture_output=True)

    res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True)
    extra_commit_sha = res.stdout.strip()

    # Switch main checkout back to main/master
    main_branch = "master" if subprocess.run(["git", "rev-parse", "--verify", "master"], cwd=str(repo), capture_output=True).returncode == 0 else "main"
    subprocess.run(["git", "checkout", main_branch], cwd=str(repo), check=True, capture_output=True)

    # Call prepare_worktree_for_task
    task = TaskItem(id="stage0-fixes", revision=1, path="tasks/stage0.md", authorized=True)
    wt_dir, err = runner.prepare_worktree_for_task(task, branch_name="task/stage0-fixes")

    assert err is None
    assert wt_dir is not None
    assert wt_dir.exists()

    # Verify the worktree HEAD has the exact extra commit SHA (NOT reset to main)
    wt_head = runner._get_worktree_head_sha(wt_dir)
    assert wt_head == extra_commit_sha
    assert (wt_dir / "extra_work.txt").exists()


def test_r1_prepare_worktree_preserves_unregistered_directory_sentinel(tmp_path: Path):
    """R1: Unregistered directory with sentinel files must be preserved, NOT deleted with rmtree."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    # Manually create a directory at the expected worktree path that is NOT registered in git
    worktrees_dir = repo / ".vmv-runner" / "worktrees"
    target_dir = worktrees_dir / "my-task"
    target_dir.mkdir(parents=True)
    sentinel_file = target_dir / "valuable_sentinel.txt"
    sentinel_file.write_text("DO NOT DELETE THIS\n", encoding="utf-8")

    task = TaskItem(id="my-task", revision=1, path="tasks/t.md", authorized=True)
    wt_dir, err = runner.prepare_worktree_for_task(task)

    assert wt_dir is None
    assert err is not None
    assert "未知目录保留" in err
    # Sentinel file MUST still exist!
    assert sentinel_file.exists()
    assert sentinel_file.read_text(encoding="utf-8") == "DO NOT DELETE THIS\n"


def test_r1_prepare_worktree_preserves_dirty_main_checkout(tmp_path: Path):
    """R1: Creating a worktree must not touch uncommitted dirty files in the main checkout."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    # Create uncommitted dirty file in main checkout
    dirty_file = repo / "dirty_user_edit.txt"
    dirty_file.write_text("Uncommitted work in main\n", encoding="utf-8")

    task = TaskItem(id="new-task", revision=1, path="tasks/new.md", authorized=True)
    wt_dir, err = runner.prepare_worktree_for_task(task)

    assert err is None
    assert wt_dir is not None
    # Main checkout dirty file must be intact
    assert dirty_file.exists()
    assert dirty_file.read_text(encoding="utf-8") == "Uncommitted work in main\n"


def test_r1_prepare_worktree_rejects_occupied_branch(tmp_path: Path):
    """R1: If a branch is currently checked out in main or another worktree, reject with error."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    # Currently checked out branch in main repo
    res = subprocess.run(["git", "branch", "--show-current"], cwd=str(repo), capture_output=True, text=True)
    current_branch = res.stdout.strip()

    task = TaskItem(id="occupied-task", revision=1, path="tasks/o.md", authorized=True)
    wt_dir, err = runner.prepare_worktree_for_task(task, branch_name=current_branch)

    assert wt_dir is None
    assert err is not None
    assert "已被其它工作区占用" in err


def test_r1_non_git_root_blocked_without_downgrade(tmp_path: Path):
    """R1: Non-git root must be rejected immediately without degrading to normal directory."""
    non_git = tmp_path / "no_git_here"
    non_git.mkdir()
    runner = LocalTaskRunner(repo_root=non_git, runner_dir=non_git / ".vmv-runner")

    task = TaskItem(id="task-1", revision=1, path="tasks/t.md", authorized=True)
    wt_dir, err = runner.prepare_worktree_for_task(task)

    assert wt_dir is None
    assert err == "根目录不是 Git 仓库"


# ==============================================================================
# R2 Tests: Remote Truth & Fetch Handling
# ==============================================================================

def test_r2_fetch_failure_halts_and_preserves_ready_task(tmp_path: Path):
    """R2: Network or fetch failure must return 1 immediately and never invoke CLI."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    states = {
        "ready-task:r1": TaskState(
            task_id="ready-task",
            revision=1,
            status="ready",
        )
    }
    runner.save_state(states)

    with patch.object(runner, "fetch_remote_main", return_value=(False, "Connection timed out")):
        with patch.object(runner, "execute_cli_task") as mock_exec:
            code = runner.run_once()
            assert code == 1
            mock_exec.assert_not_called()

            # State must be preserved
            loaded = runner.load_state()
            assert loaded["ready-task:r1"].status == "ready"


def test_r2_remote_revocation_blocks_ready_task(tmp_path: Path):
    """R2: If a task was ready locally but remote queue revoked authorization, mark blocked."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    states = {
        "revoked-task:r1": TaskState(
            task_id="revoked-task",
            revision=1,
            status="ready",
        )
    }
    runner.save_state(states)

    # Remote queue has authorized=False or does not contain revoked-task
    mock_queue = [
        TaskItem(id="revoked-task", revision=1, path="tasks/r.md", authorized=False)
    ]

    with patch.object(runner, "fetch_remote_main", return_value=(True, "")):
        with patch.object(runner, "get_origin_main_sha", return_value="fake_remote_sha"):
            with patch.object(runner, "load_queue_tasks", return_value=(mock_queue, None)):
                with patch.object(runner, "execute_cli_task") as mock_exec:
                    code = runner.run_once()
                    assert code == 0
                    mock_exec.assert_not_called()

                    loaded = runner.load_state()
                    assert loaded["revoked-task:r1"].status == "blocked"
                    assert "撤销" in (loaded["revoked-task:r1"].last_error or "")


def test_r2_corrupt_remote_queue_diagnosed_and_halts(tmp_path: Path):
    """R2: Corrupted remote queue must halt and not execute local tasks."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    with patch.object(runner, "fetch_remote_main", return_value=(True, "")):
        with patch.object(runner, "get_origin_main_sha", return_value="fake_remote_sha"):
            with patch.object(
                runner, "load_queue_tasks", return_value=(None, "JSON 格式损坏: invalid character")
            ):
                with patch.object(runner, "execute_cli_task") as mock_exec:
                    code = runner.run_once()
                    assert code == 1
                    mock_exec.assert_not_called()


# ==============================================================================
# R3 Tests: PR Verification & Delivery Consistency
# ==============================================================================

def test_r3_delivery_blocked_if_no_pr(tmp_path: Path):
    """R3: CLI exit 0 without open non-draft PR must be blocked, not awaiting_review."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    st = TaskState(task_id="test-task", revision=1, status="ready")
    worktree_dir = tmp_path / "fake_wt"
    worktree_dir.mkdir()

    with patch.object(runner, "_get_worktree_head_sha", return_value="wt_head_123"):
        with patch.object(runner, "get_pr_info_for_branch", return_value=None):
            ok, err = runner._verify_delivery(st, "task/test-task", worktree_dir)
            assert ok is False
            assert "未找到关联的有效 GitHub PR" in (err or "")


def test_r3_delivery_blocked_if_pr_is_draft_or_closed(tmp_path: Path):
    """R3: Draft or closed PR must be blocked."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    st = TaskState(task_id="test-task", revision=1, status="ready")
    worktree_dir = tmp_path / "fake_wt"
    worktree_dir.mkdir()

    draft_pr = {
        "number": 10,
        "state": "open",
        "draft": True,
        "head_ref": "task/test-task",
        "head_sha": "wt_head_123",
    }
    with patch.object(runner, "_get_worktree_head_sha", return_value="wt_head_123"):
        with patch.object(runner, "get_pr_info_for_branch", return_value=draft_pr):
            ok, err = runner._verify_delivery(st, "task/test-task", worktree_dir)
            assert ok is False
            assert "草稿" in (err or "")


def test_r3_delivery_blocked_if_worktree_head_differs_from_remote_or_pr(tmp_path: Path):
    """R3: Worktree HEAD, remote branch SHA, and PR head SHA must be strictly equal."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    st = TaskState(task_id="test-task", revision=1, status="ready")
    worktree_dir = tmp_path / "fake_wt"
    worktree_dir.mkdir()

    # PR head_sha matches worktree, but remote branch has not been pushed yet (or differs)
    open_pr = {
        "number": 10,
        "state": "open",
        "draft": False,
        "head_ref": "task/test-task",
        "head_sha": "wt_head_123",
    }
    with patch.object(runner, "_get_worktree_head_sha", return_value="wt_head_123"):
        with patch.object(runner, "get_pr_info_for_branch", return_value=open_pr):
            with patch("subprocess.run") as mock_sub:
                # Remote git rev-parse returns older commit
                mock_sub.return_value = MagicMock(returncode=0, stdout="old_remote_sha\n")
                ok, err = runner._verify_delivery(st, "task/test-task", worktree_dir)
                assert ok is False
                assert "未推送到远端或与 PR head 不一致" in (err or "")


def test_r3_delivery_succeeds_when_all_three_shas_match(tmp_path: Path):
    """R3: Worktree HEAD == remote branch SHA == PR head SHA enters awaiting_review."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    st = TaskState(task_id="test-task", revision=1, status="ready")
    worktree_dir = tmp_path / "fake_wt"
    worktree_dir.mkdir()

    target_sha = "unanimous_sha_7777777"
    open_pr = {
        "number": 15,
        "state": "open",
        "draft": False,
        "head_ref": "task/test-task",
        "head_sha": target_sha,
    }
    with patch.object(runner, "_get_worktree_head_sha", return_value=target_sha):
        with patch.object(runner, "get_pr_info_for_branch", return_value=open_pr):
            with patch("subprocess.run") as mock_sub:
                mock_sub.return_value = MagicMock(returncode=0, stdout=f"{target_sha}\n")
                ok, err = runner._verify_delivery(st, "task/test-task", worktree_dir)
                assert ok is True
                assert err is None
                assert st.pr_number == 15
                assert st.head_sha == target_sha
                assert st.head_branch == "task/test-task"


def test_r3_parse_review_conclusion_strict():
    """R3: Conclusion parser strictly accepts only four tokens without false-positives."""
    assert LocalTaskRunner._parse_review_conclusion("结论：pass") == "pass"
    assert LocalTaskRunner._parse_review_conclusion("结论：pass_with_notes") == "pass_with_notes"
    assert LocalTaskRunner._parse_review_conclusion("- 结论：request_changes (需修改)") == "request_changes"
    assert LocalTaskRunner._parse_review_conclusion("结论：blocked") == "blocked"

    # Strict rejection of false positives
    assert LocalTaskRunner._parse_review_conclusion("结论：not_pass_with_notes") == "unknown"
    assert LocalTaskRunner._parse_review_conclusion("结论：not pass") == "unknown"
    assert LocalTaskRunner._parse_review_conclusion("结论：fail") == "unknown"


def test_r3_on_started_exception_kills_child_process(tmp_path: Path):
    """R3: Exception during on_started terminates the child process immediately."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")
    task = TaskItem(id="t", revision=1, path="t.md")

    mock_proc = MagicMock()
    mock_proc.pid = 99999
    with patch("shutil.which", return_value="/bin/echo"):
        with patch("subprocess.Popen", return_value=mock_proc):
            def failing_callback(pid: int):
                raise RuntimeError("Failed to persist PID to disk")

            code, out, pid = runner.execute_cli_task(task, "prompt", on_started=failing_callback)
            assert code == 1
            assert "启动回调异常" in out
            mock_proc.kill.assert_called_once()


def test_r3_sync_existing_deliveries_attaches_stage0_pr_branch(tmp_path: Path):
    """R3: sync_existing_deliveries maps PR #2 to task/stage0-review-fix and request_changes to awaiting_review."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    reviews_dir = repo / "reviews"
    reviews_dir.mkdir(parents=True)
    review_file = reviews_dir / "pr-2-rev_sha_123.md"
    review_file.write_text("结论：request_changes\n待修改", encoding="utf-8")

    fake_pr = {
        "number": 2,
        "state": "open",
        "draft": False,
        "head_ref": "task/stage0-review-fix",
        "head_sha": "rev_sha_123",
    }

    states = {}
    with patch.object(runner, "get_pr_info_for_branch", return_value=fake_pr):
        runner.sync_existing_deliveries(states)

        st = states.get("stage0-fixes:r1")
        assert st is not None
        assert st.pr_number == 2
        assert st.head_branch == "task/stage0-review-fix"
        assert st.head_sha == "rev_sha_123"
        assert st.status == "awaiting_review"  # Registered as awaiting_review to allow dispatching


# ==============================================================================
# General Flow & Deduplication Tests
# ==============================================================================

def test_runner_detects_interrupted_process(tmp_path: Path):
    """Verify dead PID in running state is marked as interrupted."""
    repo = create_git_repo(tmp_path / "main_repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")
    states = {
        "crashed-task:r1": TaskState(
            task_id="crashed-task",
            revision=1,
            status="running",
            pid=99999999,
        )
    }
    runner.save_state(states)

    with patch.object(runner, "fetch_remote_main", return_value=(True, "")):
        with patch.object(runner, "get_origin_main_sha", return_value="fake_sha"):
            with patch.object(runner, "load_queue_tasks", return_value=([], None)):
                with patch.object(runner, "check_process_alive", return_value=False):
                    exit_code = runner.run_once()
                    assert exit_code == 0
                    loaded = runner.load_state()
                    assert loaded["crashed-task:r1"].status == "interrupted"


def test_runner_matches_passing_review_and_marks_done(tmp_path: Path):
    """Verify awaiting_review task is marked done when matching passing review file is present."""
    repo = create_git_repo(tmp_path / "main_repo")
    reviews_dir = repo / "reviews"
    reviews_dir.mkdir(parents=True)
    review_file = reviews_dir / "pr-2-abcdef.md"
    review_file.write_text("结论：pass_with_notes (通过)\n任务: my-task", encoding="utf-8")

    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")
    states = {
        "my-task:r1": TaskState(
            task_id="my-task",
            revision=1,
            status="awaiting_review",
            pr_number=2,
            head_sha="abcdef",
        )
    }
    runner.save_state(states)

    mock_queue = [TaskItem(id="my-task", revision=1, path="tasks/t.md", authorized=True)]

    with patch.object(runner, "fetch_remote_main", return_value=(True, "")):
        with patch.object(runner, "get_origin_main_sha", return_value="fake_sha"):
            with patch.object(runner, "load_queue_tasks", return_value=(mock_queue, None)):
                exit_code = runner.run_once()
                assert exit_code == 0
                loaded = runner.load_state()
                assert loaded["my-task:r1"].status == "done"
                assert loaded["my-task:r1"].review_path is not None


def test_runner_two_round_request_changes_deduplication(tmp_path: Path):
    """Verify request_changes for the same commit is only dispatched once across cycles."""
    repo = create_git_repo(tmp_path / "main_repo")
    reviews_dir = repo / "reviews"
    reviews_dir.mkdir(parents=True)
    review_file = reviews_dir / "pr-2-target_sha.md"
    review_file.write_text("结论：request_changes\n必须修正", encoding="utf-8")

    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")
    states = {
        "fix-task:r1": TaskState(
            task_id="fix-task",
            revision=1,
            status="awaiting_review",
            pr_number=2,
            head_sha="target_sha",
            attempt=1,
        )
    }
    runner.save_state(states)

    mock_queue = [TaskItem(id="fix-task", revision=1, path="tasks/f.md", authorized=True)]

    with patch.object(runner, "fetch_remote_main", return_value=(True, "")):
        with patch.object(runner, "get_origin_main_sha", return_value="fake_sha"):
            with patch.object(runner, "load_queue_tasks", return_value=(mock_queue, None)):
                with patch.object(runner, "prepare_worktree_for_task", return_value=(tmp_path, None)):
                    with patch.object(runner, "execute_cli_task", return_value=(0, "ok", 4321)) as mock_exec:
                        # Worktree HEAD remains target_sha (simulating no new commit created)
                        with patch.object(runner, "_get_worktree_head_sha", return_value="target_sha"):
                            res1 = runner.run_once()
                            assert res1 == 1  # Blocked due to unchanged HEAD
                            assert mock_exec.call_count == 1
                            loaded1 = runner.load_state()
                            assert "2:target_sha" in loaded1["fix-task:r1"].dispatched_reviews
                            assert loaded1["fix-task:r1"].status == "blocked"

                            # Round 2: Re-run run_once; even if review is still request_changes, CLI must NOT be dispatched again!
                            res2 = runner.run_once()
                            assert res2 == 0
                            assert mock_exec.call_count == 1  # Still 1!


def test_discover_pr_branch_tasks(tmp_path: Path):
    """Verify discover_pr_branch_tasks extracts PR branch tasks and titles correctly."""
    repo = create_git_repo(tmp_path / "repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    # 1. When ref does not exist
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=1, stdout="", stderr="")
        assert runner.discover_pr_branch_tasks() == []

    # 2. When ref exists and has task file
    def mock_sub_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout="20cd362cd88df183b062991a14f2ac50c9b6703f\n", stderr="")
        elif "git" in cmd and "show" in cmd:
            content = "# AGY 任务：阶段 1 镜头清单核对补充\n\n详情内容..."
            return MagicMock(returncode=0, stdout=content, stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_sub_run):
        discovered = runner.discover_pr_branch_tasks()
        assert len(discovered) == 1
        d = discovered[0]
        assert d["task_id"] == "stage1-preview-followup"
        assert d["pr_number"] == 5
        assert d["branch"] == "feat/stage1-media-import"
        assert d["remote_sha"] == "20cd362cd88df183b062991a14f2ac50c9b6703f"
        assert d["task_path"] == "tasks/stage1-preview-followup.md"
        assert d["title"] == "AGY 任务：阶段 1 镜头清单核对补充"


def test_run_once_pr_branch_task_discovery_and_readonly_safety_gate(tmp_path: Path):
    """Only the pinned, authorized PR #5 task is dispatched, once, in an isolated worktree."""
    repo = create_git_repo(tmp_path / "repo")
    runner = LocalTaskRunner(repo_root=repo, runner_dir=repo / ".vmv-runner")

    mock_pr_task = [{
        "task_id": "stage1-preview-followup",
        "pr_number": 5,
        "branch": "feat/stage1-media-import",
        "remote_sha": "20cd362cd88df183b062991a14f2ac50c9b6703f",
        "task_path": "tasks/stage1-preview-followup.md",
        "title": "AGY 任务：阶段 1 镜头清单核对补充",
    }]
    authorized_item = TaskItem(
        id="stage1-preview-followup",
        revision=1,
        path="tasks/stage1-preview-followup.md",
        authorized=True,
    )

    with patch.object(runner, "fetch_remote_main", return_value=(True, "")):
        with patch.object(runner, "get_origin_main_sha", return_value="main_sha"):
            with patch.object(runner, "load_queue_tasks", return_value=([], None)):
                with patch.object(runner, "discover_pr_branch_tasks", return_value=mock_pr_task):
                    with patch.object(
                        runner,
                        "resolve_authorized_pr_task",
                        return_value=(authorized_item, "已授权任务内容", None),
                    ):
                        with patch.object(runner, "prepare_worktree_for_task", return_value=(tmp_path, None)):
                            with patch.object(runner, "get_remote_branch_sha", return_value=mock_pr_task[0]["remote_sha"]):
                                with patch.object(
                                    runner,
                                    "_get_worktree_head_sha",
                                    side_effect=[mock_pr_task[0]["remote_sha"], "new_code_sha"],
                                ):
                                    with patch.object(runner, "_verify_delivery", return_value=(True, None)):
                                        with patch.object(
                                            runner, "execute_cli_task", return_value=(0, "已完成", 4321)
                                        ) as mock_exec:
                                            with patch.object(runner, "find_matching_review", return_value=(None, None)):
                                                # First poll starts the task and records delivery for review.
                                                exit_code = runner.run_once()
                                                assert exit_code == 0
                                                assert mock_exec.call_count == 1
                                                assert mock_exec.call_args.args[0] == authorized_item
                                                assert "已授权任务内容" in mock_exec.call_args.args[1]
                                                loaded = runner.load_state()
                                                task_key = "stage1-preview-followup:r1"
                                                assert loaded[task_key].status == "awaiting_review"
                                                assert loaded[task_key].pr_number == 5
                                                assert loaded[task_key].head_sha == mock_pr_task[0]["remote_sha"]
                                                assert loaded[task_key].attempt == 1

                                                # With no matching review yet, the next poll waits and never repeats work.
                                                exit_code2 = runner.run_once()
                                                assert exit_code2 == 0
                                                assert mock_exec.call_count == 1

    # A PR task with any different identity/path is rejected before reading or dispatching it.
    item, prompt, err = runner.resolve_authorized_pr_task({
        **mock_pr_task[0],
        "task_path": "tasks/other-task.md",
    })
    assert item is None
    assert prompt is None
    assert "不在明确授权白名单" in (err or "")


