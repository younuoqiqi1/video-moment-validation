# AGY 一次安装任务：官方 Mac 自动接单

用户已于 2026-10-01 明确授权开始实施本方案。只安装/验证官方接单链路，不改视频代码、不合并 PR、不进入阶段 2。PR #6：https://github.com/younuoqiqi1/video-moment-validation/pull/6 。

## 立即执行（不再询问是否开始）

在本机包含真实素材和已有 .venv 的原项目根目录执行；保留未提交文件，不切分支、不 reset。不关闭 AGY App，不读取或输出凭据。

```bash
(
  set -e
  git fetch origin refs/heads/codex/mac-actions:refs/remotes/origin/codex/mac-actions
  VMV_INSTALL_SCRIPT=$(mktemp -t vmv-actions-install)
  trap 'rm -f "$VMV_INSTALL_SCRIPT"' EXIT
  git show 0af7bfc161dff8e4c9c9aa04e4509987b191b61f:scripts/install_mac_actions.py > "$VMV_INSTALL_SCRIPT"
  .venv/bin/python "$VMV_INSTALL_SCRIPT" --project "$PWD"
)
```

安装器使用已有 gh 登录，在用户目录安装经过 SHA256 核验的官方 Mac runner 并启用官方用户级后台服务；本机配置、短期注册 token、素材与机器路径不进 Git。若已有未知安装目录或登录/权限不足，记录 blocked 和安全原因，不覆盖、不擅自重登录。

说明：读取 `origin/codex/mac-actions:docs/mac-actions.md`。系统依赖缺失时报告具体缺项；不新增不必要依赖。

## 实际验收

已创建探针 run 36822475573：https://github.com/younuoqiqi1/video-moment-validation/actions/runs/36822475573 。它由 GitHub push 自动触发，目前还没有 Mac 执行证据。安装后不要在 AGY 会话里手动模拟探针；等待官方 Actions 的 `Execute on user Mac` job 自动接收并执行。

任务 ID `mac-probe-20261001-1`，不碰素材。必须出现 PR #3 同一 run 的实际开始/完成回执，并核对 result.json 中 completed/sent 和挑战摘要。在线、安装成功、任务入队均不等于执行完成。若原 run 过期，用 `gh run rerun 36822475573 --repo younuoqiqi1/video-moment-validation` 重新运行原任务，再核查结果。

安装成功或阻塞，在 PR #3 发 `AGY 协同回执：官方接单程序安装完成` 或 `AGY 协同回执：官方接单程序安装阻塞`，附安全状态；不得伪称已开始 coding。真实任务开始/完成评论由本机执行程序自动发送。

## 后续分工

用户要求：链路实测跑通后，耗 token 的 coding、批量修改和测试优先交 AGY；Codex 拆任务、审查和独立验证。同一 bug 连续修三次仍未解决，由 Codex 接手。当前安装/探针任务不调用 coding CLI；CLI 适配需单独实测其非交互运行能力。

本任务文件被同步或读取，不足以证明 AGY 已执行；必须回传真实安装与 Actions job 证据。
