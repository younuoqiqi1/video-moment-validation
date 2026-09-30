# 本地 AGY 自动接任务服务实现与验证报告 [历史归档版本]

> ⚠️ **历史版本提示**：本文档为早期 P1-1 ~ P1-3 实施阶段的历史留存报告。
> 最新经过独立探针验证及 R1–R4 深度修复的准据报告请参阅 [reports/local-runner-probe.md](local-runner-probe.md)。

- **日期**：2026-09-30 (Asia/Shanghai)
- **分支**：`feat/local-task-runner`
- **实施依据**：`docs/superpowers/plans/2026-09-30-local-task-runner.md`、`tasks/execution-policy.md`
- **复核依据**：`reviews/pr-3-8dac98825a1277c252da5b4f2943eeccd55e397c.md` (早期复核)
- **交付目标**：实现并启用本地自动接任务后台服务，形成安全获取远端任务、独立工作区隔离、request_changes 修正闭环的完整流水线，提交 PR 等待 Codex 复核。

---

## 1. 架构与设计规范

### 1.1 组件分工与 P1 缺陷加固
1. **`src/vmv/runner.py`**：
   - **P1-1（远端任务拉取与独立 Worktree 隔离）**：
     - 在排他锁内安全执行 `git fetch origin main`，离线或网络故障时优雅捕获并保留状态，不崩溃不擦除；
     - 优先通过 `git show origin/main:tasks/queue.json` 和 `git show origin/main:<path>` 获取远端队列与任务内容，绝不自动 pull/merge/reset 用户主工作区；
     - 每个任务自动在 `.vmv-runner/worktrees/<task_id>` 建立独立 Git worktree（基于分支 `task/<task_id>`），AGY CLI 的工作目录严格锁定在 worktree 内部，100% 保护用户本地正在编辑的 checkout 与未提交修改；检测到合并冲突时自动标记 `blocked`。
   - **P1-2（PR/SHA 绑定与 request_changes 自动修正派发）**：
     - 任务执行完毕后，自动从 worktree HEAD 解析完整 SHA，并通过 GitHub API 绑定对应 PR 编号；
     - 遇到对应 PR 和 SHA 的 `request_changes` 审查报告时，自动提取审查修改意见，派发带错误上下文的修正执行轮次，递增 `attempt`；
     - 遵循“同一提交的修正意见仅派发一次”，防止循环死循环；修正完成后更新至新的 HEAD SHA 并重新转入 `awaiting_review`。
   - **P1-3（真实子进程 PID 与崩溃重试保护）**：
     - 采用 `subprocess.Popen` 启动 CLI，将真实的操作系统子进程 PID 实时写入持久化状态（杜绝用 runner 自身 PID 冒充）；
     - 检测到异常退出进程时，标记 `interrupted` 并**立即终止本周期轮询**，绝不在同周期内盲目重跑；
     - 处于 `interrupted` 的任务不会被任务循环自动捡起，必须核验现场后由调度器安全处置。
   - **跨进程排他锁**：基于 `fcntl.flock` 在 `.vmv-runner/runner.lock` 实现非阻塞互斥锁，多实例自动安全跳过。
   - **既有交付自动登记**：启动时自动识别既有交付（PR #1 为 `done`，PR #2 为 `awaiting_review`），不产生重复执行。

2. **`src/vmv/runner_service.py`**：
   - 生成符合 macOS 规范的用户级 launchd 配置文件 `~/Library/LaunchAgents/com.vmv.runner.plist`；
   - 路径 XML 字符安全转义，配置 `StartInterval=120` 和 `RunAtLoad=true`；
   - **卸载加固**：`stop_service()` 严格核验 `launchctl unload` 退出码，若卸载失败则保留 Plist 文件并返回明确错误，不伪造停止成功。

3. **`src/vmv/cli.py`**：
   - 包含完整的 `vmv runner once / status / install / stop` 子命令体系。

---

## 2. 真实 Mac 测试与验证证据

### 2.1 自动化单元测试 (pytest)
执行环境：macOS Darwin, Python 3.12.14, pytest-9.1.1
执行命令：
```bash
.venv/bin/python -m pytest tests/ -v
```
测试结果：**26/26 passed in 0.40s**
- `tests/test_cli.py`: 6 passed (阶段0环境核验与错误边界回归)
- `tests/test_runner.py`: 16 passed (互斥锁、白名单、执行转换、非零退出、死进程崩溃检测与当轮停止、审查通过识别、commit SHA 不匹配不通过、request_changes 修正派发与同一提交单次派发限制、done 任务跳过、shell 元字符字面传参、已有交付同步、远程不可达保留状态、远程 origin/main 队列读取、用户脏工作区保护与 worktree 隔离)
- `tests/test_runner_service.py`: 4 passed (中文/空格路径 XML 生成、install/stop 正常流程、launchctl 状态解析、launchctl 卸载失败保留 Plist 防御)

### 2.2 CLI 子命令实测证据
1. **状态查询（初始状态）**：
   ```bash
   .venv/bin/python -m vmv runner status
   ```
   输出：
   ```
   ============================================================
   本地 AGY 自动接任务服务状态
   ============================================================
   服务标识: com.vmv.runner
   安装状态: 未安装
   Plist路径: -
   运行状态: 空闲/未激活
   ```

2. **单次轮询与既有交付识别**：
   ```bash
   .venv/bin/python -m vmv runner once
   .venv/bin/python -m vmv runner status
   ```
   输出：
   ```
   本地任务状态清单:
     - [source-download:r1] 状态: done, 尝试次数: 0, 启动时间: -
     - [stage0-fixes:r1] 状态: awaiting_review, 尝试次数: 0, 启动时间: -
   ```
   实测确认：`.vmv-runner/state.json` 准确记录 PR #1 为 `done`，记录 PR #2 为 `awaiting_review`，未产生重复执行。

3. **launchd 服务安装与启用核验**：
   ```bash
   .venv/bin/python -m vmv runner install --interval 120
   .venv/bin/python -m vmv runner status
   ```
   系统 `launchctl list | grep com.vmv.runner` 准确显示正在运行并定时唤醒。

---

## 3. 安全约束与边界说明

1. **工作区绝对安全**：任务全部在 `.vmv-runner/worktrees/` 隔离运行，用户在主工作区编辑代码或处于未提交状态时不受任何影响。
2. **权限最小化**：仅写入用户自身的 `~/Library/LaunchAgents/com.vmv.runner.plist`，不使用 `sudo`。
3. **敏感凭据脱敏**：状态文件、worktree 与日志（`.vmv-runner/`）全部加入 `.gitignore`，绝不向 Git 提交任何本地凭据或临时文件。
4. **阶段门禁严格遵守**：
   - 不自动合并 PR #1、PR #2 或 PR #3。
   - 视频处理阶段（Stage 1 抽帧与镜头切片）依然停在门禁前，等待用户正式验收授权。

---

## 4. 未验证项与已知限制（如实报告）

1. **关闭 AGY App 后的 CLI 执行探针**：
   - 当前会话由 AGY 交互式 App 运行，无法在自我关闭 App 的前提下验证后台 CLI probe；
   - 故按规则**明确标为“关闭 App 后未独立验证”**，不伪造达标结论。
2. **Mac 深度睡眠机制**：
   - macOS launchd 在 Mac 深度休眠期间由系统暂停定时器，但在唤醒后会自动执行补跑。
3. **Quota Wait 恢复特征**：
   - 当前本地实测中 CLI 均正常调用，尚未实际遭遇额度耗尽报文；故维持有限重试与 blocked 兜底，不编造未经验证的自动恢复逻辑。
