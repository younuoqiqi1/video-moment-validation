"""Unit tests for local AGY task runner."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from vmv.runner import LocalTaskRunner, RunnerLock, TaskState, TaskItem


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


def test_runner_unauthorized_task_ignored(tmp_path: Path):
    """Verify unauthorized tasks in queue.json are not executed."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    queue_file = tasks_dir / "queue.json"
    queue_file.write_text(
        json.dumps({
            "version": 1,
            "tasks": [
                {"id": "unauth-task", "revision": 1, "path": "tasks/fake.md", "authorized": False}
            ]
        }),
        encoding="utf-8"
    )

    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    with patch.object(runner, "execute_cli_task") as mock_exec:
        exit_code = runner.run_once()
        assert exit_code == 0
        mock_exec.assert_not_called()


def test_runner_executes_authorized_task(tmp_path: Path):
    """Verify authorized ready task is executed and transitions to awaiting_review."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "valid_task.md"
    task_file.write_text("Hello AGY task", encoding="utf-8")

    queue_file = tasks_dir / "queue.json"
    queue_file.write_text(
        json.dumps({
            "version": 1,
            "tasks": [
                {"id": "auth-task", "revision": 1, "path": "tasks/valid_task.md", "authorized": True}
            ]
        }),
        encoding="utf-8"
    )

    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    with patch.object(runner, "execute_cli_task", return_value=(0, "Success output")) as mock_exec:
        exit_code = runner.run_once()
        assert exit_code == 0
        mock_exec.assert_called_once()

        states = runner.load_state()
        st = states.get("auth-task:r1")
        assert st is not None
        assert st.status == "awaiting_review"
        assert st.attempt == 1


def test_runner_handles_cli_failure_as_blocked(tmp_path: Path):
    """Verify non-zero CLI exit sets status to blocked with error message."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "fail_task.md"
    task_file.write_text("Will fail", encoding="utf-8")

    queue_file = tasks_dir / "queue.json"
    queue_file.write_text(
        json.dumps({
            "version": 1,
            "tasks": [
                {"id": "fail-task", "revision": 1, "path": "tasks/fail_task.md", "authorized": True}
            ]
        }),
        encoding="utf-8"
    )

    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    with patch.object(runner, "execute_cli_task", return_value=(1, "API rate limit or syntax error")):
        exit_code = runner.run_once()
        assert exit_code == 1

        states = runner.load_state()
        st = states.get("fail-task:r1")
        assert st is not None
        assert st.status == "blocked"
        assert "CLI 执行失败" in (st.last_error or "")


def test_runner_detects_interrupted_process(tmp_path: Path):
    """Verify dead PID in running state is marked as interrupted."""
    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    states = {
        "crashed-task:r1": TaskState(
            task_id="crashed-task",
            revision=1,
            status="running",
            pid=99999999,  # Unlikely to be alive
        )
    }
    runner.save_state(states)

    with patch.object(runner, "check_process_alive", return_value=False):
        exit_code = runner.run_once()
        loaded = runner.load_state()
        assert loaded["crashed-task:r1"].status == "interrupted"


def test_runner_matches_passing_review_and_marks_done(tmp_path: Path):
    """Verify awaiting_review task is marked done when matching passing review file is present."""
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir(parents=True)
    review_file = reviews_dir / "pr-2-abcdef.md"
    review_file.write_text("结论：pass_with_notes (通过)\n任务: my-task", encoding="utf-8")

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    queue_file = tasks_dir / "queue.json"
    queue_file.write_text(
        json.dumps({
            "version": 1,
            "tasks": [
                {"id": "my-task", "revision": 1, "path": "tasks/t.md", "authorized": True}
            ]
        }),
        encoding="utf-8"
    )

    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
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

    exit_code = runner.run_once()
    assert exit_code == 0
    loaded = runner.load_state()
    assert loaded["my-task:r1"].status == "done"
    assert loaded["my-task:r1"].review_path is not None


def test_runner_mismatched_head_sha_review_does_not_pass(tmp_path: Path):
    """Verify awaiting_review task is NOT marked done if review file is for a different commit."""
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir(parents=True)
    # Review is for older commit "old123"
    review_file = reviews_dir / "pr-2-old123.md"
    review_file.write_text("结论：pass (通过)\n任务: my-task", encoding="utf-8")

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    queue_file = tasks_dir / "queue.json"
    queue_file.write_text(
        json.dumps({
            "version": 1,
            "tasks": [
                {"id": "my-task", "revision": 1, "path": "tasks/t.md", "authorized": True}
            ]
        }),
        encoding="utf-8"
    )

    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    states = {
        "my-task:r1": TaskState(
            task_id="my-task",
            revision=1,
            status="awaiting_review",
            pr_number=2,
            head_sha="new456",  # Different from old123
        )
    }
    runner.save_state(states)

    exit_code = runner.run_once()
    assert exit_code == 0
    loaded = runner.load_state()
    assert loaded["my-task:r1"].status == "awaiting_review"  # Not done!


def test_runner_request_changes_review_does_not_mark_done(tmp_path: Path):
    """Verify review with request_changes does not mark task as done."""
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir(parents=True)
    review_file = reviews_dir / "pr-2-commit1.md"
    review_file.write_text("结论：request_changes\n必须修改", encoding="utf-8")

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    queue_file = tasks_dir / "queue.json"
    queue_file.write_text(
        json.dumps({
            "version": 1,
            "tasks": [
                {"id": "my-task", "revision": 1, "path": "tasks/t.md", "authorized": True}
            ]
        }),
        encoding="utf-8"
    )

    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    states = {
        "my-task:r1": TaskState(
            task_id="my-task",
            revision=1,
            status="awaiting_review",
            pr_number=2,
            head_sha="commit1",
        )
    }
    runner.save_state(states)

    with patch.object(runner, "execute_cli_task", return_value=(0, "mocked", 1234)):
        exit_code = runner.run_once()
        assert exit_code == 0
        loaded = runner.load_state()
        assert loaded["my-task:r1"].status == "awaiting_review"


def test_runner_done_task_not_reexecuted(tmp_path: Path):
    """Verify task already in done status is never re-executed."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "task.md"
    task_file.write_text("Do work", encoding="utf-8")

    queue_file = tasks_dir / "queue.json"
    queue_file.write_text(
        json.dumps({
            "version": 1,
            "tasks": [
                {"id": "done-task", "revision": 1, "path": "tasks/task.md", "authorized": True}
            ]
        }),
        encoding="utf-8"
    )

    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    states = {
        "done-task:r1": TaskState(
            task_id="done-task",
            revision=1,
            status="done",
        )
    }
    runner.save_state(states)

    with patch.object(runner, "execute_cli_task") as mock_exec:
        exit_code = runner.run_once()
        assert exit_code == 0
        mock_exec.assert_not_called()


def test_runner_shell_meta_passed_as_literal_argv(tmp_path: Path):
    """Verify prompt containing shell metacharacters is safely passed in argv list without shell=True."""
    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner", agy_bin="agy")
    task_item = TaskItem(id="test-task", revision=1, path="tasks/test.md", authorized=True)
    meta_prompt = 'echo "hello" && rm -rf / ; `whoami` $FOO'

    with patch("shutil.which", return_value="/usr/local/bin/agy"):
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 9999
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = ("success", "")
            mock_popen.return_value = mock_proc

            res = runner.execute_cli_task(task_item, meta_prompt)
            code, out = res[0], res[1]
            assert code == 0
            mock_popen.assert_called_once()
            called_cmd = mock_popen.call_args[0][0]
            assert isinstance(called_cmd, list)
            assert called_cmd[0] == "/usr/local/bin/agy"
            assert "--print" in called_cmd
            prompt_idx = called_cmd.index("--print") + 1
            assert called_cmd[prompt_idx] == meta_prompt
            assert mock_popen.call_args[1].get("shell") is not True


def test_runner_sync_existing_deliveries(tmp_path: Path):
    """Verify initial sync identifies existing reviews and git PR states."""
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir(parents=True)
    pr1_review = reviews_dir / "pr-1-abc12345.md"
    pr1_review.write_text("结论：pass_with_notes (通过)", encoding="utf-8")

    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    states = {}
    with patch("subprocess.run") as mock_git:
        mock_git.return_value = MagicMock(returncode=0, stdout="stage0_sha_999\n", stderr="")
        runner.sync_existing_deliveries(states)

        assert "source-download:r1" in states
        assert states["source-download:r1"].status == "done"
        assert states["source-download:r1"].pr_number == 1

        assert "stage0-fixes:r1" in states
        assert states["stage0-fixes:r1"].status == "awaiting_review"
        assert states["stage0-fixes:r1"].head_sha == "stage0_sha_999"
        assert states["stage0-fixes:r1"].pr_number == 2


def test_runner_fetch_remote_unreachable_preserves_state(tmp_path: Path):
    """P1-1: Verify network error or unreachable origin preserves state without crashing or wiping."""
    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    states = {
        "existing-task:r1": TaskState(
            task_id="existing-task",
            revision=1,
            status="awaiting_review",
            head_sha="head123",
        )
    }
    runner.save_state(states)

    with patch.object(runner, "fetch_remote_main", return_value=(False, "Connection timed out")):
        exit_code = runner.run_once()
        assert exit_code == 0
        loaded = runner.load_state()
        assert "existing-task:r1" in loaded
        assert loaded["existing-task:r1"].status == "awaiting_review"


def test_runner_loads_queue_from_origin_main(tmp_path: Path):
    """P1-1: Verify queue is read from origin/main:tasks/queue.json when available."""
    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    remote_queue_content = json.dumps({
        "version": 1,
        "tasks": [
            {"id": "remote-auth-task", "revision": 1, "path": "tasks/remote.md", "authorized": True}
        ]
    })

    def mock_sub_run(cmd, *args, **kwargs):
        if "git" in cmd and "origin/main:tasks/queue.json" in cmd:
            return MagicMock(returncode=0, stdout=remote_queue_content, stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_sub_run):
        tasks = runner.load_queue_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "remote-auth-task"
        assert tasks[0].authorized is True


def test_runner_request_changes_dispatches_fix_and_updates_head(tmp_path: Path):
    """P1-2: Verify request_changes review triggers fix dispatch, increments attempt, and updates head_sha."""
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir(parents=True)
    review_file = reviews_dir / "pr-2-old_sha.md"
    review_file.write_text("结论：request_changes\n必须修改两处错误", encoding="utf-8")

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    queue_file = tasks_dir / "queue.json"
    queue_file.write_text(
        json.dumps({
            "version": 1,
            "tasks": [
                {"id": "fixable-task", "revision": 1, "path": "tasks/f.md", "authorized": True}
            ]
        }),
        encoding="utf-8"
    )

    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    states = {
        "fixable-task:r1": TaskState(
            task_id="fixable-task",
            revision=1,
            status="awaiting_review",
            pr_number=2,
            head_sha="old_sha",
            attempt=1,
        )
    }
    runner.save_state(states)

    with patch.object(runner, "execute_cli_task", return_value=(0, "Fix applied successfully", 5555)) as mock_exec:
        with patch.object(runner, "_get_worktree_head_sha", return_value="new_sha_777"):
            exit_code = runner.run_once()
            assert exit_code == 0
            mock_exec.assert_called_once()
            call_prompt = mock_exec.call_args[0][1]
            assert "必须修改两处错误" in call_prompt

            loaded = runner.load_state()
            st = loaded["fixable-task:r1"]
            assert st.status == "awaiting_review"
            assert st.head_sha == "new_sha_777"
            assert st.attempt == 2


def test_runner_same_commit_request_changes_not_dispatched_twice(tmp_path: Path):
    """P1-2: Verify request_changes for the same commit is only dispatched once."""
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir(parents=True)
    review_file = reviews_dir / "pr-2-same_sha.md"
    review_file.write_text("结论：request_changes\n修改意见", encoding="utf-8")

    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    queue_file = tasks_dir / "queue.json"
    queue_file.write_text(
        json.dumps({
            "version": 1,
            "tasks": [
                {"id": "my-task", "revision": 1, "path": "tasks/t.md", "authorized": True}
            ]
        }),
        encoding="utf-8"
    )

    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    states = {
        "my-task:r1": TaskState(
            task_id="my-task",
            revision=1,
            status="awaiting_review",
            pr_number=2,
            head_sha="same_sha",
            last_error="dispatched:same_sha",  # Marked as already dispatched for this commit
        )
    }
    runner.save_state(states)

    with patch.object(runner, "execute_cli_task") as mock_exec:
        exit_code = runner.run_once()
        assert exit_code == 0
        mock_exec.assert_not_called()  # Must NOT dispatch again for same commit!


def test_runner_interrupted_stops_cycle_without_rerun(tmp_path: Path):
    """P1-3: Verify crashed PID marks task as interrupted and halts the current cycle without re-running."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "ready_task.md"
    task_file.write_text("Ready to run", encoding="utf-8")

    queue_file = tasks_dir / "queue.json"
    queue_file.write_text(
        json.dumps({
            "version": 1,
            "tasks": [
                {"id": "ready-task", "revision": 1, "path": "tasks/ready_task.md", "authorized": True}
            ]
        }),
        encoding="utf-8"
    )

    runner = LocalTaskRunner(repo_root=tmp_path, runner_dir=tmp_path / ".vmv-runner")
    states = {
        "crashed-task:r1": TaskState(
            task_id="crashed-task",
            revision=1,
            status="running",
            pid=99999999,
        )
    }
    runner.save_state(states)

    with patch.object(runner, "check_process_alive", return_value=False):
        with patch.object(runner, "execute_cli_task") as mock_exec:
            exit_code = runner.run_once()
            assert exit_code == 0
            mock_exec.assert_not_called()  # Ready task must NOT be executed in this interrupted cycle!

            loaded = runner.load_state()
            assert loaded["crashed-task:r1"].status == "interrupted"


