"""Local AGY background task runner and queue manager."""

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Only this exact task was explicitly authorized for automatic execution.
# Pin the task blob so edits to the PR task file cannot silently broaden scope.
AUTHORIZED_PR_TASK = {
    "task_id": "stage1-preview-followup",
    "pr_number": 5,
    "branch": "feat/stage1-media-import",
    "path": "tasks/stage1-preview-followup.md",
    "blob_sha": "d24aecccdbde1fce7dc28801936dcaeb2bbb564e",
}


def log_msg(msg: str) -> None:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] {msg}")


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
    head_branch: str | None = None
    worktree_path: str | None = None
    review_path: str | None = None
    dispatched_reviews: list[str] = field(default_factory=list)

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
            fallback = Path.home() / ".local" / "bin" / "agy"
            if fallback.exists():
                resolved_agy = str(fallback)
        self.agy_bin = resolved_agy or "agy"

    def load_queue(self) -> list[TaskItem]:
        """Load task items directly from filesystem tasks/queue.json (fallback/utility)."""
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
            if not isinstance(data, dict) or not isinstance(data.get("tasks"), dict):
                raise ValueError("任务状态结构无效")
            return {
                k: TaskState.from_dict(v) for k, v in data.get("tasks", {}).items()
            }
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("任务状态文件无法读取；保留原文件并停止派发") from exc

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

    @staticmethod
    def check_process_alive(pid: int | None) -> bool:
        """Check if a given pid is still active without shell injection."""
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def fetch_remote_main(self) -> tuple[bool, str]:
        """Fetch exactly the remote authority and the one authorized PR branch."""
        if not shutil.which("git"):
            return False, "系统 PATH 中未找到 git 工具"
        git_dir = self.repo_root / ".git"
        if not git_dir.exists():
            return False, "根目录不是 Git 仓库"
        try:
            res = subprocess.run(
                [
                    "git", "fetch", "origin",
                    "+refs/heads/main:refs/remotes/origin/main",
                    "+refs/heads/feat/stage1-media-import:refs/remotes/origin/feat/stage1-media-import",
                ],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if res.returncode == 0:
                return True, ""
            err = res.stderr.strip() or res.stdout.strip()
            return False, f"git fetch origin 失败: {err}"
        except subprocess.TimeoutExpired:
            return False, "git fetch 超时（超过 30 秒）"
        except Exception as exc:
            return False, f"git fetch 异常: {exc}"

    def get_origin_main_sha(self) -> str | None:
        """Get verified commit SHA of origin/main."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--verify", "origin/main"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return None

    def load_queue_tasks(self, snapshot_sha: str | None = None) -> tuple[list[TaskItem] | None, str | None]:
        """
        Load queue strictly from remote origin/main snapshot.
        Returns (tasks_list, error_diagnostic).
        A missing remote queue is an error, never local authorization.
        """
        git_dir = self.repo_root / ".git"
        if not git_dir.exists():
            return None, "根目录不是 Git 仓库"

        sha = snapshot_sha or "origin/main"
        try:
            res = subprocess.run(
                ["git", "show", f"{sha}:tasks/queue.json"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and res.stdout.strip():
                try:
                    data = json.loads(res.stdout.strip())
                except Exception as e:
                    return None, f"远端 {sha[:7] if len(sha) >= 7 else sha}:tasks/queue.json JSON 格式损坏: {e}"

                raw_tasks = data.get("tasks", [])
                tasks = [
                    TaskItem(
                        id=t["id"],
                        revision=int(t.get("revision", 1)),
                        path=t["path"],
                        authorized=bool(t.get("authorized", False)),
                    )
                    for t in raw_tasks
                ]
                return tasks, None

            err = res.stderr.strip() or "tasks/queue.json 文件不存在"
            return None, f"无法从 {sha[:7] if len(sha) >= 7 else sha} 读取 tasks/queue.json: {err}"
        except Exception as exc:
            return None, f"读取远端队列异常: {exc}"

    def discover_pr_branch_tasks(self) -> list[dict[str, Any]]:
        """
        Check remote PR tracking branches for authorized follow-up tasks.
        Specifically verifies if PR #5 branch (origin/feat/stage1-media-import) has tasks/stage1-preview-followup.md.
        """
        git_dir = self.repo_root / ".git"
        if not git_dir.exists():
            return []

        discovered: list[dict[str, Any]] = []
        monitored_pr_tasks = [
            ("feat/stage1-media-import", 5, "tasks/stage1-preview-followup.md", "stage1-preview-followup"),
        ]

        for branch, pr_num, task_rel_path, task_id in monitored_pr_tasks:
            ref = f"origin/{branch}"
            sha_res = subprocess.run(
                ["git", "rev-parse", "--verify", ref],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
            )
            if sha_res.returncode != 0 or not sha_res.stdout.strip():
                continue
            branch_sha = sha_res.stdout.strip()

            show_res = subprocess.run(
                ["git", "show", f"{branch_sha}:{task_rel_path}"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
            )
            if show_res.returncode == 0 and show_res.stdout.strip():
                title_line = ""
                for l in show_res.stdout.splitlines():
                    if l.startswith("#"):
                        title_line = l.strip("# ").strip()
                        break
                discovered.append({
                    "task_id": task_id,
                    "pr_number": pr_num,
                    "branch": branch,
                    "remote_sha": branch_sha,
                    "task_path": task_rel_path,
                    "title": title_line or task_id,
                })
        return discovered

    def get_task_prompt(self, item: TaskItem, snapshot_sha: str | None = None) -> tuple[str | None, str | None]:
        """Read task prompt strictly from remote snapshot. Returns (content, error)."""
        git_dir = self.repo_root / ".git"
        if not git_dir.exists():
            return None, "根目录不是 Git 仓库"

        sha = snapshot_sha or "origin/main"
        try:
            res = subprocess.run(
                ["git", "show", f"{sha}:{item.path}"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout, None
            err = res.stderr.strip() or "文件不存在或内容为空"
            return None, f"无法从 {sha[:7] if len(sha) >= 7 else sha} 读取任务提示词 '{item.path}': {err}"
        except Exception as exc:
            return None, f"读取任务提示词异常: {exc}"

    def resolve_authorized_pr_task(
        self, discovery: dict[str, Any]
    ) -> tuple[TaskItem | None, str | None, str | None, bool]:
        """Resolve only the single PR task whose exact scope was authorized.
        
        The final bool marks errors that are safe to retry on the next poll.
        Scope mismatches and closed/draft PRs are permanent blocks.
        """
        expected = AUTHORIZED_PR_TASK
        identity = (
            discovery.get("task_id"),
            discovery.get("pr_number"),
            discovery.get("branch"),
            discovery.get("task_path"),
        )
        allowed = (
            expected["task_id"],
            expected["pr_number"],
            expected["branch"],
            expected["path"],
        )
        if identity != allowed:
            return None, None, "PR 任务不在明确授权白名单内", False

        branch_sha = discovery.get("remote_sha")
        if not isinstance(branch_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", branch_sha):
            return None, None, "PR 分支 SHA 格式无效", False

        pr_info = self.get_pr_info_for_branch(expected["branch"])
        if not pr_info:
            return None, None, "暂时无法从 GitHub 核验 PR #5 状态", True
        if (
            pr_info.get("number") != expected["pr_number"]
            or pr_info.get("head_ref") != expected["branch"]
        ):
            return None, None, "GitHub 返回的 PR 身份或分支不匹配", False
        if pr_info.get("state") != "open" or pr_info.get("draft"):
            return None, None, "PR #5 已关闭或处于草稿状态", False
        if pr_info.get("head_sha") != branch_sha:
            return None, None, "PR #5 的最新 SHA 尚未与本轮 fetch 对齐", True

        blob_res = subprocess.run(
            ["git", "rev-parse", f"{branch_sha}:{expected['path']}"],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
        )
        if blob_res.returncode != 0 or blob_res.stdout.strip() != expected["blob_sha"]:
            return None, None, "PR #5 任务文件与已授权版本不一致；为避免扩大范围，停止派发", False

        task_res = subprocess.run(
            ["git", "show", f"{branch_sha}:{expected['path']}"],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
        )
        if task_res.returncode != 0 or not task_res.stdout.strip():
            return None, None, "暂时无法读取已授权的 PR #5 任务文件", True

        item = TaskItem(
            id=expected["task_id"],
            revision=1,
            path=expected["path"],
            authorized=True,
        )
        prompt = (
            "执行下方唯一已授权的 PR #5 阶段 1 补充任务。严格只处理任务文件列出的阶段 1 内容。"
            "如果本机素材不存在、工作区有用户改动或无法核实真实视频，停止并在 PR 中说明阻塞；"
            "不得伪造观察结果，不得上传素材/帧图，不得合并 PR，不得开始阶段 2。"
            "任务文件内容如下：\n\n"
            + task_res.stdout
        )
        return item, prompt, None, False

    def get_remote_branch_sha(self, branch_name: str) -> str | None:
        """Return the fetched origin SHA for a validated branch name."""
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch_name) or ".." in branch_name:
            return None
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--verify", f"origin/{branch_name}"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", res.stdout.strip()):
                return res.stdout.strip()
        except Exception:
            pass
        return None

    def post_pr_comment(self, pr_number: int, comment: str) -> bool:
        """Post a progress note without exposing credentials in logs."""
        token = self._get_github_token()
        if not token:
            return False
        try:
            import urllib.request
            url = f"https://api.github.com/repos/younuoqiqi1/video-moment-validation/issues/{pr_number}/comments"
            body = json.dumps({"body": comment}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "Content-Type": "application/json",
                    "User-Agent": "vmv-runner",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    def get_registered_worktrees(self) -> list[dict[str, str]]:
        """
        Parse `git worktree list --porcelain`.
        Returns a list of dicts, each with 'worktree', 'HEAD', 'branch'.
        """
        res = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            return []

        worktrees: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in res.stdout.splitlines():
            line_str = line.strip()
            if not line_str:
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line_str.startswith("worktree "):
                current["worktree"] = line_str.split("worktree ", 1)[1].strip()
            elif line_str.startswith("HEAD "):
                current["HEAD"] = line_str.split("HEAD ", 1)[1].strip()
            elif line_str.startswith("branch "):
                current["branch"] = line_str.split("branch ", 1)[1].strip()
            elif line_str == "bare":
                current["bare"] = "true"
            elif line_str == "detached":
                current["detached"] = "true"

        if current:
            worktrees.append(current)
        return worktrees

    def prepare_worktree_for_task(
        self,
        task: TaskItem,
        branch_name: str | None = None,
        base_ref: str | None = None,
    ) -> tuple[Path | None, str | None]:
        """
        Ensure an isolated git worktree exists for this task.
        Protects the user's active checkout from any modifications.
        Follows strict branch preservation rules:
        - NEVER uses git worktree add -B (never resets branch)
        - NEVER calls shutil.rmtree on existing directory
        - Rejects un-registered directories (preserves sentinels)
        - Checks for branch occupancy conflicts across worktrees
        - Attaches directly to existing branch without reset
        """
        git_dir = self.repo_root / ".git"
        if not git_dir.exists():
            return None, "根目录不是 Git 仓库"

        worktree_base = self.runner_dir / "worktrees"
        worktree_base.mkdir(parents=True, exist_ok=True)
        worktree_dir = (worktree_base / task.id).resolve()

        target_branch = branch_name or f"task/{task.id}"
        target_branch = target_branch.replace("refs/heads/", "")

        registered = self.get_registered_worktrees()
        reg_by_path: dict[str, dict[str, str]] = {}
        reg_by_branch: dict[str, str] = {}

        for wt in registered:
            wt_path_str = str(Path(wt.get("worktree", "")).resolve())
            reg_by_path[wt_path_str] = wt
            b = wt.get("branch", "").replace("refs/heads/", "")
            if b:
                reg_by_branch[b] = wt_path_str

        # Check if target branch is checked out in a different worktree
        if target_branch in reg_by_branch and reg_by_branch[target_branch] != str(worktree_dir):
            return None, f"分支 '{target_branch}' 已被其它工作区占用: {reg_by_branch[target_branch]}"

        # Check if worktree_dir exists
        if worktree_dir.exists():
            if str(worktree_dir) not in reg_by_path:
                # Unknown directory or unregistered directory! Preserve sentinel, DO NOT rmtree!
                return None, f"工作区目录已存在但未在 git worktree 中注册 (未知目录保留): {worktree_dir}"

            registered_wt = reg_by_path[str(worktree_dir)]
            curr_branch = registered_wt.get("branch", "").replace("refs/heads/", "")
            if curr_branch != target_branch:
                return None, f"worktree 路径已被分支 '{curr_branch}' 占用，与目标分支 '{target_branch}' 冲突"

            # Check for unresolved merge conflicts
            status_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(worktree_dir),
                capture_output=True,
                text=True,
            )
            if status_res.returncode != 0:
                return None, f"无法获取 worktree 状态: {status_res.stderr.strip() or status_res.stdout.strip()}"
            if status_res.stdout.strip():
                return None, f"隔离 worktree 存在未提交改动，为保护已有文件而停止: {worktree_dir}"

            remote_ref = f"origin/{target_branch}"
            remote_check = subprocess.run(
                ["git", "rev-parse", "--verify", remote_ref],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
            )
            if remote_check.returncode == 0:
                local_head = self._get_worktree_head_sha(worktree_dir)
                remote_head = remote_check.stdout.strip()
                if local_head != remote_head:
                    ancestor = subprocess.run(
                        ["git", "merge-base", "--is-ancestor", local_head or "", remote_ref],
                        cwd=str(self.repo_root),
                        capture_output=True,
                        text=True,
                    )
                    if ancestor.returncode != 0:
                        return None, f"隔离 worktree 与远端分支已分叉，未执行覆盖或重置: {target_branch}"
                    ff_res = subprocess.run(
                        ["git", "merge", "--ff-only", remote_ref],
                        cwd=str(worktree_dir),
                        capture_output=True,
                        text=True,
                    )
                    if ff_res.returncode != 0:
                        return None, f"隔离 worktree 快进同步失败: {ff_res.stderr.strip() or ff_res.stdout.strip()}"
            return worktree_dir, None

        # If worktree_dir does not exist, add it
        branch_exists_locally = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{target_branch}"],
            cwd=str(self.repo_root),
            capture_output=True,
        ).returncode == 0

        branch_exists_remotely = subprocess.run(
            ["git", "rev-parse", "--verify", f"origin/{target_branch}"],
            cwd=str(self.repo_root),
            capture_output=True,
        ).returncode == 0

        if branch_exists_locally:
            # Existing local branch: attach without -b/-B or reset
            cmd = ["git", "worktree", "add", str(worktree_dir), target_branch]
        elif branch_exists_remotely:
            # Existing remote branch: checkout tracking branch with -b
            cmd = ["git", "worktree", "add", "-b", target_branch, str(worktree_dir), f"origin/{target_branch}"]
        else:
            # Brand new branch: checkout with -b from base_ref or snapshot_sha or origin/main
            ref = base_ref or "origin/main"
            has_ref = subprocess.run(
                ["git", "rev-parse", "--verify", ref],
                cwd=str(self.repo_root),
                capture_output=True,
            ).returncode == 0
            if not has_ref:
                ref = "HEAD"
            cmd = ["git", "worktree", "add", "-b", target_branch, str(worktree_dir), ref]

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

    def get_pr_info_for_branch(self, branch_name: str) -> dict[str, Any] | None:
        """
        Query GitHub API to find PR info for a branch.
        Returns dict with: number, state, draft, head_ref, head_sha.
        """
        token = self._get_github_token()
        if not token:
            return None
        b = branch_name.replace("refs/heads/", "").replace("origin/", "")
        try:
            import urllib.request
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
                if data and isinstance(data, list):
                    for pr in data:
                        head_ref = pr.get("head", {}).get("ref", "")
                        if head_ref == b:
                            return {
                                "number": pr.get("number"),
                                "state": pr.get("state"),
                                "draft": bool(pr.get("draft", False)),
                                "head_ref": head_ref,
                                "head_sha": pr.get("head", {}).get("sha"),
                            }
        except Exception:
            pass
        return None

    def get_all_open_prs(self) -> list[dict[str, Any]]:
        """Query GitHub API to get all open PRs with full metadata."""
        token = self._get_github_token()
        if not token:
            return []
        try:
            import urllib.request
            url = "https://api.github.com/repos/younuoqiqi1/video-moment-validation/pulls?state=open"
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
                if data and isinstance(data, list):
                    return [
                        {
                            "number": pr.get("number"),
                            "state": pr.get("state"),
                            "draft": bool(pr.get("draft", False)),
                            "head_ref": pr.get("head", {}).get("ref", ""),
                            "head_sha": pr.get("head", {}).get("sha"),
                        }
                        for pr in data
                    ]
        except Exception:
            pass
        return []

    def _verify_delivery(
        self,
        st: TaskState,
        target_branch: str,
        worktree_dir: Path,
    ) -> tuple[bool, str | None]:
        """
        Verify delivery consistency:
        1. Worktree HEAD must be readable.
        2. Must have open, non-draft PR matching target_branch.
        3. Worktree HEAD, remote branch SHA, and PR head SHA must all be identical.
        Returns (is_valid, error_reason).
        """
        wt_head = self._get_worktree_head_sha(worktree_dir)
        if not wt_head:
            return False, "无法读取 worktree HEAD SHA"

        # Check PR
        pr_info = self.get_pr_info_for_branch(target_branch)
        if not pr_info:
            return False, f"未找到关联的有效 GitHub PR (分支: {target_branch})，未完成交付"

        if pr_info.get("state") != "open" or pr_info.get("draft"):
            return False, f"关联 PR #{pr_info.get('number')} 不是 open 状态或为草稿 (draft)，未完成交付"

        # Check remote branch SHA
        res = subprocess.run(
            ["git", "rev-parse", f"origin/{target_branch}"],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
        )
        remote_sha = res.stdout.strip() if res.returncode == 0 else ""

        pr_head_sha = pr_info.get("head_sha")
        if not remote_sha or remote_sha != wt_head or pr_head_sha != wt_head:
            return (
                False,
                f"交付提交未推送到远端或与 PR head 不一致 (worktree: {wt_head[:7]}, remote: {remote_sha[:7] if remote_sha else 'None'}, pr: {pr_head_sha[:7] if pr_head_sha else 'None'})",
            )

        st.pr_number = pr_info["number"]
        st.head_sha = wt_head
        st.head_branch = target_branch
        st.worktree_path = str(worktree_dir)
        return True, None

    def execute_cli_task(
        self,
        task: TaskItem,
        prompt_content: str,
        cwd: Path | None = None,
        on_started: Any = None,
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
            "--model",
            "gemini-3.8-flash-high",
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
            if on_started and callable(on_started):
                try:
                    on_started(child_pid)
                except Exception as exc:
                    proc.kill()
                    try:
                        proc.wait(timeout=5.0)
                    except Exception:
                        pass
                    return 1, f"启动回调异常，已终止子进程 (PID {child_pid}): {exc}", child_pid

            try:
                stdout, stderr = proc.communicate(timeout=600.0)
                out = stdout.strip() or stderr.strip()
                return proc.returncode, out, child_pid
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=5.0)
                except Exception:
                    pass
                return 1, "AGY CLI 执行超时（超过 600 秒）", child_pid
        except Exception as exc:
            return 1, f"启动 AGY CLI 异常: {exc}", None

    def run_once(self) -> int:
        """
        Execute one check cycle:
        1. Acquire process lock
        2. Safely fetch origin/main (halts on error without dispatching)
        3. Clean up dead/interrupted processes
        4. Match authorized tasks strictly from remote snapshot
        5. Execute ready tasks or check reviews in isolated worktree
        6. Verify PR consistency before entering awaiting_review
        """
        lock = RunnerLock(self.lock_file)
        if not lock.acquire():
            log_msg("另一个 runner 实例正在运行，跳过本次执行。")
            return 0

        try:
            # 1. Safely fetch origin branches within lock
            fetch_ok, fetch_err = self.fetch_remote_main()
            if not fetch_ok:
                log_msg(f"远程仓库同步失败: {fetch_err}，终止本轮执行以避免执行未授权或过时任务。")
                return 1

            snapshot_sha = self.get_origin_main_sha()
            if not snapshot_sha:
                log_msg("无法解析 origin/main 的最新 SHA，终止本轮执行。")
                return 1

            log_msg(f"[轮询检查] git fetch 同步完成，origin/main: {snapshot_sha[:7]}")

            queue, queue_err = self.load_queue_tasks(snapshot_sha)
            if queue is None:
                log_msg(f"远程队列加载失败: {queue_err}，终止本轮执行。")
                return 1

            try:
                states = self.load_state()
            except RuntimeError as exc:
                log_msg(str(exc))
                return 1

            # 2. Check for interrupted processes
            had_interrupted = False
            for task_key, st in states.items():
                if st.status == "running" and not self.check_process_alive(st.pid):
                    st.status = "interrupted"
                    st.last_error = f"进程异常终止 (PID {st.pid})"
                    self.save_state(states)
                    had_interrupted = True

            if had_interrupted:
                log_msg("检测到异常终止任务，本轮停止执行以供核验，避免盲目重试。")
                return 0

            # 3. Sync existing deliveries on initial load if empty
            if not states:
                self.sync_existing_deliveries(states)
                self.save_state(states)

            # 4. Resolve the one explicitly authorized PR task. All other
            # PR-branch tasks remain non-executable.
            pr_task_prompts: dict[str, str] = {}
            retryable_pr_keys: set[str] = set()
            pr_tasks = self.discover_pr_branch_tasks()
            for pt in pr_tasks:
                task_id = pt.get("task_id")
                pr_num = pt.get("pr_number")
                task_key = f"{task_id}:r1"
                legacy_key = f"{task_id}:pr{pr_num}"
                if task_key not in states and legacy_key in states:
                    states[task_key] = states.pop(legacy_key)

                item, prompt_text, resolve_err, retryable = self.resolve_authorized_pr_task(pt)
                st = states.get(task_key)
                if st is None:
                    st = TaskState(
                        task_id=str(task_id),
                        revision=1,
                        status=("ready" if retryable else "blocked") if resolve_err else "ready",
                        pr_number=pr_num if isinstance(pr_num, int) else None,
                        head_sha=pt.get("remote_sha"),
                        head_branch=pt.get("branch"),
                    )
                    states[task_key] = st
                st.pr_number = pr_num if isinstance(pr_num, int) else st.pr_number
                st.head_branch = str(pt.get("branch") or st.head_branch or "")
                if resolve_err:
                    st.status = "ready" if retryable else "blocked"
                    st.last_error = resolve_err
                    if retryable:
                        retryable_pr_keys.add(task_key)
                    self.save_state(states)
                    level = "等待重试" if retryable else "阻塞"
                    log_msg(f"[PR 任务{level}] {task_key}: {resolve_err}")
                    continue

                previous_sha = st.head_sha
                previous_status = st.status
                # Keep the reviewed code SHA if its exact review report has arrived
                # on this branch. The report commit itself can advance the PR head.
                matching_review = None
                if previous_status == "awaiting_review" and previous_sha:
                    matching_review, _ = self.find_matching_review(st, snapshot_sha)

                if previous_status == "discovered_readonly":
                    st.status = "ready"
                if previous_sha != pt["remote_sha"] and not matching_review:
                    st.head_sha = pt["remote_sha"]
                    if previous_status == "awaiting_review":
                        st.status = "awaiting_review"
                elif not st.head_sha:
                    st.head_sha = pt["remote_sha"]

                st.last_error = None if st.status in ("ready", "awaiting_review") else st.last_error
                if item is not None and prompt_text is not None and st.status in ("ready", "awaiting_review"):
                    queue = [queued for queued in queue if queued.id != item.id]
                    queue.append(item)
                    pr_task_prompts[task_key] = prompt_text
                    log_msg(
                        f"[PR 任务授权] PR #5 任务已核对：open、非草稿、分支 SHA 与任务文件版本一致；"
                        f"状态 {st.status}。"
                    )
                self.save_state(states)

            # 5. Block queue entries whose explicit authorization was revoked.
            active_queue_keys = {f"{item.id}:r{item.revision}": item for item in queue}
            for task_key, st in states.items():
                if st.status in ("ready", "running"):
                    if task_key in retryable_pr_keys:
                        continue
                    item = active_queue_keys.get(task_key)
                    if not item or not item.authorized:
                        st.status = "blocked"
                        st.last_error = "远程队列已撤销对该任务的授权或任务已从队列移除"
                        self.save_state(states)
                        log_msg(f"任务 {task_key} 授权已被远端撤销，状态置为 blocked。")

            # 6. Process actionable tasks from queue
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
                    review_file, content = self.find_matching_review(st, snapshot_sha)
                    if review_file and content:
                        conclusion = self._parse_review_conclusion(content)
                        if conclusion in ("pass", "pass_with_notes"):
                            st.status = "done"
                            st.completed_at = datetime.now(timezone.utc).isoformat()
                            st.review_path = f"reviews/pr-{st.pr_number}-{st.head_sha}.md"
                            self.save_state(states)
                            log_msg(f"任务 {task_key} 已通过审查并标记完成: {st.review_path}")
                            return 0
                        elif conclusion == "request_changes":
                            dispatch_key = f"{st.pr_number}:{st.head_sha}"
                            if dispatch_key in st.dispatched_reviews or (
                                st.last_error and f"dispatched:{st.head_sha}" in st.last_error
                            ):
                                continue

                            log_msg(f"任务 {task_key} 收到 request_changes 审查，开始派发修正...")
                            target_branch = st.head_branch or f"task/{item.id}"
                            worktree_dir, wt_err = self.prepare_worktree_for_task(
                                item, branch_name=target_branch, base_ref=snapshot_sha
                            )
                            if not worktree_dir:
                                st.status = "blocked"
                                st.last_error = f"工作区准备失败: {wt_err}"
                                self.save_state(states)
                                return 1

                            pre_dispatch_head = self._get_worktree_head_sha(worktree_dir)
                            if not pre_dispatch_head:
                                st.status = "blocked"
                                st.last_error = "无法读取隔离 worktree 当前 HEAD，未派发 CLI"
                                self.save_state(states)
                                return 1
                            if item.id == AUTHORIZED_PR_TASK["task_id"]:
                                remote_head = self.get_remote_branch_sha(target_branch)
                                if not remote_head or remote_head != pre_dispatch_head:
                                    st.status = "blocked"
                                    st.last_error = "隔离 worktree 未与已核验 PR #5 最新远端 SHA 对齐，未派发 CLI"
                                    self.save_state(states)
                                    return 1
                            st.dispatched_reviews.append(dispatch_key)
                            st.status = "running"
                            st.attempt += 1
                            st.started_at = datetime.now(timezone.utc).isoformat()
                            self.save_state(states)

                            def on_started(pid: int):
                                st.pid = pid
                                self.save_state(states)
                                if st.pr_number == AUTHORIZED_PR_TASK["pr_number"]:
                                    posted = self.post_pr_comment(
                                        st.pr_number,
                                        "@codex AGY 已开始处理已授权的阶段 1 补充任务。"
                                        "正在核对 130 条清单、完整预览与长区间；本地素材抽查结果会单独记录。",
                                    )
                                    if not posted:
                                        log_msg("PR 进度评论未能发送；AGY 任务仍继续运行。")

                            fix_prompt = (
                                pr_task_prompts.get(task_key, "")
                                + f"\n\nCodex 对 PR #{st.pr_number} (提交 {st.head_sha}) 提出了修改意见，"
                                + f"请严格在原任务范围内阅读以下审查报告并执行修正：\n\n{content}"
                            )
                            exec_res = self.execute_cli_task(
                                item, fix_prompt, cwd=worktree_dir, on_started=on_started
                            )
                            code = exec_res[0]
                            output = exec_res[1]
                            child_pid = exec_res[2] if len(exec_res) > 2 else None
                            st.pid = child_pid

                            if code == 0:
                                new_head = self._get_worktree_head_sha(worktree_dir)
                                if new_head and new_head == pre_dispatch_head:
                                    st.status = "blocked"
                                    st.last_error = "CLI 执行未产生新的代码提交 (HEAD 与派发前一致)"
                                    self.save_state(states)
                                    log_msg(f"任务 {task_key} 阻塞: 未产生新代码提交")
                                    return 1

                                # Verify delivery consistency
                                ok_deliv, err_deliv = self._verify_delivery(st, target_branch, worktree_dir)
                                if not ok_deliv:
                                    st.status = "blocked"
                                    st.last_error = err_deliv
                                    self.save_state(states)
                                    log_msg(f"任务 {task_key} 交付核验失败: {err_deliv}")
                                    return 1

                                st.status = "awaiting_review"
                                st.last_error = None
                                self.save_state(states)
                                log_msg(f"任务 {task_key} 修正执行成功且交付核验一致，head {st.head_sha}，已转入 awaiting_review。")
                                return 0
                            else:
                                st.status = "blocked"
                                st.last_error = f"CLI 修正执行失败 (退出码 {code}): {output[:200]}"
                                self.save_state(states)
                                log_msg(f"任务 {task_key} 修正执行失败: {st.last_error}")
                                return 1

                    continue

                if st.status in ("ready",):
                    prompt_text = pr_task_prompts.get(task_key)
                    prompt_err = None
                    if prompt_text is None:
                        prompt_text, prompt_err = self.get_task_prompt(item, snapshot_sha)
                    if not prompt_text:
                        st.status = "blocked"
                        st.last_error = prompt_err or f"任务文件不存在或无法从远程读取: '{item.path}'"
                        self.save_state(states)
                        return 1

                    target_branch = st.head_branch or f"task/{item.id}"
                    worktree_dir, wt_err = self.prepare_worktree_for_task(
                        item, branch_name=target_branch, base_ref=snapshot_sha
                    )
                    if not worktree_dir:
                        st.status = "blocked"
                        st.last_error = f"工作区准备失败: {wt_err}"
                        self.save_state(states)
                        return 1

                    pre_dispatch_head = self._get_worktree_head_sha(worktree_dir)
                    if not pre_dispatch_head:
                        st.status = "blocked"
                        st.last_error = "无法读取隔离 worktree 当前 HEAD，未派发 CLI"
                        self.save_state(states)
                        return 1
                    if item.id == AUTHORIZED_PR_TASK["task_id"]:
                        remote_head = self.get_remote_branch_sha(target_branch)
                        if not remote_head or remote_head != pre_dispatch_head:
                            st.status = "blocked"
                            st.last_error = "隔离 worktree 未与已核验 PR #5 最新远端 SHA 对齐，未派发 CLI"
                            self.save_state(states)
                            return 1
                    st.status = "running"
                    st.attempt += 1
                    st.started_at = datetime.now(timezone.utc).isoformat()
                    self.save_state(states)

                    def on_started(pid: int):
                        st.pid = pid
                        self.save_state(states)
                        if st.pr_number == AUTHORIZED_PR_TASK["pr_number"]:
                            posted = self.post_pr_comment(
                                st.pr_number,
                                "@codex AGY 已开始处理已授权的阶段 1 补充任务。"
                                "正在核对 130 条清单、完整预览与长区间；本地素材抽查结果会单独记录。",
                            )
                            if not posted:
                                log_msg("PR 进度评论未能发送；AGY 任务仍继续运行。")

                    exec_res = self.execute_cli_task(
                        item, prompt_text, cwd=worktree_dir, on_started=on_started
                    )
                    code = exec_res[0]
                    output = exec_res[1]
                    child_pid = exec_res[2] if len(exec_res) > 2 else None
                    st.pid = child_pid

                    if code == 0:
                        # Verify delivery consistency
                        ok_deliv, err_deliv = self._verify_delivery(st, target_branch, worktree_dir)
                        if not ok_deliv:
                            st.status = "blocked"
                            st.last_error = err_deliv
                            self.save_state(states)
                            log_msg(f"任务 {task_key} 交付核验失败: {err_deliv}")
                            return 1

                        st.status = "awaiting_review"
                        st.last_error = None
                        self.save_state(states)
                        log_msg(f"任务 {task_key} 执行成功且交付核验一致，head {st.head_sha}，已转入 awaiting_review。")
                        return 0
                    else:
                        st.status = "blocked"
                        st.last_error = f"CLI 执行失败 (退出码 {code}): {output[:200]}"
                        self.save_state(states)
                        log_msg(f"任务 {task_key} 执行失败: {st.last_error}")
                        return 1

            return 0
        finally:
            lock.release()

    @staticmethod
    def _parse_review_conclusion(review_text: str) -> str:
        """
        Strictly parse exact conclusion token from review text.
        Only accepts one of: 'pass', 'pass_with_notes', 'request_changes', 'blocked'.
        Rejects false-positives like 'not_pass_with_notes'.
        """
        for line in review_text.splitlines():
            line_str = line.strip()
            if "结论" in line_str or "conclusion" in line_str.lower():
                val = line_str
                if "：" in line_str:
                    val = line_str.split("：", 1)[1]
                elif ":" in line_str:
                    val = line_str.split(":", 1)[1]
                tokens = [t.lower() for t in re.findall(r"[a-zA-Z_]+", val)]
                if "request_changes" in tokens:
                    return "request_changes"
                if "pass_with_notes" in tokens:
                    if "not" not in tokens and "no" not in tokens:
                        return "pass_with_notes"
                if "blocked" in tokens:
                    return "blocked"
                if "pass" in tokens and "not" not in tokens and "no" not in tokens:
                    return "pass"
        return "unknown"

    @classmethod
    def _is_review_passed(cls, review_text: str) -> bool:
        """Check if review indicates pass or pass_with_notes."""
        return cls._parse_review_conclusion(review_text) in ("pass", "pass_with_notes")

    def sync_existing_deliveries(self, states: dict[str, TaskState]) -> None:
        """
        Inspect real GitHub PR metadata and remote reviews to recognize
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
                    head_branch="main",
                    review_path=str(p.relative_to(self.repo_root)),
                )
                break

        # 2. Recognize stage0-fixes via real PR metadata
        stage0_key = "stage0-fixes:r1"
        if stage0_key not in states:
            target_branch = "task/stage0-review-fix"
            pr_info = self.get_pr_info_for_branch(target_branch)

            head_sha = None
            pr_number = 2
            if pr_info:
                head_sha = pr_info.get("head_sha")
                pr_number = pr_info.get("number", 2)
            else:
                # Try reading local or origin ref
                try:
                    res = subprocess.run(
                        ["git", "rev-parse", f"origin/{target_branch}"],
                        cwd=str(self.repo_root),
                        capture_output=True,
                        text=True,
                    )
                    if res.returncode == 0:
                        head_sha = res.stdout.strip()
                except Exception:
                    pass

            if head_sha:
                matching_review = None
                if reviews_dir.exists():
                    for p in reviews_dir.glob(f"pr-{pr_number}-*.md"):
                        if head_sha in p.name:
                            matching_review = p
                            break

                if matching_review:
                    content = matching_review.read_text(encoding="utf-8")
                    if self._is_review_passed(content):
                        status = "done"
                    else:
                        status = "awaiting_review"
                    review_path_str = str(matching_review.relative_to(self.repo_root))
                else:
                    status = "awaiting_review"
                    review_path_str = None

                states[stage0_key] = TaskState(
                    task_id="stage0-fixes",
                    revision=1,
                    status=status,
                    pr_number=pr_number,
                    head_sha=head_sha,
                    head_branch=target_branch,
                    review_path=review_path_str,
                )

        # 3. Check any other task in queue
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

    def find_matching_review(self, st: TaskState, snapshot_sha: str | None = None) -> tuple[Path | None, str | None]:
        """
        Find exact matching review for PR and exact head_sha.
        Returns (local_cached_path, content).
        Cached in .vmv-runner/reviews/ to avoid polluting workspace.
        """
        if not st.pr_number or not st.head_sha:
            return None, None

        target_name = f"pr-{st.pr_number}-{st.head_sha}.md"
        cached_path = self.runner_dir / "reviews" / target_name

        if cached_path.exists():
            try:
                return cached_path, cached_path.read_text(encoding="utf-8")
            except Exception:
                pass

        git_dir = self.repo_root / ".git"
        if git_dir.exists():
            # A review record may be committed to the PR branch itself. Check this
            # before origin/main so the runner can react without merging the PR.
            if (
                st.pr_number == AUTHORIZED_PR_TASK["pr_number"]
                and st.task_id == AUTHORIZED_PR_TASK["task_id"]
                and st.head_branch == AUTHORIZED_PR_TASK["branch"]
            ):
                try:
                    branch_ref = f"origin/{AUTHORIZED_PR_TASK['branch']}"
                    res = subprocess.run(
                        ["git", "show", f"{branch_ref}:reviews/{target_name}"],
                        cwd=str(self.repo_root),
                        capture_output=True,
                        text=True,
                    )
                    if res.returncode == 0 and res.stdout.strip():
                        cached_path.parent.mkdir(parents=True, exist_ok=True)
                        cached_path.write_text(res.stdout, encoding="utf-8")
                        return cached_path, res.stdout
                except Exception:
                    pass

            sha = snapshot_sha or "origin/main"
            try:
                res = subprocess.run(
                    ["git", "show", f"{sha}:reviews/{target_name}"],
                    cwd=str(self.repo_root),
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0 and res.stdout.strip():
                    cached_path.parent.mkdir(parents=True, exist_ok=True)
                    cached_path.write_text(res.stdout, encoding="utf-8")
                    return cached_path, res.stdout
            except Exception:
                pass

        local_p = self.repo_root / "reviews" / target_name
        if local_p.exists():
            try:
                return local_p, local_p.read_text(encoding="utf-8")
            except Exception:
                pass

        return None, None
