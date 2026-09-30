# 本地 AGY 真实后台执行能力探针报告

- **日期**：2026-09-30（Asia/Shanghai）
- **关联任务**：`tasks/local-runner-probe-first.md`
- **关联审查**：`reviews/pr-3-02629fbae0cf92bec45ae7f694a343f2a5ab4451.md`（R1–R4 修正）
- **分支**：`feat/local-task-runner`
- **状态**：`implementation_complete` / `awaiting_review`

---

## 1. 真实可执行文件与调用参数模板

- **可执行文件路径**：`/Users/yoyotaozhou/.local/bin/agy`
- **版本信息**：`1.2.14`（原生二进制，大小约 187MB）
- **验证支持的参数**：
  - `--print`：非交互式单次运行并输出结果（别名 `-p`、`--prompt`）；
  - `--model gemini-3.8-flash-high`：显式指定项目要求模型（实测 `agy models` 返回并支持）；
  - `--dangerously-skip-permissions`：非交互自动放行工具调用；
  - `--effort`、`--output-format text`。
- **脱敏调用参数模板**：
  ```bash
  /Users/yoyotaozhou/.local/bin/agy --print "<PROMPT>" --model gemini-3.8-flash-high --dangerously-skip-permissions
  ```

---

## 2. 独立终端真实 CLI 探测验证 (探针 1)

- **结论**：`完成` (passed)
- **测试环境**：独立临时 Git 仓库 `/tmp/agy_cli_probe_209bc29f`（与业务代码 100% 隔离）
- **随机标识令牌**：`TOKEN_2c1aa6073cfcdb2c`
- **无副作用探测任务**：
  > 只在当前目录创建 probe-result.txt，文件内容严格且仅写入单行：PROBE_RESULT=TOKEN_2c1aa6073cfcdb2c，严禁修改或操作任何其他文件或父级目录。
- **执行时间与指标**：
  - **启动时间**：`2026-09-30T12:56:18.839522+00:00`
  - **完成时间**：`2026-09-30T12:57:11.983830+00:00`
  - **总耗时**：`53.14 秒`
  - **退出码**：`0`
- **产物与内容精确校验**：
  - 目标文件 `probe-result.txt` 存在：`True`
  - 实际内容：`PROBE_RESULT=TOKEN_2c1aa6073cfcdb2c\n`
  - 仓库内除 `.git` 外的文件列表：仅包含 `['probe-result.txt']`，无其他文件改动。
- **结论核验**：未弹出 GUI 窗口，AGY 成功在非交互模式下驱动大模型并调用文件创建工具完成指定编码任务。

---

## 3. 用户级后台真实 CLI 探测验证 (launchd 探针 2)

- **结论**：`完成` (passed)
- **启动来源**：macOS 用户级 launchd 服务（临时标识 `com.vmv.probe_step5`）
- **执行环境**：独立临时 Git 仓库 `/tmp/agy_bg_probe_d87e2d9c`
- **随机标识令牌**：`TOKEN_BG_96caf0ce8a808e85`
- **实际子进程追踪**：
  - 父级控制器 PID：`76690`
  - 实际 AGY 运行子进程 PID：`76694`
- **执行时间与指标**：
  - **启动时间**：`2026-09-30T12:57:28.556877+00:00`
  - **完成时间**：`2026-09-30T12:57:54.083300+00:00`
  - **总耗时**：`25.53 秒`
  - **退出码**：`0`
- **产物与内容精确校验**：
  - 目标文件 `probe-result.txt` 存在：`True`
  - 实际内容：`PROBE_RESULT=TOKEN_BG_96caf0ce8a808e85\n`
  - 仓库内文件列表：仅 `['probe-result.txt']`
- **服务回收**：探测完成并捕获结果后，立即通过 `launchctl unload` 卸载服务并安全删除临时 plist 文件，无残留孤儿服务。

---

## 4. 原审查 A–F 项对照状态总表

按照 Codex 审查报告 `reviews/pr-3-02629fbae0cf92bec45ae7f694a343f2a5ab4451.md` 的要求，原 A–F 审查项对齐结果如下：

| 审查项 | 对应要求 | 当前状态 | 修复与验证说明 |
|:---|:---|:---:|:---|
| **A 项** | **工作区与分支保护** | **完成** | `TaskState` 新增 `head_branch` 与 `worktree_path`；`prepare_worktree_for_task` 通过 `git worktree list --porcelain` 核验；杜绝 `git worktree add -B`（绝不 reset 分支）、杜绝 `shutil.rmtree`（保留未知目录哨兵文件）；已有分支直接使用 `git worktree add <dir> <branch>` 保留已有 extra commit；非 Git 根目录直接报错 blocked；分支被占用直接报错 blocked。真实临时 Git 仓库测试已全数覆盖通过。 |
| **B 项** | **远程准据与 fetch 同步可靠性** | **完成** | 彻底移除生产代码中的 `PYTEST_CURRENT_TEST` 绕过分支；`run_once()` 显式核验 `fetch_remote_main()`，失败立即记录脱敏诊断并返回 1，保留原任务状态且 CLI 派发次数为 0；成功后固定本轮 `origin/main` 快照 SHA，统一读取 queue/task/review；远程队列缺失或损坏时明确记录诊断并中断，不静默伪装正常；远程撤销授权的任务自动置为 blocked。 |
| **C 项** | **真实 PR 元数据与交付一致性** | **完成** | PR 查询获取完整元数据（`number`、`state`、`draft`、`head_ref`、`head_sha`）；CLI 退出 0 后必须通过 `_verify_delivery` 核对存在 open 且非 draft 的 PR，且 `worktree HEAD == remote branch SHA == PR head_sha`，否则置为 blocked 拒绝进入 `awaiting_review`；`sync_existing_deliveries` 将 PR #2 正确附着到分支 `task/stage0-review-fix`；`_parse_review_conclusion` 严格解析固定结论字段，只接受枚举，杜绝 `not_pass_with_notes` 等误判。 |
| **D 项** | **去重记录永久持久化与无提交保护** | **完成** | `dispatched_reviews` 永久持久化，同一提交审查修改仅派发一次；CLI 执行退出 0 但工作区 HEAD 未产生新提交时，立即标记 blocked，杜绝死循环。 |
| **E 项** | **子进程实时 PID 持久化与异常防护** | **完成** | `on_started` 回调在子进程启动后立即写回 `state.json`；若 `on_started` 发生异常，立即通过 `proc.kill()` 与 `proc.wait()` 回收子进程并返回 1，标记 blocked，杜绝无 PID 记录的子进程裸跑。 |
| **F 项** | **离线/闭门后台执行验证** | **未验证** (已就绪) | 避免在交互开发会话中强杀宿主 Antigravity GUI 导致连接中断，本项实测需由用户在独立原生终端触发；已完成纯 Python 重构（`scripts/verify_offline_probe.py`），支持严格字节比对、真实 GUI 进程（`/Applications/Antigravity.app/Contents/MacOS/Antigravity`）检测以及 launchd 生命周期回收，相关单元测试 8/8 全数通过。 |

---

## 5. 离线/闭门验证程序说明与用户操作指南 (F 项)

验证程序文件：[`scripts/verify_offline_probe.py`](scripts/verify_offline_probe.py)

### 5.1 架构与防漏设计
1. **纯 Python 控制器与 Worker**：完全废弃易发生注入或转义损坏的 shell heredoc，参数通过 Python 数组传递；
2. **字节级精确校验**：
   - 严格比较 `target_file.read_bytes() == f"PROBE_RESULT={token}\n".encode("utf-8")`；
   - 任何前后缀（如 `WRONG PREFIX ...`）、引号或多行内容均判为 False；
3. **宿主 GUI 进程鉴权**：
   - 严格根据 `/Applications/Antigravity.app/Contents/MacOS/Antigravity` 签名检测 GUI 应用是否存在；
   - 明确区分 CLI 进程（`agy`）与 GUI 应用，输出独立字段 `app_closed`、`app_closed_verified` 与证据；
4. **生命周期自动回收**：
   - 控制器在 `finally` 块中显式执行 `launchctl unload -w` 卸载探针服务，并确认删除 plist 文件，不残留任何常驻服务。

### 5.2 用户验证指南
用户若需在关闭 Antigravity 宿主 GUI 下独立核验，请打开 macOS 系统原生 **终端（Terminal.app）**，执行以下单个命令：
```bash
python3 scripts/verify_offline_probe.py
```
**交互过程**：
1. 终端提示服务排期成功并进入 15 秒倒计时；
2. 在 15 秒内完全退出 Antigravity 应用（按 `Cmd + Q`）；
3. 控制器自动监听并输出真实关闭与 CLI 探针结果；
4. 控制器在运行完毕后自动清理临时 launchd 服务与 plist 配置文件。

---

## 6. 自动化测试证据

全量测试执行环境：macOS Darwin (arm64), Python 3.12.14, pytest-9.1.1
执行命令：
```bash
.venv/bin/pytest
```
测试结果：**37/37 passed in 3.77s**
- `tests/test_cli.py`: 6 passed
- `tests/test_offline_probe.py`: 8 passed（字节精确全等、前后缀拒绝、多行/引号拒绝、GUI进程检测、CLI进程区分、Worker成功/超时、Controller清理）
- `tests/test_runner.py`: 19 passed（R1真实Git工作区保留extra commit、保留未知目录哨兵、主checkout脏文件保留、分支占用冲突报错、非Git根目录blocked；R2断网退出并保留状态、远端撤销授权自动blocked、远端队列损坏诊断退出；R3无PR/草稿PR/SHA不一致拒绝awaiting_review、三方一致进入awaiting_review、严格结论解析、启动回调异常终止子进程、PR #2 分支绑定；以及进程中断、去重等流转）
- `tests/test_runner_service.py`: 4 passed

---

## 7. 守则与门禁约束

- **不合并 PR**：保持 PR #1、PR #2、PR #3 处于未合并状态；
- **不推进下一阶段**：严禁越权进入阶段 1（视频处理）；
- **PR #3 状态**：保持 `awaiting_review` 等待 Codex 复核。
