"""Environment checking and report generation."""

import html
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from vmv.stages import StageResult

REQUIRED_TOOLS = ["python", "ffmpeg", "ffprobe", "git", "agy"]


def get_system_info() -> dict[str, str]:
    """Retrieve OS platform and CPU architecture information."""
    sys_name = platform.system()
    mac_ver = ""
    if sys_name == "Darwin":
        release, _, _ = platform.mac_ver()
        mac_ver = f"macOS {release}" if release else "macOS"
    return {
        "platform": sys_name,
        "os_version": mac_ver or platform.release(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
    }


def probe_tool_version(cmd: list[str], timeout_sec: float = 5.0) -> tuple[bool, str | None, str | None]:
    """
    Run command to probe version using argument list and timeout.
    Returns (success, version_output_or_none, error_message_or_none).
    """
    executable = cmd[0]
    resolved = shutil.which(executable)
    if not resolved:
        return False, None, f"未在环境变量 PATH 中找到可执行命令: {executable}"

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec,
        )
        if proc.returncode == 0:
            output = proc.stdout.strip() or proc.stderr.strip()
            first_line = output.splitlines()[0] if output else "已安装"
            return True, first_line, None
        else:
            err_msg = (proc.stderr.strip() or proc.stdout.strip() or f"退出码 {proc.returncode}")
            return False, None, f"执行异常: {err_msg}"
    except subprocess.TimeoutExpired:
        return False, None, f"探测超时（超过 {timeout_sec} 秒）"
    except Exception as exc:
        return False, None, f"探测失败: {exc}"


def check_environment(timeout_sec: float = 5.0) -> dict[str, Any]:
    """Check all required dependencies and system environment."""
    sys_info = get_system_info()
    tools: dict[str, dict[str, Any]] = {}
    missing_items: list[str] = []
    errors: list[str] = []

    # 1. Python check
    major, minor, micro = sys.version_info[0], sys.version_info[1], sys.version_info[2]
    py_ver = f"{major}.{minor}.{micro}"
    py_valid = (major, minor) >= (3, 12)
    tools["python"] = {
        "name": "Python",
        "required": True,
        "installed": True,
        "version": py_ver,
        "path": sys.executable,
        "valid": py_valid,
        "error": None if py_valid else f"需要 Python >= 3.12，当前版本为 {py_ver}",
    }
    if not py_valid:
        missing_items.append("Python >= 3.12")
        errors.append(f"Python 版本不符合要求: 当前为 {py_ver}，需 >= 3.12")

    # 2. FFmpeg check
    ff_ok, ff_ver, ff_err = probe_tool_version(["ffmpeg", "-version"], timeout_sec=timeout_sec)
    tools["ffmpeg"] = {
        "name": "FFmpeg",
        "required": True,
        "installed": ff_ok,
        "version": ff_ver,
        "path": shutil.which("ffmpeg"),
        "valid": ff_ok,
        "error": ff_err,
    }
    if not ff_ok:
        missing_items.append("ffmpeg")
        errors.append(f"FFmpeg 缺失或异常: {ff_err}")

    # 3. ffprobe check
    ffp_ok, ffp_ver, ffp_err = probe_tool_version(["ffprobe", "-version"], timeout_sec=timeout_sec)
    tools["ffprobe"] = {
        "name": "ffprobe",
        "required": True,
        "installed": ffp_ok,
        "version": ffp_ver,
        "path": shutil.which("ffprobe"),
        "valid": ffp_ok,
        "error": ffp_err,
    }
    if not ffp_ok:
        missing_items.append("ffprobe")
        errors.append(f"ffprobe 缺失或异常: {ffp_err}")

    # 4. Git check
    git_ok, git_ver, git_err = probe_tool_version(["git", "--version"], timeout_sec=timeout_sec)
    tools["git"] = {
        "name": "Git",
        "required": True,
        "installed": git_ok,
        "version": git_ver,
        "path": shutil.which("git"),
        "valid": git_ok,
        "error": git_err,
    }
    if not git_ok:
        missing_items.append("git")
        errors.append(f"Git 缺失或异常: {git_err}")

    # 5. AGY (Antigravity CLI) check
    agy_ok, agy_ver, agy_err = probe_tool_version(["agy", "--version"], timeout_sec=timeout_sec)
    tools["agy"] = {
        "name": "Antigravity CLI (agy)",
        "required": True,
        "installed": agy_ok,
        "version": agy_ver,
        "path": shutil.which("agy"),
        "valid": agy_ok,
        "error": agy_err,
    }
    if not agy_ok:
        missing_items.append("agy")
        errors.append(f"AGY CLI 缺失或异常: {agy_err}")

    overall_status = "passed" if len(missing_items) == 0 else "failed"

    return {
        "system": sys_info,
        "tools": tools,
        "missing_items": missing_items,
        "errors": errors,
        "overall_status": overall_status,
    }


def generate_html_report(env_data: dict[str, Any]) -> str:
    """Generate self-contained Chinese HTML report without external CDN dependencies."""
    sys_info = env_data["system"]
    tools = env_data["tools"]
    missing = env_data["missing_items"]
    status = env_data["overall_status"]
    is_passed = status == "passed"

    badge_color = "#10b981" if is_passed else "#ef4444"
    status_text = "通过 (All Passed)" if is_passed else "未通过 (Requirements Missing)"

    tool_rows = []
    for tool_key, item in tools.items():
        name = html.escape(str(item.get("name", tool_key)))
        installed = item.get("installed", False) and item.get("valid", False)
        ver = html.escape(str(item.get("version") or "-"))
        path = html.escape(str(item.get("path") or "-"))
        err = html.escape(str(item.get("error") or ""))
        
        status_tag = (
            '<span style="color: #059669; font-weight: bold;">✔ 已就绪</span>'
            if installed
            else '<span style="color: #dc2626; font-weight: bold;">✘ 缺失/未达标</span>'
        )
        extra = f'<div style="color: #b91c1c; font-size: 12px; margin-top: 4px;">{err}</div>' if err else ""

        tool_rows.append(
            f"<tr>"
            f"<td><strong>{name}</strong></td>"
            f"<td>{status_tag}</td>"
            f"<td><code style='background:#f1f5f9;padding:2px 6px;border-radius:4px;'>{ver}</code></td>"
            f"<td style='font-size:12px;color:#64748b;'>{path}{extra}</td>"
            f"</tr>"
        )

    tools_html = "\n".join(tool_rows)

    remediation_section = ""
    if missing:
        items_li = "".join(f"<li><strong>{html.escape(m)}</strong></li>" for m in missing)
        remediation_section = f"""
        <div style="margin-top: 24px; padding: 16px; background-color: #fef2f2; border-left: 4px solid #ef4444; border-radius: 4px;">
            <h3 style="margin-top: 0; color: #991b1b; font-size: 16px;">待修复/安装项清单</h3>
            <ul style="color: #7f1d1d; margin-bottom: 8px;">
                {items_li}
            </ul>
            <p style="color: #4b5563; font-size: 13px; margin-bottom: 0;">
                提示：若缺少 FFmpeg，可在 Mac 上使用 <code>brew install ffmpeg</code> 或下载静态包放置于 PATH 路径。
            </p>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>阶段 0：环境与工具核验报告 (Stage 0 Environment)</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            background-color: #f8fafc;
            color: #1e293b;
            margin: 0;
            padding: 32px 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 860px;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
            padding: 32px 40px;
            border: 1px solid #e2e8f0;
        }}
        h1 {{
            font-size: 24px;
            font-weight: 700;
            margin-top: 0;
            margin-bottom: 12px;
            color: #0f172a;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 9999px;
            color: #ffffff;
            font-weight: 600;
            font-size: 14px;
            background-color: {badge_color};
            margin-bottom: 24px;
        }}
        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            background: #f8fafc;
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 28px;
            border: 1px solid #e2e8f0;
        }}
        .meta-item {{
            font-size: 13px;
        }}
        .meta-item span {{
            color: #64748b;
            display: block;
            margin-bottom: 2px;
        }}
        .meta-item strong {{
            color: #1e293b;
            font-size: 14px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
        }}
        th, td {{
            text-align: left;
            padding: 12px 14px;
            border-bottom: 1px solid #e2e8f0;
            font-size: 14px;
        }}
        th {{
            background: #f1f5f9;
            color: #475569;
            font-weight: 600;
        }}
        tr:hover {{
            background: #fafafa;
        }}
        .footer {{
            margin-top: 32px;
            padding-top: 16px;
            border-top: 1px solid #e2e8f0;
            color: #94a3b8;
            font-size: 12px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>数智博主视频镜头检索 - 本地环境核验报告</h1>
        <div class="badge">{status_text}</div>

        <div class="meta-grid">
            <div class="meta-item">
                <span>操作系统</span>
                <strong>{html.escape(sys_info.get("os_version", "macOS"))}</strong>
            </div>
            <div class="meta-item">
                <span>CPU 架构</span>
                <strong>{html.escape(sys_info.get("architecture", ""))}</strong>
            </div>
            <div class="meta-item">
                <span>平台内核</span>
                <strong>{html.escape(sys_info.get("platform", ""))}</strong>
            </div>
        </div>

        <h2 style="font-size: 18px; margin-bottom: 8px;">工具链与依赖检查</h2>
        <table>
            <thead>
                <tr>
                    <th style="width: 25%;">工具 / 组件</th>
                    <th style="width: 20%;">状态</th>
                    <th style="width: 25%;">版本</th>
                    <th style="width: 30%;">路径与详情</th>
                </tr>
            </thead>
            <tbody>
                {tools_html}
            </tbody>
        </table>

        {remediation_section}

        <div class="footer">
            数智博主视频镜头检索技术验证 (Video Moment Validation) · 阶段 0 产物
        </div>
    </div>
</body>
</html>
"""


def validate_output_paths(output_json_path: Path) -> tuple[Path, Path]:
    """
    Validate that output_json_path is a .json file and distinct from HTML.
    Raises ValueError or OSError with Chinese explanation if invalid.
    """
    if output_json_path.suffix.lower() != ".json":
        raise ValueError(
            f"输出报告路径必须以 .json 结尾（不区分大小写），实际提供: '{output_json_path}'"
        )

    try:
        resolved_json = output_json_path.resolve()
    except (OSError, RuntimeError) as exc:
        raise OSError(f"路径解析失败（符号链接循环或权限异常）: '{output_json_path}'，原因: {exc}")

    try:
        resolved_html = resolved_json.with_suffix(".html")
    except (OSError, RuntimeError) as exc:
        raise OSError(f"HTML 关联路径解析失败: '{output_json_path}'，原因: {exc}")

    if resolved_json == resolved_html:
        raise ValueError(
            f"JSON 与 HTML 报告路径冲突（两者完全相同）: '{resolved_json}'"
        )

    return resolved_json, resolved_html


class ReportPublishError(OSError):
    """Exception raised when publishing reports fails, with rollback details."""

    def __init__(
        self,
        message: str,
        original_error: Exception,
        rollback_errors: list[str] | None = None,
        preserved_backups: list[str] | None = None,
        dangling_artifacts: list[str] | None = None,
    ):
        super().__init__(message)
        self.original_error = original_error
        self.rollback_errors = rollback_errors or []
        self.preserved_backups = preserved_backups or []
        self.dangling_artifacts = dangling_artifacts or []


def write_status_reports(output_json_path: Path, env_data: dict[str, Any]) -> tuple[Path, Path]:
    """
    Write JSON and HTML status reports with path validation and rollback protection.
    Single-file atomic replacement with best-effort rollback on failure.
    If rollback of a backup fails, the backup file is strictly preserved and reported.
    Returns (target_json, target_html).
    """
    json_path, html_path = validate_output_paths(output_json_path)
    parent_dir = json_path.parent

    # 1. Ensure parent directory exists
    try:
        parent_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"无法创建输出目录: '{parent_dir}'，原因: {exc}")

    # 2. Write HTML to temporary file first (random temp file to prevent overwrite attacks)
    import tempfile

    html_content = generate_html_report(env_data)
    tmp_html_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent_dir,
            prefix=".tmp_html_",
            suffix=".tmp",
            delete=False,
        ) as f_html:
            f_html.write(html_content)
            tmp_html_path = Path(f_html.name)
    except OSError as exc:
        raise OSError(f"创建或写入临时 HTML 报告失败: '{html_path}'，原因: {exc}")

    # 3. Write JSON to temporary file
    tmp_json_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent_dir,
            prefix=".tmp_json_",
            suffix=".tmp",
            delete=False,
        ) as f_json:
            json.dump(env_data, f_json, ensure_ascii=False, indent=2)
            tmp_json_path = Path(f_json.name)
    except OSError as exc:
        if tmp_html_path and tmp_html_path.exists():
            try:
                tmp_html_path.unlink()
            except OSError:
                pass
        raise OSError(f"创建或写入临时 JSON 报告失败: '{json_path}'，原因: {exc}")

    # 4. Check pre-existence of target files to allow transactional rollback without corrupting pre-existing user files
    html_existed = html_path.exists()
    json_existed = json_path.exists()

    bak_html: Path | None = None
    if html_existed and html_path.is_file():
        try:
            with tempfile.NamedTemporaryFile(
                dir=parent_dir, prefix=".bak_html_", suffix=".bak", delete=False
            ) as f_bak:
                bak_html = Path(f_bak.name)
            shutil.copy2(html_path, bak_html)
        except OSError as exc:
            for p in (tmp_html_path, tmp_json_path):
                if p and p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
            raise OSError(f"备份既有 HTML 报告失败: '{html_path}'，原因: {exc}")

    bak_json: Path | None = None
    if json_existed and json_path.is_file():
        try:
            with tempfile.NamedTemporaryFile(
                dir=parent_dir, prefix=".bak_json_", suffix=".bak", delete=False
            ) as f_bak:
                bak_json = Path(f_bak.name)
            shutil.copy2(json_path, bak_json)
        except OSError as exc:
            for p in (tmp_html_path, tmp_json_path, bak_html):
                if p and p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
            raise OSError(f"备份既有 JSON 报告失败: '{json_path}'，原因: {exc}")

    # 5. Dual publish with rollback protection
    html_published = False
    json_published = False
    rollback_errors: list[str] = []
    preserved_backups: list[str] = []
    dangling_artifacts: list[str] = []

    try:
        os.replace(tmp_html_path, html_path)
        html_published = True
        tmp_html_path = None

        os.replace(tmp_json_path, json_path)
        json_published = True
        tmp_json_path = None

        # Success! Clean up backup files
        if bak_html and bak_html.exists():
            try:
                bak_html.unlink()
            except OSError:
                pass
        if bak_json and bak_json.exists():
            try:
                bak_json.unlink()
            except OSError:
                pass

        return json_path, html_path

    except Exception as exc:
        # ROLLBACK: 单文件原子替换，失败时尽力回滚；回滚失败保留备份并报告
        # 1. 清理未被替换的临时生成文件
        for p in (tmp_html_path, tmp_json_path):
            if p and p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

        # 2. 回滚 HTML: 若存在旧文件备份则尝试恢复；若为本次新发布则尝试撤回删除
        if html_published:
            if bak_html and bak_html.exists():
                try:
                    os.replace(bak_html, html_path)
                    bak_html = None  # 恢复成功，旧文件已归位
                except OSError as restore_err:
                    preserved_backups.append(str(bak_html))
                    dangling_artifacts.append(str(html_path))
                    rollback_errors.append(
                        f"还原旧 HTML 报告失败: 目标 '{html_path}' 可能残留本次生成内容，原始备份已安全保留在 '{bak_html}'，恢复错误: {restore_err}"
                    )
            elif not html_existed and html_path.exists():
                try:
                    html_path.unlink()
                except OSError as unlink_err:
                    dangling_artifacts.append(str(html_path))
                    rollback_errors.append(
                        f"撤回新发布的 HTML 报告失败: 残留文件 '{html_path}'，撤回错误: {unlink_err}"
                    )

        # 3. 回滚 JSON: 若存在旧文件备份则尝试恢复；若为本次新发布则尝试撤回删除
        if json_published:
            if bak_json and bak_json.exists():
                try:
                    os.replace(bak_json, json_path)
                    bak_json = None  # 恢复成功，旧文件已归位
                except OSError as restore_err:
                    preserved_backups.append(str(bak_json))
                    dangling_artifacts.append(str(json_path))
                    rollback_errors.append(
                        f"还原旧 JSON 报告失败: 目标 '{json_path}' 可能残留本次生成内容，原始备份已安全保留在 '{bak_json}'，恢复错误: {restore_err}"
                    )
            elif not json_existed and json_path.exists():
                try:
                    json_path.unlink()
                except OSError as unlink_err:
                    dangling_artifacts.append(str(json_path))
                    rollback_errors.append(
                        f"撤回新发布的 JSON 报告失败: 残留文件 '{json_path}'，撤回错误: {unlink_err}"
                    )

        # 4. 清理未受保护的剩余临时备份（恢复失败的备份已被加入 preserved_backups，严禁删除）
        if bak_html and bak_html.exists() and str(bak_html) not in preserved_backups:
            try:
                bak_html.unlink()
            except OSError:
                pass
        if bak_json and bak_json.exists() and str(bak_json) not in preserved_backups:
            try:
                bak_json.unlink()
            except OSError:
                pass

        err_parts = [f"发布报告失败: {exc}"]
        if rollback_errors:
            err_parts.append("回滚发生异常: " + "；".join(rollback_errors))

        raise ReportPublishError(
            "；".join(err_parts),
            original_error=exc,
            rollback_errors=rollback_errors,
            preserved_backups=preserved_backups,
            dangling_artifacts=dangling_artifacts,
        )


def run_status_stage(output_json_path: Path, timeout_sec: float = 5.0) -> StageResult:
    """Execute Stage 0 status check and produce reports."""
    # 1. Validate output path before performing probes or creating files
    try:
        target_json, target_html = validate_output_paths(output_json_path)
    except (ValueError, OSError, RuntimeError) as exc:
        return StageResult(
            stage="stage0_environment",
            status="failed",
            artifacts=[],
            errors=[f"输出路径校验未通过: {exc}"],
            details={
                "error_type": "invalid_path",
                "overall_status": "failed",
                "errors": [f"输出路径校验未通过: {exc}"],
            },
        )

    # 2. Check environment
    env_data = check_environment(timeout_sec=timeout_sec)

    # 3. Write status reports
    artifacts: list[str] = []
    write_error: str | None = None
    try:
        json_path, html_path = write_status_reports(target_json, env_data)
        artifacts = [str(json_path), str(html_path)]
    except (OSError, ValueError, RuntimeError) as exc:
        write_error = f"文件系统异常: {exc}"
        if isinstance(exc, ReportPublishError):
            if exc.rollback_errors:
                env_data["rollback_errors"] = exc.rollback_errors
            if exc.preserved_backups:
                env_data["preserved_backups"] = exc.preserved_backups
            if exc.dangling_artifacts:
                env_data["dangling_artifacts"] = exc.dangling_artifacts

    errors = list(env_data.get("errors", []))
    if write_error:
        errors.append(write_error)
        env_data["overall_status"] = "failed"
        env_data["errors"] = errors
        env_data["report_generation_status"] = "failed"
        env_data["report_generation_error"] = write_error
        artifacts = []
        status = "failed"
    else:
        status = env_data["overall_status"]

    return StageResult(
        stage="stage0_environment",
        status=status,
        artifacts=artifacts,
        errors=errors,
        details=env_data,
    )
