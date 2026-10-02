# 第六阶段指标与剪辑经验记录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 已授权执行方式为 Codex 限定任务、AGY CLI 执行，显式指定 gemini-3.8-flash-high。

**Goal:** 用最新完整成片及返工证据完成第六阶段指标报告，保存以后可整理成 skill 的剪辑修订记录。

**Architecture:** 本阶段只交付报告和结构化指标，不新增后台、CLI 或自动剪辑功能。测得的数据与用户反馈分开记录，缺失的分母、操作时间和账单费用使用 null，并说明补测方法。

**Tech Stack:** Markdown、JSON、现有本地成片验证文件。

**Spec:** docs/superpowers/specs/2026-09-29-video-moment-validation-design.md 的第六节指标；用户最新完整成片与修改记录要求。

## Global Constraints

- 最新片长 156.32 秒、3908 帧、25fps、1920×1080；完整解码、最终音轨一致性、时轴更新验证通过。
- 候选可用率达标线 ≥80%；片长 ≤180 秒；没有全量 top3 审核分母，不可推算命中率。
- 最新完整片主观验收待用户观看，授权进入阶段6不自动等于所有阶段已验收。
- 原片、口播、原声台词、精确源时间、机器路径和私有日志不得发送给 AGY 或提交 GitHub。
- 所有项目修改限定任务文件，不动 src/tests，不覆盖历史状态和来源不明文件；不新增 API、TTS 或渲染任务。
- AGY 调用使用受管进程组，单轮总超时58秒并清理子进程。

## Review Focus

- 未审核候选不可填0或100%；已选素材不能当作top3检索成功。
- 物理区间无重叠不能当作场景不重复，也不能当作情节因果正确。
- 工程验证通过不能当作主观内容已认可，未知费用不能填免费。
- 镜头计数、替换数量和反馈项数量不能当作完整人工操作次数。
- 本片字幕和接点参数为案例参数；通用原则必须包含检查方法和适用边界。

### Task 1: 阶段6指标与结论

**Files:** reports/stage6-evaluation.md、reports/stage6-metrics.json。
**Interfaces:** 读取现有脱敏报告；输出已测指标、unknown字段、达标判定与继续开发建议。
- [x] Codex 完成报告和JSON（AGY指定模型报告调用及最小健康检查均超时，无落盘），候选可用率/覆盖率/人工操作分钟/分阶段耗时费用为null；不虚构。
- [x] Codex 对照最新本地verification、manifest及设计阈值核验JSON与结论。

### Task 2: 修订案例及未来skill资料

**Files:** reports/editing-adjustment-playbook.md、PROGRESS.md、README.md。
**Interfaces:** 案例采用“问题、原因、修改、验证、用户反馈、可复用规则、边界”；记录流程和可检查原则，非正式skill安装。
- [x] Codex 写调整案例（只修改文档，程序代码保持不变）、输入输出约定、决策流程与检查清单，并在README/PROGRESS顶部增加最新状态链接，保留历史。
- [x] Codex 检查事实、通用规则与本片参数区别、隐私和相对链接。
- [x] 选择性提交至原PR分支，读取GitHub验证；不合并、不将待评指标写为通过。
