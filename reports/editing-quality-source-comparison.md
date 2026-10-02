根据 Codex 复核意见，已对公开源码初审分析完成针对性修正。本报告保留初审时点的边界；后续调用链证据和实际试剪状态分别见 `editing-quality-call-chain.md`、`editing-quality-pilot-progress.md`。报告不包含任何本机绝对路径、真实节目台词及素材细节；上游代码引用均采用真实仓库相对路径与固定 Commit。当前 PR #11 仍保持 draft 状态。

---

# 影视解说部分源码初审与机制对比报告

以下 `waiting_for_local_edit_plan` 及未完成项描述属于初审时点；后续实际验证和修正以 `editing-quality-pilot-progress.md` 为准。

> **前置说明与审计边界**
> 1. **审计性质**：本报告仅为公开 GitHub 源码、提示词与工程架构的部分只读初审，**未在本地部署或运行上游完整产品流水线，不声称完整调用链与成片验证已通过**。
> 2. **客观性原则**：机制设计不直接等同于成片艺术质量，不预设成片优劣与业务指标提升。
> 3. **合规与环境安全**：报告通篇仅引用公开仓库代码，不含本机绝对路径、真实节目台词与素材细节。后台进程生命周期由 Codex 运行包装器负责核验与管理。
> 4. **任务状态**：当前标记为 `waiting_for_local_edit_plan`（PR #11 维持 draft）。AGY 负责通用机制与规则梳理，后续 15 秒同稿受控试剪严格等待 Codex 交付本地画面计划后执行。

---

## 一、 上游仓库基线与许可证核查

| 仓库名称 | 固定 Commit SHA | 开源许可证 | 核心特征定位 |
| :--- | :--- | :--- | :--- |
| **zenstory-ai/video-recap-skills** | `e7eb0a82f13aab930f64a669e91ece78b82f65f5` | MIT License | 规则与契约驱动：定义剪辑工作法，侧重入出点权衡、物理区间重叠拦截与因果序校验。 |
| **linyqh/NarratoAI** | `9fa69e022d4add41205ee385207561df8796b3f1` | MIT License | 工程管线驱动：具备显式 OST 模式分流（纯原声保持原始区间，解说类按 TTS 时长计算）。 |

- **许可证合规性**：两仓库均采用 MIT License，允许设计思路与通用算法逻辑借鉴，当前阶段仅做只读审读与机制研究。

---

## 二、 三方机制对比与风险辨析

### 1. 镜头入出点机制与表演完整性风险
- **zenstory-ai/video-recap-skills**：
  - 在 `creative-editing-playbook.md` [第 60–75 行] 提出“选择时刻而非单选事件”、“晚进早出（最短但完整）”，明确权衡“动作与反应谁更重要”；在 `cut_contract.py` [第 333–424 行] 的 `normalize_clip_plan` 中保持蒙太奇排列，设置最小剪辑时长约束。
- **linyqh/NarratoAI**：
  - 在 `clip_video.py` [第 674–686 行] 及 [第 759–780 行]，针对 `OST=0`（纯解说）和 `OST=2`（解说+原声混合），入出点按 `calculated_end_time = start_time + tts_duration` 计算；但对于 `OST=1`（纯原声保留片段，见 [第 731–736 行]），则显式保留切片原始的 `start_time` 与 `end_time`。其管线存在分流逻辑，不能整体概括为单一被动裁剪。
- **当前 VMV 现状与确切风险**：
  - 在 `src/vmv/voice_timeline.py` [第 170–174 行]，入出点计算为 `src_in = shot["source_in_sec"]` 与 `src_out = src_in + alloc_frames / fps`。需澄清：`source_in_sec` 本身是用户或策划已选择的入点，并非永远固定在候选片段头部。
  - **确切风险辨析**：分配机制将语音超出部分按帧数摊派到镜头后，若计算出的 `src_out` 落在关键动作尚未落地或表情反应未完成的时间点，可能导致关键表演被提前截断；该现象属于分配逻辑与戏剧节奏的匹配风险，非已证明的代码漏洞。
  - **工程现状澄清**：当前 15 秒样片由独立脚本 `render-opening.py` 渲染，该脚本已支持显式指定 `start_sec` 与 `frames`；正式的 `voice_timeline.py` 并非本次样片确定的直接根因。

---

### 2. 镜头重复、物理区间重叠与因果约束
- **zenstory-ai/video-recap-skills**：
  - 在 `cut_contract.py` [第 71–80 行]，定义了 `_overlaps_authored_range`，以底层时间戳物理区间 `[raw_start, raw_end]` 进行交叉碰撞校验，重叠即抛出异常阻断；在 `narrative_selection.py` [第 162–244 行] 对必选证据节点与偏序因果进行前置检查。
- **当前 VMV 现状辨析**：
  - 需澄清：当前系统并非无重复检查，除 `src/vmv/retrieval.py` 检索层过滤外，`src/vmv/production.py` 与 `src/vmv/voice_timeline.py` 均包含 `shot_id` 维度的重复校验。
  - **关键悬疑点**：若上游切片产生的时间区间存在子区间交叉，现有管线在全链路是否严格具备底层连续物理时间戳 `[source_in_sec, source_out_sec]` 的防重叠拦截，仍有待完整调用链进一步复核确认。

---

### 3. 声音角色与音画协同分流
- **zenstory-ai/video-recap-skills**：
  - 在 `creative-editing-playbook.md` [第 99–116 行] 提出了 `audio_owner`（声音归属）与 `narration_job`（旁白功能）的设计理念，用于指引 Agent 在解说与原声留白之间取得平衡。
- **linyqh/NarratoAI**：
  - 在 `clip_video.py` [第 880–980 行] 实现了 `OST=0`（静音混解说）、`OST=1`（原声片段独立保活）、`OST=2`（解说与原声混音对齐）的分流剪辑模式。
- **当前 VMV 现状**：
  - 在 `src/vmv/render.py` [第 263–271 行]，切片渲染时硬编码带有 `-an` 参数。
  - **处置原则**：原片声音保留与 `audio_owner`/OST 机制作为后续长期演进观察项，**本轮试验严格固定声音，不新增音频接口，不修改音频代码**。

---

### 4. 画面检索与任务匹配
- **对比观察**：
  - `zenstory-ai/video-recap-skills` 采用分镜职责与上下文编排；NarratoAI 借助 Vision 描述由大模型完成匹配。
  - 当前 VMV 在 `src/vmv/retrieval.py` [第 16–29 行] 采用 2-gram 字符级重合基线，在缺乏视觉动作语义理解时，需依赖人工或上层规划补充画面任务属性。

---

## 三、 本轮优先试验项选择（严格控制为三项，声音完全固定）

在严格遵守“固定原片、口播正文、用户原音、语速、字幕、标题、背景声音及 15 秒总长（375 帧）”边界下，选定以下 3 个具备明确源码支撑且可在本地可控验证的试验项：

### 试验项 1：精确入出点——关键动作锚定与晚进早出
- **上游源码/文档依据**：
  - `zenstory-ai/video-recap-skills` 中 `creative-editing-playbook.md` [第 60–75 行]（跳过无效铺垫，出点完整保留情绪与微反应）。
- **可验证操作**：
  - 针对当前 15 秒样片使用的 `render-opening.py`，消费画面计划中的精确入点（`start_sec`）与时长（`frames`），确保入出点锚定在关键动作发生或眼神交流落地处，规避因机械分配导致的动作半截截断。

### 试验项 2：对源区间重叠与视觉重复复核
- **上游源码/文档依据**：
  - `zenstory-ai/video-recap-skills` 中 `cut_contract.py` [第 71–80 行]（基于物理区间的 `_overlaps_authored_range` 防碰撞校验）。
- **可验证操作**：
  - 在试剪执行前，按素材来源对画面计划中的 `[source_in_sec, source_out_sec]` 检查越界、正时长和区间重叠；不要求原片时间随成片顺序单调递增，允许有依据的蒙太奇重排。物理区间不重叠不能证明视觉内容不重复，仍需实际看片复核。

### 试验项 3：在不改文案的前提下为镜头定义证据/表演/反应任务
- **上游源码/文档依据**：
  - `zenstory-ai/video-recap-skills` 中 `creative-editing-playbook.md` [第 66 行]（明确区分动作承载者与倾听反应者）与 `narrative_selection.py` [第 162–244 行]（分镜任务校验）。
- **可验证操作**：
  - 在保持现有 15 秒口播文案逐字不改的前提下，为分配到各分句的镜头明确标注叙事功能（如“动作证据镜头”、“人物反应镜头”），验证是否能够解决当前 2-gram 检索带来的画面叙事意图模糊问题。

---

## 四、 下一步动作与任务状态

1. **当前状态**：`waiting_for_local_edit_plan`，GitHub PR #11 维持 **draft**。
2. **下一步协作动作**：
   - 等待 Codex 产出脱敏的本地 15 秒画面计划（明确包含物理源区间、精确入出点、画面任务定义与 375 帧总帧数分布）。
   - 收到本地画面计划后，AGY 在同稿同音的严格受控条件下，调用本地脚本执行 15 秒同稿试剪对比。
3. **审计说明**：本阶段未触发独立环境部署，进程运行由 Codex 运行包装器统一核验，成片视听质量待输出后由人工对比裁决。

## 五、源码定位与Codex复核补充

报告中的上游文件简称对应固定commit下的以下真实路径：

- Video Recap：`skills/video-script/references/creative-editing-playbook.md`、`skills/video-script/SKILL.md`、`skills/video-cut/scripts/cut_contract.py`、`skills/video-cut/scripts/narrative_selection.py`。
- NarratoAI：`app/services/clip_video.py`、`app/services/generate_video.py`、`app/services/generate_narration_script.py`。

Codex已核对报告涉及的入出点计算、OST分流、区间重叠判断及VMV既有shot_id去重位置，并修正原片时间单调性这一不必要限制。公开源码审读不证明真实样片已采用对应路径，也不证明视觉重复已经消除。上游其余裁剪/合成调用链仍需继续核查，报告不能作为完整源码审计通过的证据。
