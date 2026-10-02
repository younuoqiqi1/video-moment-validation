# 裁剪、合成与脚本调用链复核

固定版本沿用源码初审报告中的两个 commit。下述为静态源码证据，未部署上游产品，不宣称其成片更好。

## Video Recap

`skills/video-cut/scripts/cut_cli.py` 的 `main` 调用 normalize、镜头/句边界吸附，再在最终区间上执行 `check_required_evidence`；blocking 会在渲染前退出。否则进入 `cut_render.py::build_edited_source_video`，按 `source_start/source_end` 使用 FFmpeg trim，统一几何规格后 concat。策划契约、边界调整和实际渲染是三个步骤，不能只把文档规则当成运行实现。

`skills/video-assemble/scripts/assemble.py::assemble_video` 进入声音模式分支，并通过 `timeline_emit` 输出时间线。`adopted-packet-copy` 分支直接映射已有音轨，区别于重混/归一化的路径。此机制适合我们的画面单变量实验：已确认的音轨直接复用，以解码样本哈希核对，避免重新编码成为隐藏变量。

`skills/video-script/references/creative-editing-playbook.md` 要求保留具体必要证据、表演落点；跨场并置不得冒充同场因果，钩子不得夸张承诺正文没有兑现的结果。这些是策划层责任；区间合法和文件可解码无法替代它们。

## NarratoAI

`app/services/script_service.py::ScriptGenerator.generate_script` 当前实际委派到 `documentary/frame_analysis_service.py::generate_documentary_script`，并不直接完成影视叙事策划。服务先做分批视觉观察，再转换为 Markdown，进入 `generate_narration_script.py::generate_narration`，该入口优先走 `llm/migration_adapter.py`，异常时回退旧实现。两个路径均引用 documentary 的 narration_generation 提示词。帧分析服务生成最终列表时将 OST 置为 2。

`app/services/prompts/documentary/narration_generation.py` 强调钩子、具体动作、情绪、信息点和留白，也给出通用时长模板。这是提示词要求，不是经过实测的完播收益。`clip_video.py` 根据 OST 处理源区间与 TTS 时长，OST=1 保留原段；OST=0/2 按旁白长度调整。不能把所有模式概括为固定按 TTS 裁剪。

## 对本项目的结论

1. 首先借鉴显式时刻、画面任务和必要表演范围，保留已有拆镜头/理解能力；不接 MiMo，不假设当前聊天模型可以作为程序 API。
2. 受控对照应冻结实际音轨，而不只冻结 TTS 参数。重复合成音轨即使参数相同也须核验；本地试验已改用 A 音轨包复制。
3. 物理区间防重叠、总帧数与关键范围包含关系可进入通用校验；内容吸引力、真实因果和文案兑现仍需要看片反馈。

当前 `retrieval.py` 除 2-gram 基线外具备 assisted_rankings 路径，本轮不替换检索架构。也未证明正式 voice_timeline 是历史样片平庸的根因。

审读范围覆盖上述实际入口、选段契约、渲染函数、OST分支与当前提示词。未做第三方运行验证、全仓安全审计或效果排行榜。
