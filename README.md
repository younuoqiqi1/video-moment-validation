> 阶段3色块流程已获用户确认通过；真实素材检索质量仍待验证。

> 当前：阶段5本地模拟配音短样片首版已实现，待用户验收；全套237项测试通过。真实素材全量检索质量与正式音色仍待验证。详见[阶段5报告](reports/stage5-voice-render.md)。

# 数智博主视频镜头检索技术验证

这个项目只验证一条最小链路：

> 口播脚本 → 候选镜头 → 人工选镜头 → 结构化生产单 → TTS 与 FFmpeg 合成 MP4

当前阶段、完成度和阻塞项见 [`PROGRESS.md`](PROGRESS.md)。技术边界和验收口径见 [`docs/superpowers/specs/2026-09-29-video-moment-validation-design.md`](docs/superpowers/specs/2026-09-29-video-moment-validation-design.md)。

Notion 同步看板：[老周聊《潜伏》技术验证｜进度与阶段验收](https://app.notion.com/p/3ea82d45c32181f7991bc19f2050cb17)

## 当前状态

2026-10-02：用户已授权阶段2，口播拆段、自动生成画面需求与审核编辑支持`vmv script`和`vmv script-review`。先用 `examples/stage2-script-sample.txt` 合成稿验证，完整测试129项通过，真实AGY生成3段合成稿已跑通。使用方式及未验证项见[阶段2报告](reports/stage2-script-breakdown.md)。阶段2合成流程已由用户验收，真实稿泛化未独立验证；阶段1画面验收保留，阶段3已授权并交付合成首版。

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


## 阶段4：镜头编排与生产单

从阶段3候选目录生成独立编辑页，口播和候选画面同页展示。每段可勾选多个镜头，调整原片入出点，并用上下按钮改变采用顺序。导出 `selection.json` 后，命令行再次校验并写出生产单：

```bash
vmv production-edit --candidates outputs/stage3/candidates.json --output outputs/stage4/editor
vmv build-order --script outputs/stage2/script.json --candidates outputs/stage4/editor/candidates.json --catalog data/work/catalog.json --selection outputs/stage4/editor/selection.json --media outputs/stage1/media_manifest.json --output outputs/stage4/production-order.json
```

将浏览器导出的选择文件保存到命令指定位置；命令中的脚本、目录与媒体清单必须是候选文档绑定的原始版本。输出目录或生产单已存在会拒绝覆盖，修改选择后请指定新输出文件。选择文件使用 `segments[].shots[].shot_id/in_sec/out_sec`，入出点采用原片绝对秒数。

生产单保存原片时间、累计时间线和输入文件哈希。`ready_for_tts` 表示可交给下一步；时间线目前按所选原片长度累计，尚未按口播配音定时，不能据此判定最终节奏合格。


## 阶段5：本地配音模拟与短样片

先使用认可的本地语音文件运行链路；目前不调用云端TTS，不使用示例API密钥。导入时复制音频快照并绑定原始生产单、段落和音频哈希；渲染前再次核对原片及音频：

```bash
vmv audio-import --order outputs/stage4/production-order.json --audio seg-001=outputs/voice/seg-001.wav --output outputs/stage5/audio
vmv render --order outputs/stage4/production-order.json --media-root . --audio-manifest outputs/stage5/audio/audio_manifest.json --output outputs/stage5/rendered
```

多段稿为每段重复提供 `--audio SEG_ID=FILE`，必须完整覆盖生产单段落。支持WAV/AIFF/AIF/MP3。渲染输出 `sample.mp4`、`subtitles.srt`、`voice-timeline.json`、`render-report.json`，保留源文件和已有输出；已有输出目录会拒绝覆盖。

每段按实际配音长度向上对齐25fps帧数，按已选镜头容量分配，每镜头至少一帧，从所选入点截取并保持原速。配音超出可用素材、镜头数量超过可分配帧数时失败，不补长镜头或冻结画面。原片声音不混入模拟配音；原片内嵌字幕保留，另加口播字幕。

依赖FFmpeg、ffprobe和可用中文字体。Mac自动使用Heiti SC/Songti SC，Linux尝试本地Noto CJK；其他字体可通过 `--subtitle-font FILE --subtitle-font-name FAMILY` 显式指定，不自动下载或安装。文字缺字时报错，不把方框字幕作为成功产物。最终FFmpeg使用受管临时工作目录，支持空格和单引号路径；进程组在失败、超时和退出时清理。单次导入/渲染处理总限60秒，样片上限180秒；较长或复杂素材需要分段处理，不能绕过超时限制。

短样片只验证合成链路，正式声音、完整稿匹配与裁切叙事仍需验收。云TTS适配等待具体产品文档与本地配置。
