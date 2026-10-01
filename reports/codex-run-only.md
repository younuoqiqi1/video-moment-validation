# Codex 编码、AGY 运行的任务切换

2026-10-01：按用户选择，PR #5 原编码任务保留为历史，自动执行白名单切换到 `tasks/stage1-codex-local-run.md`。使用新的任务 ID，避免历史任务状态令本次运行被跳过；仍只授权 PR #5 与指定任务文件 SHA，不能扩大阶段范围。AGY 只运行程序、检查本机画面、提交脱敏结果；代码问题交回 Codex。

真实 Mac 启动尚未确认，切换白名单不能替代本机服务启动。

独立 Linux 验证：`python -m pytest -q`，52 passed in 2.71s；`git diff --check` 通过。
