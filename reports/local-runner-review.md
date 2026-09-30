# 本地 AGY 自动接任务服务实现与验证报告

- **日期**：2026-09-30 (Asia/Shanghai)
- **分支**：`feat/local-task-runner`
- **实施依据**：`docs/superpowers/plans/2026-09-30-local-task-runner.md`、`tasks/execution-policy.md`
- **交付目标**：实现并启用本地自动接任务后台服务，安全轮询已授权任务，提交 PR 等待 Codex 审查。

---

## 1. 架构与设计规范

### 1.1 组件分工
1. **`src/vmv/runner.py`**：
   - **任务白名单**：从 `tasks/queue.json` 读取受控任务，非白名单或 `authorized=false` 任务静默跳过。
   - **跨进程排他锁**：基于 `fcntl.flock` 在 `.vmv-runner/runner.lock` 实现非阻塞互斥锁，多实例自动跳过。
   - **状态机与原子持久化**：支持 `ready`, `running`, `awaiting_review`, `blocked`, `interrupted`, `quota_wait`, `done`，通过 `.tmp` + `os.replace` 原子写入 `.vmv-runner/state.json`。
   - **既有交付自动登记**：首次运行自动识别已交付的 PR（如 PR #1 素材下载已标记 `done`，PR #2 阶段0修正已标记 `awaiting_review`），杜绝重复执行。
   - **审查结果精确匹配**：要求审查文件必须与任务的 `head_sha` 严格对应（例如 `reviews/pr-2-<sha>.md`），旧提交的审查或结论为 `request_changes` 的文件不会误标 `done`。
   - **CLI 安全调用**：通过参数列表 `[agy, "--print", prompt, "--output-format", "text", "--dangerously-skip-permissions"]` 启动，严禁 `shell=True`，防御 shell 元字符注入。

2. **`src/vmv/runner_service.py`**：
   - 生成符合 macOS 规范的用户级 launchd 配置文件 `~/Library/LaunchAgents/com.vmv.runner.plist`。
   - 支持路径 XML 转义（处理中文与空格路径），配置 `StartInterval=120` 和 `RunAtLoad=true`。
   - 提供 `install_service`, `stop_service`, `get_service_status` 管理接口。

3. **`src/vmv/cli.py`**：
   - 新增 `vmv runner` 子命令体系：`once`, `status`, `install`, `stop`。

---

## 2. 真实 Mac 测试与验证证据

### 2.1 自动化单元测试 (pytest)
执行环境：macOS Darwin, Python 3.12.14, pytest-9.1.1
执行命令：
```bash
.venv/bin/python -m pytest tests/ -v
```
测试结果：**20/20 passed in 0.18s**
- `tests/test_cli.py`: 6 passed (阶段0环境核验与错误边界回归)
- `tests/test_runner.py`: 11 passed (互斥锁、白名单、执行转换、非零退出、死进程崩溃恢复、审查通过识别、commit SHA 不匹配不通过、request_changes 不通过、done 任务跳过、shell 元字符字面传参、已有交付同步)
- `tests/test_runner_service.py`: 3 passed (中文/空格路径 XML 生成、install/stop 流程、launchctl 状态解析)

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
   本地暂无持久化任务状态记录。
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
   实测确认：`.vmv-runner/state.json` 准确记录 PR #1 为 `done`（匹配 `reviews/pr-1-a73a298a12ca87bd81d1ca27bf87f0b7c5c8172f.md` 的 `pass_with_notes`），记录 PR #2 为 `awaiting_review`（head 为 `1cb49c5c3fb1dc9f94f8048b64792345c3f7ce89`），未产生重复执行。

3. **launchd 服务安装与卸载验证**：
   - 安装命令：
     ```bash
     .venv/bin/python -m vmv runner install --interval 120
     ```
     返回：`成功安装并启用后台轮询服务: com.vmv.runner (周期 120 秒)`。
     系统进程核实：`launchctl list | grep com.vmv.runner` 准确显示 `53077 0 com.vmv.runner`。
   - 停止与卸载命令：
     ```bash
     .venv/bin/python -m vmv runner stop
     ```
     返回：`已成功停止并卸载后台服务: com.vmv.runner`。
     系统进程核实：`launchctl list` 无遗留，Plist 文件已安全删除。

---

## 3. 安全约束与边界说明

1. **权限最小化**：仅写入当前用户的 `~/Library/LaunchAgents/com.vmv.runner.plist`，不请求 `sudo`，不修改系统级服务。
2. **凭据脱敏**：任务状态与日志（`.vmv-runner/`）加入 `.gitignore`，不输出 token、cookies 或敏感路径。
3. **阶段门禁严格遵守**：
   - 不自动合并 PR #1 或 PR #2。
   - 视频处理阶段（Stage 1 抽帧与镜头切片）依然停在门禁前，等待用户完成阶段0的正式验收授权。

---

## 4. 未验证项与已知限制

1. **Mac 睡眠/唤醒行为**：launchd 在 Mac 深度睡眠期间不保证定时触发，但在唤醒后会自动执行一次补跑；此特性为 macOS launchd 原生机制，无需额外轮询进程常驻。
2. **离线/断网重试**：当本地网络断开导致 Git 远程或 GitHub API 不可达时，检查器会保留当前本地状态并退出当前周期（返回 0），在下个周期网络恢复后继续探测，不盲目标记 blocked。
3. **Quota Wait 恢复特征**：当前实测中 AGY CLI 均正常响应，尚未捕获实际的额度耗尽错误报文格式；因此保持有限重试与 blocked 兜底，不伪造未经验证的自动恢复逻辑。
