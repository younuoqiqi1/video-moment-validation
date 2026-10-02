# 数智博主视频镜头检索技术验证

这个项目只验证一条最小链路：

> 口播脚本 → 候选镜头 → 人工选镜头 → 结构化生产单 → TTS 与 FFmpeg 合成 MP4

当前阶段、完成度和阻塞项见 [`PROGRESS.md`](PROGRESS.md)。技术边界和验收口径见 [`docs/superpowers/specs/2026-09-29-video-moment-validation-design.md`](docs/superpowers/specs/2026-09-29-video-moment-validation-design.md)。

Notion 同步看板：[老周聊《潜伏》技术验证｜进度与阶段验收](https://app.notion.com/p/3ea82d45c32181f7991bc19f2050cb17)

## 当前状态

2026-10-02：用户已授权阶段2，口播拆段、自动生成画面需求与审核编辑支持`vmv script`和`vmv script-review`。先用 `examples/stage2-script-sample.txt` 合成稿验证，完整测试129项通过，真实AGY生成3段合成稿已跑通。使用方式及未验证项见[阶段2报告](reports/stage2-script-breakdown.md)。阶段1画面验收和阶段2真实稿/浏览器验收均未完成；阶段3未授权。

以下为早期环境记录，历史测试数量不代表当前结果：

- 执行方式已改为用户 Mac 本地运行，AGY 编码，Codex 监督与审查
- 已建立独立的本地 Git 仓库，并在项目内配置 Python 3.12 虚拟环境
- 完成阶段 0（L0）：CLI 模块 `vmv status` 与离线 HTML/JSON 环境报告生成
- 自动化测试（`pytest tests/test_cli.py`）6/6 全部通过
- 当前环境实测：Python 3.12、Git、AGY、FFmpeg 7.0、ffprobe 7.0 全部达标就绪（阶段 0 已通过）
- 等待 20–30 分钟测试视频投入 `data/input/` 与确认后的口播稿

镜头理解先由当前 GPT 会话读取本地导出的抽帧与字幕包完成，再将结果导回本地程序；程序不使用 Plus 额度调用 GPT API。全流程无需云端计算服务器，但 AGY、阿里云 TTS 与 GitHub 仍需要联网。

## 数据约定

测试视频、TTS 密钥和输出成片不提交到 Git：

- `data/input/`：测试视频、字幕、人物参考图
- `data/work/`：抽帧、切片、索引等中间文件
- `outputs/`：候选片段、生产单、MP4 和验证报告
- `.env`：阿里云 TTS 等密钥
