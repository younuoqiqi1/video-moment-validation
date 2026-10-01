# Mac 官方自动接单：安装一次，再用真实任务验证

当前状态：代码和测试已就绪，真实 Mac 安装与自动执行未验证。

用户已授权此方案。保留 PR #3 旧轮询程序及报告，先验证替代链路；不合并 PR #3/#5，不启动视频阶段 2，不把执行完成当作用户验收。

## 工作方式

Codex 更新独立分支 `codex/mac-actions` 的 `tasks/mac-actions/dispatch.json`，GitHub push 自动创建任务。官方 runner 在用户 Mac 接收并执行，使用 Mac 已有 gh 登录把脱敏开始/完成回执写到对应 AGY PR，已有 ChatGPT 评论通知负责接收。文件更新本身不等于 Mac 开工；只有实际 Mac job 和回执可证明执行。

当前固定任务只允许：

- `probe`：PR #3 自动接单探针，真实写入临时挑战文件并计算 SHA256，不读取素材。
- `stage1-preview`：PR #5 已授权的完整清单预览，代码固定为 `39c48d9a87167decb3ab53d5da5d79d6e3bd9c05`。不重跑 import、不改阈值、不做后续阶段。只回传数字；预览和帧图保留本机。

探针完成后，才发送素材任务。新增代码版本或任务类别必须明确更新授权白名单。JSON 不接受命令、机器路径、任意脚本或阶段 2。

## AGY 在 Mac 执行的一次安装

在已经包含真实素材和 `.venv` 的原项目根目录执行。不得 reset/切换/覆盖原项目，先安全 fetch，再把安装器读到临时文件：

```bash
git fetch origin codex/mac-actions
VMV_INSTALL_SCRIPT=$(mktemp -t vmv-actions-install)
git show origin/codex/mac-actions:scripts/install_mac_actions.py > "$VMV_INSTALL_SCRIPT"
.venv/bin/python "$VMV_INSTALL_SCRIPT" --project "$PWD"
rm -f "$VMV_INSTALL_SCRIPT"
```

安装器要求已有 Python 3.12+ 项目虚拟环境和 gh 登录；不自动安装系统依赖、不重新登录、不索取或打印 token。它从官方 `actions/runner` 发布下载适合 M2 的 arm64 包，核对 SHA256，通过本机 gh 获取短期注册凭据，配置专用标签 `vmv-mac`，安装并启动用户级官方服务。凭据与原项目路径保留本机，不进 Git。未知已有安装目录不会覆盖。

如果 gh 无注册 runner 的权限，AGY 报告 `blocked`。用户只需在仓库 **Settings → Actions → Runners → New self-hosted runner → macOS → ARM64** 按官方命令注册，并添加 `vmv-mac` 标签，然后在安装目录执行 `./svc.sh install`、`./svc.sh start`。不要把页面里的注册 token 复制到聊天或仓库。

官方服务目录为本机用户目录下 `.local/share/vmv-actions-runner`。安装器创建本机 `vmv-local.json`，只写本机原项目目录与已有 Python 路径；重复安装保留已有配置。视频任务运行在官方 runner 独立 checkout 中，读取原项目素材和清单。

## 如何验收链路

1. 安装后 GitHub Runners 显示在线，只代表待命。
2. [Actions 页面](https://github.com/younuoqiqi1/video-moment-validation/actions)中 `Mac local task` 的 `Execute on user Mac` job 确实运行；核对 runner 标签 `self-hosted/macOS/vmv-mac`。
3. PR #3 收到同一 run ID 的开始与完成回执，平台为 Darwin，任务 ID 和 nonce 与派发文件一致。独立计算 `SHA256(nonce 的 ASCII 字节)`，等于回执 `probe_sha256`；不能以安装日志或 Linux 模拟测试替代。
4. 下载对应 run 的唯一 `result.json`，核对 `execution_status=completed`、`notification_status=sent`。
5. 当前聊天收到该回执通知，才算“派发→Mac执行→回传→聊天通知”完整成功。

首个 push 任务若在安装之前到达，会等待匹配 Mac runner；若队列超时，AGY 用本机 `gh run list --branch codex/mac-actions --workflow mac-local.yml` 找到原 run ID 后 `gh run rerun <run-id>`。不重复造新任务，不以 rerun 请求成功当作执行成功。

Mac 必须保持联网和唤醒。App 是否打开与官方 runner 无关。机器离线、任务未运行、回传失败都明确报告，不把静默当成成功。

回执沿用本机 gh 用户身份，使原有 GitHub 评论 webhook 能收到；不靠仅 @codex，不新建另一套定时器。评论按 run ID/attempt/阶段去重。GitHub API 或网络失败会保留安全结果并返回非零；同一次执行已完成但回传失败，不称为链路成功。

## 后续分工（用户 2026-10-01 明确要求）

自动接单链路实测通过后，耗 token 的 coding、批量修改和测试优先交 AGY；Codex 负责拆任务、审查与独立验证。同一 bug 连续修三次仍未解决，由 Codex 接手。当前两个固定任务不调用 AGY coding CLI。接入 coding 时复用现有 PR #3 的 CLI 能力，但先在 Mac 核实真实非交互启动/退出行为，再加明确授权的任务适配器，不擅自假设 CLI 参数或把任意远程文本当命令。

官方依据：
- https://docs.github.com/en/actions/concepts/runners/self-hosted-runners
- https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/configure-the-application?platform=mac
- https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/monitor-and-troubleshoot?platform=mac
