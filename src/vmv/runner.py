"""Local AGY background task runner and queue manager."""

import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class TaskItem:
    id: str
    revision: int
    path: str
    authorized: bool = False


@dataclass
class TaskState:
    task_id: str
    revision: int
    status: str = "ready"  # ready, running, awaiting_review, blocked, interrupted, quota_wait, done
    attempt: int = 0
    pid: int | None = None
    started_at: str | None = None
    completed_at: str | None = None
    last_error: str | None = None
    pr_number: int | None = None
    head_sha: str | None = None
    review_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskState":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class RunnerLock:
    """Cross-process file lock using fcntl.flock."""

    def __init__(self, lock_file_path: Path):
        self.lock_file_path = lock_file_path
        self._fd: int | None = None

    def acquire(self) -> bool:
        self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(str(self.lock_file_path), os.O_CREAT | os.O_RDWR)
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None
            return False

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None


class LocalTaskRunner:
    """Manages reading authorized queue tasks, checking state, and executing via AGY CLI."""

    def __init__(
        self,
        repo_root: Path | None = None,
        runner_dir: Path | None = None,
        agy_bin: str | None = None,
    ):
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.runner_dir = (runner_dir or (self.repo_root / ".vmv-runner")).resolve()
        self.runner_dir.mkdir(parents=True, exist_ok=True)

        self.state_file = self.runner_dir / "state.json"
        self.lock_file = self.runner_dir / "runner.lock"
        self.queue_file = self.repo_root / "tasks" / "queue.json"

        resolved_agy = agy_bin or shutil.which("agy")
        if not resolved_agy:
            # Check default macOS local bin path
            fallback = Path.home() / ".local" / "bin" / "agy"
            if fallback.exists():
                resolved_agy = str(fallback)
        self.agy_bin = resolved_agy or "agy"

    def load_queue(self) -> list[TaskItem]:
        """Load task items from tasks/queue.json."""
        if not self.queue_file.exists():
            return []
        try:
            with open(self.queue_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw_tasks = data.get("tasks", [])
            return [
                TaskItem(
                    id=t["id"],
                    revision=int(t.get("revision", 1)),
                    path=t["path"],
                    authorized=bool(t.get("authorized", False)),
                )
                for t in raw_tasks
            ]
        except Exception:
            return []

    def load_state(self) -> dict[str, TaskState]:
        """Load persisted task states from state.json."""
        if not self.state_file.exists():
            return {}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                k: TaskState.from_dict(v) for k, v in data.get("tasks", {}).items()
            }
        except Exception:
            return {}

    def save_state(self, states: dict[str, TaskState]) -> None:
        """Atomically persist task states to state.json."""
        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "tasks": {k: v.to_dict() for k, v in states.items()},
        }
        tmp_file = self.state_file.with_name(f"{self.state_file.name}.tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, self.state_file)

    def check_process_alive(self, pid: int | None) -> bool:
        """Check if a given pid is still active."""
        if not pid or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def execute_cli_task(self, task: TaskItem, prompt_content: str) -> tuple[int, str]:
        """
        Execute prompt via AGY CLI using argument list.
        Returns (exit_code, output_text).
        """
        resolved = shutil.which(self.agy_bin) or (
            self.agy_bin if Path(self.agy_bin).exists() else None
        )
        if not resolved:
            return 1, f"未找到可用的 AGY CLI 执行文件: '{self.agy_bin}'"

        cmd = [
            resolved,
            "--print",
            prompt_content,
            "--output-format",
            "text",
            "--dangerously-skip-permissions",
        ]

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=600.0,
            )
            out = proc.stdout.strip() or proc.stderr.strip()
            return proc.returncode, out
        except subprocess.TimeoutExpired:
            return 1, "AGY CLI 执行超时（超过 600 秒）"
        except Exception as exc:
            return 1, f"启动 AGY CLI 异常: {exc}"

    def run_once(self) -> int:
        """
        Execute one check cycle:
        1. Acquire process lock
        2. Clean up dead/interrupted processes
        3. Match authorized tasks from queue
        4. Execute ready tasks or check reviews
        """
        lock = RunnerLock(self.lock_file)
        if not lock.acquire():
            print("另一个 runner 实例正在运行，跳过本次执行。")
            return 0

        try:
            queue = self.load_queue()
            states = self.load_state()

            # 1. Check for interrupted processes
            for task_key, st in states.items():
                if st.status == "running" and not self.check_process_alive(st.pid):
                    st.status = "interrupted"
                    st.last_error = f"进程异常终止 (PID {st.pid})"
                    self.save_state(states)

            # 0. Sync existing deliveries on initial load if empty
            if not states:
                self.sync_existing_deliveries(states)
                self.save_state(states)

            # 2. Find first authorized and non-done task
            for item in queue:
                if not item.authorized:
                    continue

                task_key = f"{item.id}:r{item.revision}"
                st = states.get(task_key)

                if st is None:
                    st = TaskState(task_id=item.id, revision=item.revision, status="ready")
                    states[task_key] = st
                    self.save_state(states)

                if st.status == "done":
                    continue

                if st.status == "awaiting_review":
                    # Check if matching review exists
                    review_file = self.find_matching_review(st)
                    if review_file:
                        content = review_file.read_text(encoding="utf-8")
                        if self._is_review_passed(content):
                            st.status = "done"
                            st.completed_at = datetime.now(timezone.utc).isoformat()
                            st.review_path = str(review_file.relative_to(self.repo_root))
                            self.save_state(states)
                            print(f"任务 {task_key} 已通过审查并标记完成: {st.review_path}")
                            return 0
                    continue

                if st.status in ("ready", "interrupted"):
                    # Check task file
                    task_path = self.repo_root / item.path
                    if not task_path.exists():
                        st.status = "blocked"
                        st.last_error = f"任务文件不存在: '{item.path}'"
                        self.save_state(states)
                        return 1

                    prompt_text = task_path.read_text(encoding="utf-8")
                    st.status = "running"
                    st.attempt += 1
                    st.pid = os.getpid()
                    st.started_at = datetime.now(timezone.utc).isoformat()
                    self.save_state(states)

                    code, output = self.execute_cli_task(item, prompt_text)
                    if code == 0:
                        st.status = "awaiting_review"
                        st.last_error = None
                        self.save_state(states)
                        print(f"任务 {task_key} 执行成功，已转入 awaiting_review。")
                        return 0
                    else:
                        st.status = "blocked"
                        st.last_error = f"CLI 执行失败 (退出码 {code}): {output[:200]}"
                        self.save_state(states)
                        print(f"任务 {task_key} 执行失败: {st.last_error}")
                        return 1

            return 0
        finally:
            lock.release()

    @staticmethod
    def _is_review_passed(review_text: str) -> bool:
        """Check if review indicates pass or pass_with_notes."""
        for line in review_text.splitlines():
            if "结论" in line or "conclusion" in line.lower():
                line_lower = line.lower()
                return "pass" in line_lower and "request_changes" not in line_lower
        content_lower = review_text.lower()
        return "pass" in content_lower and "request_changes" not in content_lower

    def sync_existing_deliveries(self, states: dict[str, TaskState]) -> None:
        """
        Inspect local repository markers, reviews, and git references to recognize
        already completed or awaiting-review deliveries, preventing duplicate execution.
        """
        reviews_dir = self.repo_root / "reviews"

        # 1. Recognize source-download if completed via pr-1 review
        source_key = "source-download:r1"
        if source_key not in states and reviews_dir.exists():
            for p in reviews_dir.glob("pr-1-*.md"):
                content = p.read_text(encoding="utf-8")
                status = "done" if self._is_review_passed(content) else "awaiting_review"
                sha = p.stem.split("-", 2)[-1] if len(p.stem.split("-")) >= 3 else None
                states[source_key] = TaskState(
                    task_id="source-download",
                    revision=1,
                    status=status,
                    pr_number=1,
                    head_sha=sha,
                    review_path=str(p.relative_to(self.repo_root)),
                )
                break

        # 2. Recognize stage0-fixes
        stage0_key = "stage0-fixes:r1"
        if stage0_key not in states:
            head_sha = None
            try:
                proc = subprocess.run(
                    ["git", "rev-parse", "--verify", "origin/task/stage0-review-fix"],
                    cwd=str(self.repo_root),
                    capture_output=True,
                    text=True,
                )
                if proc.returncode == 0:
                    head_sha = proc.stdout.strip()
                else:
                    proc_local = subprocess.run(
                        ["git", "rev-parse", "--verify", "task/stage0-review-fix"],
                        cwd=str(self.repo_root),
                        capture_output=True,
                        text=True,
                    )
                    if proc_local.returncode == 0:
                        head_sha = proc_local.stdout.strip()
            except Exception:
                pass

            if head_sha:
                matching_review = None
                if reviews_dir.exists():
                    for p in reviews_dir.glob("pr-2-*.md"):
                        if head_sha in p.name:
                            matching_review = p
                            break

                if matching_review:
                    content = matching_review.read_text(encoding="utf-8")
                    status = "done" if self._is_review_passed(content) else "blocked"
                    review_path_str = str(matching_review.relative_to(self.repo_root))
                else:
                    status = "awaiting_review"
                    review_path_str = None

                states[stage0_key] = TaskState(
                    task_id="stage0-fixes",
                    revision=1,
                    status=status,
                    pr_number=2,
                    head_sha=head_sha,
                    review_path=review_path_str,
                )

        # 3. Check any other task currently in queue against existing reviews
        if reviews_dir.exists():
            for item in self.load_queue():
                task_key = f"{item.id}:r{item.revision}"
                if task_key in states:
                    continue
                for p in reviews_dir.glob("*.md"):
                    try:
                        text = p.read_text(encoding="utf-8")
                        if item.id in text or item.path in text:
                            status = "done" if self._is_review_passed(text) else "awaiting_review"
                            states[task_key] = TaskState(
                                task_id=item.id,
                                revision=item.revision,
                                status=status,
                                review_path=str(p.relative_to(self.repo_root)),
                            )
                            break
                    except Exception:
                        pass

    def find_matching_review(self, st: TaskState) -> Path | None:
        """Find a review markdown matching this task."""
        reviews_dir = self.repo_root / "reviews"
        if not reviews_dir.exists():
            return None

        # Check by pr_number and head_sha if known
        if st.pr_number and st.head_sha:
            for p in reviews_dir.glob(f"pr-{st.pr_number}-*.md"):
                if st.head_sha in p.name:
                    return p
                try:
                    if st.head_sha in p.read_text(encoding="utf-8"):
                        return p
                except Exception:
                    pass
            # If head_sha is specified and none matched, do not match an unrelated SHA
            return None

        if st.pr_number:
            pattern = f"pr-{st.pr_number}-*.md"
            for p in reviews_dir.glob(pattern):
                return p

        # Check by task_id in review files
        for p in reviews_dir.glob("*.md"):
            try:
                text = p.read_text(encoding="utf-8")
                if st.task_id in text or (st.head_sha and st.head_sha in text):
                    return p
            except Exception:
                pass
        return None
