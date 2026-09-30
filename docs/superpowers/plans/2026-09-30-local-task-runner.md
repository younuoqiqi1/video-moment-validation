# 本地 AGY 自动接任务实施计划

> **For agentic workers:** 实际执行者为用户Mac上的AGY，按 executing-plans 逐项执行。用户已于2026-09-30明确要求实现，不再询问是否开始。

**Goal:** 在Mac后台检查Git已授权任务并启动AGY CLI；关闭AGY App后仍可工作，完成通过PR触发Codex审查。
**Architecture:** Python单次检查器加用户级launchd定时启动，独立运行目录和任务worktree，不修改用户正在编辑的checkout。任务白名单与状态持久化，PR审查按编号和提交匹配。
**Tech Stack:** 现有Python 3.12、Git、Mac用户级launchd、实际已安装AGY CLI；不接GPT API。
**Spec:** 本文件中的授权范围与行为约束，以及 tasks/execution-policy.md、tasks/automatic-review-handoff.md。

## 授权与执行顺序

本任务现在明确授权实现、测试及在用户级后台启用。先完成当前阶段0 R1–R3工作并提交其PR，再在独立分支实现本任务；不要求再次询问用户，也不自动推进视频阶段。当前授权仅新增本地自动化，不合并任何PR，不改变其他阶段验收门禁。

## 全局约束

- 每120秒检查一次；睡眠期间不保证运行，唤醒后补检查。Mac必须开机、有网络且CLI登录可用。
- 只接本仓库已明确授权的任务；发现任意新Markdown不等于获准执行。
- 每任务只运行一个CLI实例；跨进程文件锁，原子保存状态；崩溃后标interrupted并核实原进程，不盲目自动重跑。
- 不把登录、网络、权限失败归为额度问题；只有实测明确额度信号才进入quota_wait，有限重试。真实格式未核对前不得编造自动恢复能力。
- launchd仅写用户 ~/Library/LaunchAgents 的本任务文件，不使用sudo、不修改其他服务、不给系统全盘权限。
- 命令用参数数组，不通过shell拼接任务文本；路径支持中文与空格。日志不打印环境变量、cookies、令牌或原始凭据。
- 后台验证任务不能编辑视频工程业务代码；任务worktree与用户主目录改动隔离。

## 代码与文件职责

- src/vmv/runner.py：任务白名单、状态机、锁、远程变更读取、CLI启动。
- src/vmv/runner_service.py：launchd模板、用户级安装/状态/停止。
- src/vmv/cli.py：增加 runner 子命令。
- tests/test_runner.py：调度、锁、审查匹配、错误与去重。
- tests/test_runner_service.py：中文/空格路径及安装停止。
- tasks/queue.json：已授权任务清单，Git可读；凭据与本地CLI路径不入此文件。
- reports/local-runner-review.md：真实Mac证据与未验证项。
- 本地配置和状态放 .vmv-runner/ 并加入忽略规则；保留原有忽略内容。

## 任务1：核对真实CLI并实现最小执行器

- [ ] 检查Git状态、现有AGY路径/version/help；实测CLI是否支持无GUI、非交互提示、工作目录、退出状态。先用独立临时Git目录执行无副作用任务。写入脱敏后的精确调用形式。
- [ ] 若所谓CLI只是打开App或不能无GUI执行，报告blocked和实测证据，不伪造后台实现成功，也不自动安装替代代理。
- [ ] 先写并运行失败测试：task id及revision相同只启动一次；未知任务不启动；两实例只有一实例持锁；shell元字符作为字面提示；进程非零退出标blocked而非完成。
- [ ] 实现 run_once(config_path: Path) -> int；CLI argv从本地核验配置读取，固定可执行程序，任务内容从指定仓库文件读取。
- [ ] 实现持久状态：task_id、revision、status、attempt、pid、started_at、last_error、pr_number、head_sha、review_path；状态为ready/running/awaiting_review/blocked/interrupted/quota_wait/done。
- [ ] 用模拟CLI跑测试，再在Mac用真实CLI跑无副作用探测；不只凭pytest宣称CLI登录可用。

## 任务2：接Git任务及审查，保留验收门禁

tasks/queue.json结构：
{"version":1,"tasks":[{"id":"stage0-fixes","revision":1,"path":"reviews/stage0-task.md","authorized":true}]}

- [ ] 测试远程暂时不可达保留状态；已有任务完成不重复；未经授权的新文件不启动；脏主工作区保持原样。
- [ ] 安全fetch origin/main并通过git show读指定任务和queue，不在用户checkout自动pull/merge/reset。任务独立worktree；检测与正在工作的AGY分支冲突则blocked，不启动重复修复。
- [ ] 首次接入先识别已有PR/交付并登记，不重复阶段0修正或下载。若真实GitHub读取不可用，明确blocked而不是假装去重。
- [ ] 测试审查PR或head_sha不匹配不继续；同一提交的修正意见仅派发一次；通过仅记录done，不自动开始未经授权新阶段。
- [ ] 读取reviews/pr-<编号>-<完整sha>.md；已有历史stage0-task作为已授权修正。自动处理当前任务范围的request_changes，通过后停在用户验收边界。
- [ ] 已有Codex自动审查PR触发保持不变；不要额外创建GPT调用或定时任务。
- [ ] 新交付按automatic-review-handoff开标题AGY开头的PR，报告awaiting_review；禁止自动合并。

## 任务3：安装后台服务并端到端验证

- [ ] 增加 python -m vmv runner once / status / install / stop 命令；install使用实际Python、仓库及配置绝对路径。
- [ ] launchd设置StartInterval=120和RunAtLoad，运行单次检查器；输出到本地忽略日志。启动前校验CLI登录、配置和任务锁。
- [ ] 测试服务配置XML转义、路径含空格中文；重复install不产生重复服务；stop只停止本任务服务。
- [ ] 启用用户级服务，记录launchctl状态。当前AGY自身编写安装时不可导致第二实例自动重跑本任务。
- [ ] 在独立验证队列安排无业务副作用probe任务，关闭AGY App，观察后台CLI仍成功执行并生成本地标记。如执行者不能关闭自身App，使用独立终端/后台验证记录；不能完成就标“关闭App后未验证”，不声称达标。
- [ ] 验证新任务一次执行、完成PR、Codex报告回Git；真实端到端未完成的部分标未验证，测试假PR不冒充真实事件。
- [ ] 执行本任务测试及CLI相关回归；报告具体命令、结果、启动/停止方式、Mac未验证项。
- [ ] 更新PROGRESS.md事实状态。提交 AGY：本地自动接任务 的PR，等待Codex审查；服务只运行白名单已授权工作，不自动越过视频阶段验收。

## 最小交付验收

必须有真实CLI无GUI探测、120秒后台检查、重复启动防护、既有交付去重、授权任务范围限制、可停止服务及真实Mac报告。quota恢复格式未实测可单独标未完成，不能阻塞先交付上述基础自动接任务能力。

不要求用户反复转发报告；任务/修正通过Git，阶段验收结果仍由用户明确给出。
