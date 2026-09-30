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

    def fetch_remote_main(self) -> tuple[bool, str]:
        """Safely fetch origin/main inside lock. Returns (success, err_msg)."""
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return True, ""
        git_dir = self.repo_root / ".git"
        if not git_dir.exists():
            return True, ""
        try:
            res = subprocess.run(
                ["git", "fetch", "origin", "main"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if res.returncode == 0:
                return True, ""
            err = res.stderr.strip() or res.stdout.strip()
            return False, f"git fetch origin main 失败: {err}"
        except subprocess.TimeoutExpired:
            return False, "git fetch 超时（超过 30 秒）"
        except Exception as exc:
            return False, f"git fetch 异常: {exc}"

    def load_queue_tasks(self) -> list[TaskItem]:
        """Load queue from origin/main:tasks/queue.json or fallback to local."""
        try:
            res = subprocess.run(
                ["git", "show", "origin/main:tasks/queue.json"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
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
            pass
        return self.load_queue()

    def get_task_prompt(self, item: TaskItem) -> str | None:
        """Read task prompt from remote origin/main or local file."""
        try:
            res = subprocess.run(
                ["git", "show", f"origin/main:{item.path}"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and res.stdout:
                return res.stdout
        except Exception:
            pass

        local_p = self.repo_root / item.path
        if local_p.exists():
            return local_p.read_text(encoding="utf-8")
        return None

    def prepare_worktree_for_task(self, task: TaskItem) -> tuple[Path | None, str | None]:
        """
        Ensure an isolated git worktree exists for this task.
        Protects the user's active checkout from any modifications.
        """
        worktree_base = self.runner_dir / "worktrees"
        worktree_base.mkdir(parents=True, exist_ok=True)
        worktree_dir = worktree_base / task.id
        branch_name = f"task/{task.id}"

        git_dir = self.repo_root / ".git"
        if not git_dir.exists():
            worktree_dir.mkdir(parents=True, exist_ok=True)
            return worktree_dir, None

        if worktree_dir.exists():
            status_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(worktree_dir),
                capture_output=True,
                text=True,
            )
            if status_res.returncode == 0:
                for line in status_res.stdout.splitlines():
                    if line.startswith("U") or line.startswith("AA") or line.startswith("DD"):
                        return None, f"worktree 存在未解决合并冲突: {worktree_dir}"
                return worktree_dir, None
            else:
                shutil.rmtree(worktree_dir, ignore_errors=True)

        ref = "origin/main"
        has_origin = subprocess.run(
            ["git", "rev-parse", "--verify", "origin/main"],
            cwd=str(self.repo_root),
            capture_output=True,
        ).returncode == 0
        if not has_origin:
            ref = "HEAD"

        cmd = ["git", "worktree", "add", "-B", branch_name, str(worktree_dir), ref]
        res = subprocess.run(cmd, cwd=str(self.repo_root), capture_output=True, text=True)
        if res.returncode == 0:
            return worktree_dir, None
        return None, f"git worktree add 失败: {res.stderr.strip() or res.stdout.strip()}"

    def _get_worktree_head_sha(self, worktree_dir: Path) -> str | None:
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(worktree_dir),
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return None

    def _get_github_token(self) -> str | None:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return None
        try:
            proc = subprocess.run(
                ["git", "credential", "fill"],
                input="protocol=https\nhost=github.com\n\n",
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in proc.stdout.splitlines():
                if line.startswith("password="):
                    return line.split("=", 1)[1]
        except Exception:
            pass
        return None

    def get_pr_number_for_branch(self, branch_name: str) -> int | None:
        """Query GitHub API to find PR number for a branch."""
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return None
        token = self._get_github_token()
        if not token:
            return None
        try:
            import urllib.request
            b = branch_name.replace("refs/heads/", "")
            url = f"https://api.github.com/repos/younuoqiqi1/video-moment-validation/pulls?head=younuoqiqi1:{b}&state=all"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "vmv-runner",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data and isinstance(data, list) and len(data) > 0:
                    return data[0]["number"]
        except Exception:
            pass
        return None

    def execute_cli_task(
        self,
        task: TaskItem,
        prompt_content: str,
        cwd: Path | None = None,
    ) -> tuple[int, str, int | None]:
        """
        Execute prompt via AGY CLI using argument list in isolated cwd.
        Returns (exit_code, output_text, child_pid).
        """
        resolved = shutil.which(self.agy_bin) or (
            self.agy_bin if Path(self.agy_bin).exists() else None
        )
        if not resolved:
            return 1, f"未找到可用的 AGY CLI 执行文件: '{self.agy_bin}'", None

        cmd = [
            resolved,
            "--print",
            prompt_content,
            "--output-format",
            "text",
            "--dangerously-skip-permissions",
        ]

        target_cwd = str(cwd or self.repo_root)

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=target_cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            child_pid = proc.pid
            try:
                stdout, stderr = proc.communicate(timeout=600.0)
                out = stdout.strip() or stderr.strip()
                return proc.returncode, out, child_pid
            except subprocess.TimeoutExpired:
                proc.kill()
                return 1, "AGY CLI 执行超时（超过 600 秒）", child_pid
        except Exception as exc:
            return 1, f"启动 AGY CLI 异常: {exc}", None

    def run_once(self) -> int:
        """
        Execute one check cycle:
        1. Acquire process lock
        2. Safely fetch origin/main
        3. Clean up dead/interrupted processes (stop cycle if interrupted)
        4. Match authorized tasks from queue (remote origin/main or local)
        5. Execute ready tasks or check reviews in isolated worktree
        """
        lock = RunnerLock(self.lock_file)
        if not lock.acquire():
            print("另一个 runner 实例正在运行，跳过本次执行。")
            return 0

        try:
            # 1. Safely fetch origin/main within lock
            self.fetch_remote_main()

            queue = self.load_queue_tasks()
            states = self.load_state()

            # 2. Check for interrupted processes
            had_interrupted = False
            for task_key, st in states.items():
                if st.status == "running" and not self.check_process_alive(st.pid):
                    st.status = "interrupted"
                    st.last_error = f"进程异常终止 (PID {st.pid})"
                    self.save_state(states)
                    had_interrupted = True

            if had_interrupted:
                print("检测到异常终止任务，本轮停止执行以供核验，避免盲目重试。")
                return 0

            # 0. Sync existing deliveries on initial load if empty
            if not states:
                self.sync_existing_deliveries(states)
                self.save_state(states)

            # 3. Find first authorized and actionable task
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
                        elif "request_changes" in content:
                            dispatch_tag = f"dispatched:{st.head_sha}"
                            if st.last_error and dispatch_tag in st.last_error:
                                # "同一提交的修正意见仅派发一次"
                                continue

                            print(f"任务 {task_key} 收到 request_changes 审查，开始派发修正...")
                            worktree_dir, wt_err = self.prepare_worktree_for_task(item)
                            if not worktree_dir:
                                st.status = "blocked"
                                st.last_error = f"工作区准备失败: {wt_err}"
                                self.save_state(states)
                                return 1

                            st.status = "running"
                            st.attempt += 1
                            st.last_error = dispatch_tag
                            st.started_at = datetime.now(timezone.utc).isoformat()
                            self.save_state(states)

                            fix_prompt = f"Codex 对 PR #{st.pr_number} (提交 {st.head_sha}) 提出了修改意见，请仔细阅读以下审查报告并执行修正：\n\n{content}"
                            exec_res = self.execute_cli_task(item, fix_prompt, cwd=worktree_dir)
                            code = exec_res[0]
                            output = exec_res[1]
                            child_pid = exec_res[2] if len(exec_res) > 2 else None
                            st.pid = child_pid

                            if code == 0:
                                head_sha = self._get_worktree_head_sha(worktree_dir)
                                st.status = "awaiting_review"
                                if head_sha:
                                    st.head_sha = head_sha
                                st.last_error = None
                                self.save_state(states)
                                print(f"任务 {task_key} 修正执行成功，更新 head {st.head_sha}，已转入 awaiting_review。")
                                return 0
                            else:
                                st.status = "blocked"
                                st.last_error = f"CLI 修正执行失败 (退出码 {code}): {output[:200]}"
                                self.save_state(states)
                                print(f"任务 {task_key} 修正执行失败: {st.last_error}")
                                return 1

                    continue

                if st.status in ("ready",):
                    # Check task file or remote task content
                    prompt_text = self.get_task_prompt(item)
                    if not prompt_text:
                        st.status = "blocked"
                        st.last_error = f"任务文件不存在: '{item.path}'"
                        self.save_state(states)
                        return 1

                    worktree_dir, wt_err = self.prepare_worktree_for_task(item)
                    if not worktree_dir:
                        st.status = "blocked"
                        st.last_error = f"工作区准备失败: {wt_err}"
                        self.save_state(states)
                        return 1

                    st.status = "running"
                    st.attempt += 1
                    st.started_at = datetime.now(timezone.utc).isoformat()
                    self.save_state(states)

                    exec_res = self.execute_cli_task(item, prompt_text, cwd=worktree_dir)
                    code = exec_res[0]
                    output = exec_res[1]
                    child_pid = exec_res[2] if len(exec_res) > 2 else None
                    st.pid = child_pid

                    if code == 0:
                        head_sha = self._get_worktree_head_sha(worktree_dir)
                        pr_num = self.get_pr_number_for_branch(f"task/{item.id}")
                        st.status = "awaiting_review"
                        st.pr_number = pr_num or st.pr_number
                        if head_sha:
                            st.head_sha = head_sha
                        st.last_error = None
                        self.save_state(states)
                        print(f"任务 {task_key} 执行成功，head {st.head_sha}，已转入 awaiting_review。")
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

        # Check local files first
        if reviews_dir.exists():
            if st.pr_number and st.head_sha:
                for p in reviews_dir.glob(f"pr-{st.pr_number}-*.md"):
                    if st.head_sha in p.name:
                        return p
                    try:
                        if st.head_sha in p.read_text(encoding="utf-8"):
                            return p
                    except Exception:
                        pass
                return None

            if st.pr_number:
                for p in reviews_dir.glob(f"pr-{st.pr_number}-*.md"):
                    return p

            for p in reviews_dir.glob("*.md"):
                try:
                    text = p.read_text(encoding="utf-8")
                    if st.task_id in text or (st.head_sha and st.head_sha in text):
                        return p
                except Exception:
                    pass

        # Check origin/main via git ls-tree if repo is git
        if st.pr_number:
            git_dir = self.repo_root / ".git"
            if git_dir.exists():
                try:
                    ls_res = subprocess.run(
                        ["git", "ls-tree", "--name-only", "origin/main", "reviews/"],
                        cwd=str(self.repo_root),
                        capture_output=True,
                        text=True,
                    )
                    if ls_res.returncode == 0:
                        matching_files = [
                            line.strip()
                            for line in ls_res.stdout.splitlines()
                            if line.strip().startswith(f"reviews/pr-{st.pr_number}-")
                        ]
                        target_file = None
                        if st.head_sha:
                            for mf in matching_files:
                                if st.head_sha in mf:
                                    target_file = mf
                                    break
                        if not target_file and matching_files:
                            target_file = matching_files[-1]

                        if target_file:
                            res = subprocess.run(
                                ["git", "show", f"origin/main:{target_file}"],
                                cwd=str(self.repo_root),
                                capture_output=True,
                                text=True,
                            )
                            if res.returncode == 0 and res.stdout.strip():
                                reviews_dir.mkdir(parents=True, exist_ok=True)
                                fname = Path(target_file).name
                                local_copy = reviews_dir / fname
                                local_copy.write_text(res.stdout, encoding="utf-8")
                                return local_copy
                except Exception:
                    pass

        return None
