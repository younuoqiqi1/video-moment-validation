# Mac 本地自动接单：一次启动

此文档只针对用户 Mac 上现有的 `video-moment-validation` Git 仓库。云端提交代码、PR 评论或 `@codex` 不会自动安装或启动本地服务；Mac 需要先执行一次启动命令。之后 launchd 每 120 秒运行一次：先从 GitHub 拉取接单程序、主分支任务准据和 PR #5 分支，再只核验并处理唯一授权的 PR #5 补充任务。

在 Mac 自带的“终端”里，整段复制执行一次：

```bash
cd "$HOME/Documents/video-moment-validation" && mkdir -p .vmv-runner && git fetch origin '+refs/heads/feat/local-task-runner:refs/remotes/origin/feat/local-task-runner' && git show origin/feat/local-task-runner:scripts/activate_local_runner.py > .vmv-runner/activate_local_runner.py && .venv/bin/python .vmv-runner/activate_local_runner.py
```

成功时会显示 `成功安装并启用后台轮询服务` 和代码版本。原项目当前分支及未提交内容不会被切换、reset 或覆盖；程序代码存放在 Git 忽略的 `.vmv-runner/code` 独立 worktree。若这个位置有未知文件或未提交修改，启动会停止并保留文件。安装时只替换同名 `com.vmv.runner` 服务。关闭 Antigravity 图形应用后能否继续执行仍需单独探针证明。

核对是否真正开始处理：

```bash
tail -n 30 .vmv-runner/runner.log
```

新日志应出现 `[接单服务] 已更新隔离代码到 ...`，然后是 `[PR 任务授权]`，最后是任务进入 `running` 或明确的阻塞原因。PR #5 中真实新增的“已开始”评论、AGY 子进程 PID 或后续代码提交才能证明 AGY 已经开始。只看到定时拉取或任务发现，不能算开始。任务状态只留本机 `.vmv-runner/state.json`，不得上传凭据或视频素材。

这是一处 Mac 本地的一次操作。Codex 的 Linux 环境只能验证脚本、Git 隔离及测试，无法替 Mac 执行 `launchctl` 或查看真实进程。若启动失败，保留终端里的简短错误文字与新的脱敏日志，供后续修正。
