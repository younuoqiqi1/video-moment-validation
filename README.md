# 数智博主视频镜头检索技术验证

这个项目只验证一条最小链路：

> 口播脚本 → 候选镜头 → 人工选镜头 → 结构化生产单 → TTS 与 FFmpeg 合成 MP4

当前阶段、完成度和阻塞项见 [`PROGRESS.md`](PROGRESS.md)。技术边界和验收口径见 [`docs/superpowers/specs/2026-09-29-video-moment-validation-design.md`](docs/superpowers/specs/2026-09-29-video-moment-validation-design.md)。

Notion 同步看板：[老周聊《潜伏》技术验证｜进度与阶段验收](https://app.notion.com/p/3ea82d45c32181f7991bc19f2050cb17)

## 当前状态

- 执行方式已改为用户 Mac 本地运行，AGY 编码，Codex 监督与审查
- 当前只有项目文档与 Git 历史，尚未实现检索、配音、成片功能
- 从 [`LOCAL_START.md`](LOCAL_START.md) 开始；本地执行修订优先于旧计划中的云端安排
- 等待核验 Mac 上的 AGY、Python、FFmpeg 与登录状态
- 已有 Git 历史，但尚未关联或推送 GitHub 仓库
- 等待 20–30 分钟测试视频与确认后的口播稿

镜头理解先由当前 GPT 会话读取本地导出的抽帧与字幕包完成，再将结果导回本地程序；程序不使用 Plus 额度调用 GPT API。全流程无需云端计算服务器，但 AGY、阿里云 TTS 与 GitHub 仍需要联网。

## 数据约定

测试视频、TTS 密钥和输出成片不提交到 Git：

- `data/input/`：测试视频、字幕、人物参考图
- `data/work/`：抽帧、切片、索引等中间文件
- `outputs/`：候选片段、生产单、MP4 和验证报告
- `.env`：阿里云 TTS 等密钥
