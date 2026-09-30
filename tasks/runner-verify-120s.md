# AGY 任务：启用并验证 GitHub 定时同步

## 用户目标

用户希望 Codex 写入 GitHub 的新任务或更新后，本地 Mac 上的 AGY 能自动发现并继续处理，不再需要用户手动转发。项目已有用户级 launchd 方案，目标间隔为每 120 秒检查一次。

本任务只完善并实测“定时发现/拉取 GitHub 更新”能力。继续使用现有 runner_service.py 与 PR #3 实现，不重复创建第二套定时器。不要合并 PR，不要绕过阶段验收。

## 先明确现有实现的边界

当前 PR #3 的实现使用 launchd 的 StartInterval=120 和 RunAtLoad=true；每次运行 python -m vmv runner once，现有 fetch_remote_main() 执行的是 git fetch origin main。

这表示代码已经写了“每 120 秒检查一次 main”，不等于用户 Mac 上已经安装并运行；并且只 fetch origin/main 不会发现只存在于 PR 分支的提交。Codex 刚写入的 tasks/stage1-preview-followup.md 在 PR #5 的 feat/stage1-media-import 分支，不在 main。不能把 main-only fetch 描述成会自动发现该 PR 分支更新。

## 执行要求

1. 在用户 Mac 先检查本地仓库路径、Git 工作区、AGY CLI、现有 com.vmv.runner 服务状态和最近日志；保留用户未提交内容，不启动重复 AGY 实例。
2. 若服务未安装，按项目已有命令安装用户级 launchd 服务，间隔 120 秒。先核对 python -m vmv runner --help 和 install --help 的实际参数，再使用项目虚拟环境 Python 与仓库绝对路径。无需 sudo，不改其他 launchd 服务。
3. 明确实现“定时发现当前授权任务更新”的分支来源。至少让已授权的 PR #5 feat/stage1-media-import 上的 tasks/stage1-preview-followup.md 能被发现；不得仅轮询 main 后声称已同步该任务。可复用已授权任务队列和隔离 worktree，或提交一个范围更小、明确只读 fetch/比对的实现方案。
4. 拉取必须安全：不自动 merge、reset 或覆盖用户当前工作区；只处理已明确授权的任务和指定 PR/分支；每个任务只运行一个 CLI 实例。对未知分支/文件不自动执行。
5. 实测一个完整轮询周期：记录安装结果、服务是否 loaded、配置中的 120 秒间隔、至少两次真实检查的时间，以及 GitHub 远端分支 SHA 是否被本机 fetch 到。用 PR #5 已授权任务作为只读发现样例；不要重复执行其中的媒体处理任务来证明“拉取成功”。
6. 增加或更新最小测试，覆盖间隔配置、指定分支更新能否发现、未经授权的分支/文件不执行、当前工作区改动不被覆盖、重复轮询不重复派发。单元测试不能代替真实 Mac launchd 证据。
7. 更新 reports/local-runner-probe.md 与 PR #3 描述，明确区分：代码配置完成、服务已安装、真实轮询验证、AGY 是否实际启动后续任务。失败就写实际阻塞，不得只凭 launchctl list 或 pytest 宣称验证通过。

## 进度与门禁

开始编码后，在 PR #3 留真实进度说明；改动推送到 PR #3 后等待 Codex 复核。不要合并 PR #3/#4/#5，不要自动开始阶段 2。AGY 实际接到 PR #5 的阶段 1 补充任务后，仍须按 PR #5 任务要求工作并等 Codex 复核。
