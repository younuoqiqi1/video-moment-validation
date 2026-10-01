# 官方 Mac 自动执行链路交付（2026-10-01）

- implementation_complete：是。
- review_status：awaiting_review。
- real_mac_execution：not_verified。
- end_to_end_coordination：not_verified。
- user_acceptance：not_recorded。

## 已实现

独立 `codex/mac-actions` 分支 push 自动派发固定 JSON 任务；GitHub 托管机器先校验任务，专用 Mac 官方 runner 执行。本机 gh 用户身份发送真实开始/完成回执，附 Actions run 链接、任务 ID、挑战值、平台、代码提交和退出状态；按运行/attempt/阶段去重。现有聊天 webhook 继续使用，不新建或禁用自动化。

只支持不读取素材的挑战文件探针及 PR #5 固定已授权提交的阶段 1 预览。禁止任意命令、未知模式、未知 PR 和未授权代码版本。只上传安全 `result.json`；不上传素材、帧图、HTML、机器路径、凭据或原始日志。原项目不切换、不覆盖，预览运行在独立 checkout。

安装器通过已登录 gh 下载并核验官方适配 Mac 的包，在用户目录注册/启用官方 launchd 服务。未知安装内容不覆盖；本机配置不进 Git。后续重任务优先交 AGY 的分工已记录，但 coding CLI 尚未接入本流程，不能声称已自动派发 coding。

## 独立验证（Linux）

- 基线 `.venv/bin/python -m pytest -q`：19/19 通过。
- 先新增测试运行：11 个失败，原因是执行器/安装器模块尚不存在；实现后全量 30/30 通过（0.26 秒）。
- 覆盖：拒绝越界任务与代码、真实临时文件摘要（Mac 平台边界以测试替身模拟）、拒绝 Linux 伪称 Mac、回传失败不宣称链路成功、错误摘要不泄露私密路径、官方包来源与校验和门禁。
- `actionlint v1.7.12 -shellcheck='' .github/workflows/mac-local.yml`：通过；明确配置自托管标签 vmv-mac。未运行 shellcheck。
- 派发 JSON 实际 validate-only：退出 0。
- Linux 实际探针：退出 1、blocked/not_sent；安装器：退出 1、not_macos。确认不会将 Linux 冒充 Mac。
- 实际读取官方 `actions/runner` 最新发布元数据，安装器选中 `actions-runner-osx-arm64-2.337.0.tar.gz`，取得有效 64 字符 SHA256；没有在 Linux 安装该 Mac 包。
- `git diff --check`：通过。

## 尚待实机确认

Mac 的首次安装、注册权限、服务在线、实际自动接单、挑战摘要、两条 GitHub 回执和聊天通知未独立验证。安装说明在 `docs/mac-actions.md`；收到真实 run 后逐项核对。没有这些证据就不能写“协同跑通”。

不自动合并任何 PR，不认定阶段 1 验收通过，不进入阶段 2。
