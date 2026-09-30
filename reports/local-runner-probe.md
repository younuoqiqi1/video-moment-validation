# 本地 AGY 真实后台执行能力探针报告

- **日期**：2026-09-30（Asia/Shanghai）
- **关联任务**：`tasks/local-runner-probe-first.md`
- **关联审查**：`reviews/pr-3-cbed914ec0392411013541247344a1f10ed6d26c.md`（A–E 项）
- **代码提交**：`e6fc99e1e85020fd844992c5da40c83160b4e34f`
- **状态**：`implementation_complete` / `awaiting_review`

---

## 1. 真实可执行文件与调用参数模板

- **可执行文件路径**：`/Users/yoyotaozhou/.local/bin/agy`
- **版本信息**：`1.2.14`（非软链接或猜测文件，大小约 187MB 的原生二进制）
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

## 2. 独立终端真实 CLI 探测验证

- **结论**：`passed`
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

## 3. 用户级后台真实 CLI 探测验证 (launchd)

- **结论**：`passed`
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

## 4. App 关闭条件验证状态

- **结论**：`not_verified`
- **原因说明**：为防止在交互会话中强行退出宿主 Antigravity App 导致与用户会话失联，本轮未在当前开发会话中强行关闭 App。
- **独立离线验证程序准备**：
  - 已编写就绪独立验证程序：[`scripts/verify_offline_probe.py`](file:///Users/yoyotaozhou/Documents/video-moment-validation/scripts/verify_offline_probe.py)；
  - **用户一步操作指南**：
    1. 在系统原生终端（Terminal.app）中运行：
       ```bash
       python3 scripts/verify_offline_probe.py
       ```
    2. 程序会通过 launchd 自动排期并在 15 秒后触发探测；
    3. 在 15 秒内完全退出 Antigravity / 宿主 IDE（`Cmd + Q`）；
    4. 45 秒后，在终端查看最终写入结果：
       ```bash
       cat /tmp/agy_offline_probe_result.json
       ```

---

## 5. 任务调度器 A–E 项修复与回归实测

针对 `reviews/pr-3-cbed914ec0392411013541247344a1f10ed6d26c.md` 指出的缺陷，生产调度器已全面完成最小充分修复：

1. **A 项（网络与注入防范）**：
   - `check_process_alive` 严格校验 `isinstance(pid, int) and pid > 0`，杜绝任何参数注入；
   - `fetch_remote_main` 校验 `shutil.which("git")` 并增加 30s 超时与异常捕获。
2. **B 项（远程准据与未授权隔离）**：
   - `load_queue_tasks` 与 `get_task_prompt` 严格以 `origin/main` 远端为唯一准据；
   - 远端队列文件损坏、解析异常或缺失时返回空列表并记录错误，**严禁静默回退至本地未授权草稿**。
3. **C 项（精确 PR 与当前提交匹配）**：
   - 构造目标 `reviews/pr-<number>-<40位sha>.md`，通过 `git show origin/main:reviews/...` 读取；
   - 报告仅缓存在 `.vmv-runner/reviews/`，不污染工作区；
   - 新增 `_parse_review_conclusion` 精确解析 `pass` / `pass_with_notes` / `request_changes` / `blocked`，杜绝子串误判；
   - GitHub API 查询严格筛选 `state=open` 且 `draft=false`。
4. **D 项（去重记录永久持久化与无提交保护）**：
   - `TaskState` 新增独立 `dispatched_reviews` 列表；
   - 派发前将 `f"{st.pr_number}:{st.head_sha}"` 先行存入磁盘，后续成功/失败/重启均不删除该键；
   - 若 CLI 运行成功但工作区 HEAD 未产生新提交（与被审查提交相同），立即标记 `blocked`（“未产生可审查的新交付”），防止无限循环。
5. **E 项（子进程存活期间实时持久化 PID）**：
   - `execute_cli_task` 引入 `on_started(pid)` 回调，在 `communicate()` 阻塞等待之前立即写回 `state.json`；
   - 超时后通过 `proc.kill()` 与 `proc.wait(timeout=5.0)` 及时回收子进程。
6. **服务生命周期加固**：
   - `install_service` 与 `stop_service` 严格校验卸载退出状态；若卸载失败，保留配置文件并如实返回错误原因。

### 自动化测试证据
- **调度器专项测试**：`tests/test_runner.py`（**20/20 passed in 0.20s**，含跨两轮去重实测、实时 PID 写入断言、损坏远程队列隔离、结论解析回归）
- **后台服务专项测试**：`tests/test_runner_service.py`（**4/4 passed in 0.03s**）
- **全量测试套件**：`.venv/bin/pytest`（**30/30 passed in 0.21s**）

---

## 6. Git 任务自动接收与生产边界

- **远端队列限制说明**：经核对，当前远程 `origin/main` 主分支尚未包含 `tasks/queue.json`（队列定义文件仍在 PR #3 分支中）。因此，生产远程任务自动接收处于就绪但等待合并状态。
- **守则边界**：
  - 本次不合并 PR #1、PR #2、PR #3；
  - 不认定用户验收；
  - 严禁越权进入阶段 1（视频处理）；
  - 保持 `awaiting_review` 等待复核。
