# Mac Local Execution Implementation Plan

> **For agentic workers:** 使用 executing-plans 的逐任务检查方式；实际编码执行者是用户本地 AGY，Codex 在当前聊天监督。每个阶段完成后等待用户验收。

**Goal:** 在用户 Mac 建立可验证的项目入口，并将已有最小视频验证计划交给本地 AGY 实现。

**Architecture:** 复用原 Python/FFmpeg 文件流程。L0 完成本地环境报告；L1 实现本地 AGY 检查点与额度续跑；后续按已有素材、脚本、检索、生产单、成片阶段推进。GPT 分析使用文件往返，不接 GPT API。

**Tech Stack:** Mac Apple silicon、Python 3.12 或更高、FFmpeg/ffprobe、Git、用户现有 AGY；实际工具版本在 L0 核验。

**Spec:** `docs/superpowers/specs/2026-09-29-video-moment-validation-design.md`

## Global Constraints

- 单作品、20–30 分钟素材、确认后的口播稿、每段最多 3 个候选、成片不超过 3 分钟。
- 阶段验收前暂停；无 GPT API，不自动调用当前聊天；视频与凭据不进入 Git。
- 本地工具缺失须报告，不擅自进行系统安装。项目依赖限于 `.venv`。
- 原计划的 GPU、云端磁盘和云端账号要求不适用于本地执行。

## Review Focus

- 工具缺失：报告确切缺失项，退出失败，不写出全通过报告。
- 中文和空格路径：不使用拼接 shell 字符串执行探测命令。
- 本地用户修改：先查看 Git 状态，保留用户工作，不批量暂存未知文件。
- 没有 GitHub remote：允许本地检查点，禁止伪造推送成功。
- 额度等待或进程中断：保持状态，不能跳过阶段验收；网络、权限和登录失败不是额度错误。

## L0：环境报告（本次唯一执行任务）

**Files:** 沿用旧计划 Task 1 的 `pyproject.toml`、`src/vmv/cli.py`、`src/vmv/stages.py`、`src/vmv/report.py`、`tests/test_cli.py`；新增 `reports/stage0-review.md`。

**Interfaces:** `python -m vmv status --output outputs/stage0/environment.json`。产生同目录的 `environment.html`；JSON 至少包含 platform、architecture、Python/FFmpeg/ffprobe/Git/AGY 版本、各检查结果和缺失项。工具运行使用参数数组和超时。

- [ ] 只读检查 Mac 环境、Git 状态和已有目录；AGY 本身完成任务是登录可用的证据，不检查原始凭据。
- [ ] 编写缺少 FFmpeg 时失败、AGY 探测超时、正常环境成功、包含中文和空格输出路径的测试；运行并确认未实现时失败。
- [ ] 实现环境探测与 CLI；成功退出 0，缺少必需工具或 Python 版本不符退出非 0；所有失败生成可读中文说明。
- [ ] 在项目虚拟环境运行 `python -m pytest tests/test_cli.py -v`，然后实际运行 status 命令，打开 HTML。真实 Mac 环境未执行的项标为未验证。
- [ ] 写阶段审查报告，更新 PROGRESS.md，提交本阶段文件，报告最终提交 ID；无 remote 仍允许本地提交。
- [ ] 停在 awaiting_review，交回报告、代码改动和检查结果。

## L1：AGY 本地额度续跑（L0 验收后执行）

沿用旧计划 Task 0 的状态结构与 tests/test_agy_runner.py，在 Mac 实测 AGY 的 JSON 输出、真实错误格式和会话恢复方式，不能凭文档猜测额度格式。只续跑同一个已获准的任务，完成后进入 awaiting_review。

使用明确刷新时间；没有刷新时间只记录保守重试策略，不宣称五小时一定恢复。普通失败 blocked；断电、休眠和重启后重新检查状态，不启动重复进程。限制重试次数并保留上次错误。GPT 自动化创建暂缓，没有可用调用入口时 waiting_gpt_review，不能伪造 GPT 审查通过。

## 后续阶段

L1 验收后依次使用旧计划 Task 2–7。检索阶段须增加抽帧/字幕分析包导出、GPT 描述与排序结果校验导入，保留镜头 ID 和时间码；记录 lexical_baseline 和 GPT_assisted 两条结果，不将简单词语重叠称为语义检索。正式素材、脚本和 TTS 文档未就绪时报告阻塞。

## 优先级更新：先验证能力，旧 Demo 接入后置（2026-09-30）

用户已明确：先完成视频技术验证，旧 Demo 的迁移和接入留到后面。

- 当前不迁移旧 Demo、不开发完整操作系统、不把旧界面接入作为任何验证阶段的前置条件。
- 先沿现有阶段验证素材读取、口播拆段、候选镜头检索、人工选择与生产单、阿里云配音及 MP4 合成，最后记录指标并判断效果。
- 验证时使用现有命令、文件报告或必要的简单预览页面，让用户能检查候选镜头和成片；只做验收需要的最少界面。
- 旧 Demo 复用待核心验证完成、效果可判断后再安排，届时单独确认接入范围。
- 本次只调整旧 Demo 的优先级；阶段0修正复核、L1安排和逐阶段验收规则仍按当前计划执行。AGY 不得据此跳过审查或提前进入下一阶段。
