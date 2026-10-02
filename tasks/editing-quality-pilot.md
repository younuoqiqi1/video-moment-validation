# AGY：影视解说源码对比与15秒同稿试剪

日期：2026-10-02（Asia/Shanghai）。用户已明确授权按照本方案执行并在GitHub新增任务；不要重复询问是否开始。

## 目标与第一批范围

基于现有 video-moment-validation 流程，研究 Video Recap Skills 与 NarratoAI 的实际剪辑机制，验证借鉴方法是否能改善现有节目开头的吸引力。第一批只做到“源码对比、最多三个优先改法、固定口播和配音的15秒画面对照”，交付后停在 awaiting_review。

- 研究仓库：`https://github.com/zenstory-ai/video-recap-skills` 和 `https://github.com/linyqh/NarratoAI`。NarratoAI不是NarratorAI-Studio的云端CLI Skill。
- 代码依赖：现有 `codex/stage5-voice-render` 分支（PR #10），不要基于缺少阶段2–5功能的main实现业务改动，不合并既有PR。
- 现有基准：最新去重的15秒开头；基准、素材和原音的本机绑定由Codex提供，不把旧重复镜头版作为唯一对照。
- 固定原片、口播正文、用户原音、语速、字幕正文/样式/时间、标题、背景声音及15秒片长；第一轮仅改变画面选择、顺序及入出点。
- 用当前Codex完成真实素材画面理解与视听策划，不接MiMo，不新增GPT API依赖。AGY负责公开源码研究、通用实现与本地执行；缺少Codex提供的具体画面计划时先完成源码报告，明确 `waiting_for_local_edit_plan`，不能编造镜头或代替用户重写口播。

## 必须遵守

1. 每次coding调用明确指定 `--model gemini-3.8-flash-high`，不能使用隐式默认模型。
2. 先读本任务、`tasks/execution-policy.md`、`tasks/automatic-review-handoff.md`及Git状态。保护已有修改，使用独立任务分支；不重做已完成阶段。
3. 原片、真实口播、用户音频、字幕、具体素材剪辑单和机器绝对路径只留本机，不上传GitHub、不打印到云端模型请求。允许提交公开源码引用、通用方法、合成测试和脱敏报告。
4. 不先安装两个完整产品或系统依赖；先按固定commit只读审计。核验LICENSE，记录方法参考和实际代码复用的区别。
5. 所有新增脚本退出清理、强制超时≤60秒；必要服务使用随机端口；结束前终止本次启动的临时进程，不杀其他任务进程。
6. 不自动修改文案、原音、语速或旧版本，不重新TTS，不重做镜头检测算法。不因素材不足而循环画面或把冷峻反应标作暴怒。
7. 测试通过、匹配分数和切镜头数量都不能当作内容验收；不宣称完播率提高。

## 执行步骤与产物

### 1. 固定来源与审读

- 固定两个上游仓库commit SHA和LICENSE。
- Video Recap优先读 `skills/video-script/SKILL.md`、`references/creative-editing-playbook.md` 以及 `video-cut`/`video-assemble` 的实际调用链。
- NarratoAI优先追踪 `app/services/generate_narration_script.py`、`script_service.py`、`clip_video.py`、`generate_video.py`及关联prompts。
- 比较：故事递进、镜头任务、入出点、表演/反应镜头、重复使用、原声/旁白分工。区分Agent决策、提示词要求、代码实现和未经验证的宣传。
- 交付 `reports/editing-quality-source-comparison.md`：每项包含commit/文件位置、机制、我们当前差异、可验证改法。最多选三个优先试验项。

### 2. 核验当前代码风险

重点检查 `src/vmv/voice_timeline.py::plan_timeline` 的帧分配和截取、`src/vmv/retrieval.py::rank_candidates` 与辅助路径、`src/vmv/production.py` 的镜头顺序与来源绑定、`src/vmv/render.py` 的原声与配音行为。

当前观察是时间线可能按选段可用长度分配口播时长，从入点截取；检索有相邻字匹配基线；现有视频渲染路径可能丢弃原声。均需以实际代码与入口核实，不能把这些观察当作已证明的成片根因，也不能据此把所有模块一起重构。

### 3. 15秒受控试剪

- Codex先提供已核实的本机画面计划，包含源区间、具体时刻、画面任务、入出点和帧数。AGY只需消费本地计划，不把私人内容提交模型。
- 优先复用现有15秒渲染工具，采用新编辑单和新输出目录。375帧、25fps、1920×1080、15.000秒；逐项核对声音、字幕和基准一致。
- 检查源区间越界、相同源区间重叠、画面重复、关键动作/反应被截断；不只按shot_id去重。
- 交付本机A/B视频、可追溯剪辑单、机械验证与未验证项；Git只提交脱敏的 `reports/editing-quality-pilot.md`。
- 完整原速观看和接点复核由Codex与用户完成；15秒仅检验开头，不宣称验证全片叙事。

## 后续门槛

用户认可对照收益后，扩展到现有口播首个完整叙事段，再把有效规则做成最小正式源码改动。文案修改、原声混音实验与直接部署上游工具分别作为后续变量，不自动执行。

## GitHub交付与状态

- 对应任务分支为 `codex/editing-quality-pilot`，基于阶段5分支。只提交任务文档、公开来源报告、通用代码及必要合成测试。
- 完成可交付部分后更新同一任务PR，不重复开交付PR。交付标题以 `AGY：` 开头，描述引用本任务与报告，状态 `awaiting_review`，列出实际检查、等待本地计划或素材、尚未看片等限制。
- 任务下发PR仅有文档时保持draft；不得把任务文件推送成功当成AGY开工或效果验证通过。不得自行合并。
- 缺本地画面计划时报告 `waiting_for_local_edit_plan`；实际工具失败时给具体错误和解除条件，不自行换模型、绕过权限或宣称全部完成。

## 第一批完成判据

- [x] 两个仓库实际commit、许可证和源码调用链已核对。
- [x] 至少一份可审查的来源对比报告，包含最多三个有证据支持的改法。
- [x] 当前时间线风险与最新样片执行入口已区分。
- [x] 本机对照输入固定，画面计划存在后才试剪，输出保持原音原稿且不覆盖旧版。
- [x] 全片解码、帧数、字幕/声音不变检查与观看验收分开记录。
- [x] 阶段报告与同一任务PR更新，明确awaiting_review或具体等待条件，临时进程已清理。

## 后续明确授权与交付

用户要求连续执行五步，认可 15 秒 B 版后，已扩展完整开场段，并按后续明确反馈增加原声、简易配乐、短字幕和原片摄影机移动。完整段最初沿用旧录音，用户纠正后已改用其原始口播 MP3，不重新 TTS。

通用显式计划及执行入口已由 AGY 指定模型实现，336 项全量测试通过。正式入口重现获认可的 15 秒 B：源区间一致、ASS 字节一致、PCM 音频一致，逐帧图像 SSIM 为 1。具体状态及内容反馈见 `reports/editing-quality-pilot-progress.md`；没有部署上游完整产品或改造默认理解模型。PR 保持 draft，不自行合并。
