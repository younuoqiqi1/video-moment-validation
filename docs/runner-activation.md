# Mac 本地自动接单：一次启动

此文档只针对用户 Mac 上现有的 `video-moment-validation` Git 仓库。云端提交代码、PR 评论或 `@codex` 不会自动安装或启动本地服务；Mac 需要先执行一次启动命令。之后 launchd 每 120 秒运行一次：先从 GitHub 拉取接单程序、主分支任务准据和 PR #5 分支，再只核验并处理唯一授权的 PR #5 补充任务。

在 Mac 自带的“终端”里，整段复制执行一次：

```bash
cd "$HOME/Documents/video-moment-validation" && mkdir -p .vmv-runner && git fetch origin '+refs/heads/feat/local-task-runner:refs/remotes/origin/feat/local-task-runner' && git show origin/feat/local-task-runner:scripts/activate_local_runner.py > .vmv-runner/activate_local_runner.py && .venv/bin/python .vmv-runner/activate_local_runner.py
```

成功时会显示 `成功安装并启用后台轮询服务` 和代码版本。原项目当前分支及未提交内容不会被切换、reset 或覆盖；程序代码存放在 Git 忽略的 `.vmv-runner/code` 独立 worktree。PR #5 的执行目录也是独立的，即使原分支正在使用，仍能核对任务；仅在本机忽略目录中链接现有视频和阶段 1 清单，不提交素材。若独立目录有未知文件或未提交修改，启动会停止并保留文件。安装时只替换同名 `com.vmv.runner` 服务。关闭 Antigravity 图形应用后能否继续执行仍需单独探针证明。

核对是否真正开始处理：

```bash
tail -n 30 .vmv-runner/runner.log
```

新日志应出现 `[接单服务] 已更新隔离代码到 ...`，然后是 `[PR 任务授权]`，最后是任务进入 `running` 或明确的阻塞原因。PR #5 中真实新增的“已开始”评论、AGY 子进程 PID 或后续代码提交才能证明 AGY 已经开始。只看到定时拉取或任务发现，不能算开始。任务状态只留本机 `.vmv-runner/state.json`，不得上传凭据或视频素材。

这是一处 Mac 本地的一次操作。Codex 的 Linux 环境只能验证脚本、Git 隔离及测试，无法替 Mac 执行 `launchctl` 或查看真实进程。若启动失败，保留终端里的简短错误文字与新的脱敏日志，供后续修正。

## 不操作终端的办法

在用户已经打开的 AGY 会话发一次下列目标，让 AGY 完成同一个启动步骤：

```text
/goal 在这台 Mac 的 video-moment-validation 项目中，安全拉取 PR #3 的 feat/local-task-runner 最新代码，按照 docs/runner-activation.md 执行一次启动入口。保留当前分支和未提交文件。检查 com.vmv.runner 新日志是否包含最新代码版本，确认“AGY 协同回执”已发到 PR #3；如果没有，检查服务错误与 GitHub 登录并修复。只接已授权的 PR #5 阶段1补充任务，不合并PR，不进入阶段2。真正开始后在PR #5回报，失败时回报阻塞原因。不要再要求用户转发审查意见。
```

新版每次轮询会在 PR #3 报告首次启动及任务状态变化；更新失败、状态文件损坏和轮询异常也会发固定类别的回执。不上传原始日志、路径、素材或凭据，相同版本和状态不重复发送。发帖失败会留本机提示并在下次重试，不能算回执送达。ChatGPT 现已启用本仓库 AGY PR 评论事件通知，真实回执可用于唤醒进度检查；只有收到原始评论或代码更新才算已收到。仅 @codex 或 GitHub 设置保存成功不能证明端到端链路已实测。
