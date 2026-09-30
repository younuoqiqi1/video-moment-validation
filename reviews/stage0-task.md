# 阶段 0：Codex 审查与 AGY 修正任务

- 审查时间：2026-09-30（Asia/Shanghai）
- 审查对象：main / d146c309a413ac5c08b6e1255941131c863f2b4c
- 结论：request_changes；已有功能保留，只做以下修正。暂不进入 L1 或阶段 1。
- 执行者：用户 Mac 上的 AGY。Codex 不替 AGY 修改产品代码。

## 已核实与证据边界

已从 GitHub 读取 pyproject.toml、src/vmv 的全部模块、tests/test_cli.py、阶段报告与本地实施计划。
在 Python 3.12.14 环境，现有六个测试函数通过标准库辅助执行器逐一运行，断言全部通过。辅助执行器只为未使用的 pytest 导入提供占位模块，并提供临时 tmp_path；这不是一次正式 pytest 执行。当前审查环境没有 pytest，不能把该结果写成 Codex 重新跑了 pytest 6/6。
独立复现了下面的输出覆盖和文件系统异常。
Mac 上的真实工具状态、原 pytest 执行与 HTML 打开结果目前以 AGY 报告为依据，未独立操作用户 Mac。

## 必须修正

### R1：JSON 与 HTML 输出路径碰撞（P2）

位置：src/vmv/report.py:353–366。
复现：status --output environment.html。JSON 和 HTML 写到同一路径；最终只剩 HTML，命令却退出 0 并给出两条相同产物路径。

最小修复：CLI 的 --output 必须是 .json 文件，大小写可以标准化校验；发现其他后缀或 JSON/HTML 路径相同，写文件前拒绝，返回非零并显示中文原因。不覆盖已经存在的非 JSON 目标。保持默认 .json 路径和中文/空格路径有效。
回归测试：传入 .html，退出非零且不创建产物；若目标已有哨兵内容，内容不变。正常 .json 生成两个不同路径、JSON 可解析。

### R2：输出失败的错误处理（P2）

位置：src/vmv/report.py:350–366；src/vmv/cli.py:42。
复现：输出路径指向已存在目录，抛 IsADirectoryError；父目录是普通文件也会失败。
最小修复：处理预期的文件系统错误，输出中文失败说明及目标路径，返回非零，不输出“全部通过”。不宣称两个文件事务性写入；若部分产物已生成，明确记录部分失败，避免留存误导性成功结果。
回归测试：使用确定的路径冲突或模拟 PermissionError，不依赖 root 权限、chmod 或磁盘满。断言中文错误、非零退出和没有成功提示。

### R3：报告与看板一致、保留人工验收（P2）

reports/stage0-review.md 自行声明正式验收通过；PROGRESS.md 阶段表为 10% 已通过，但顶部仍为 8%、Mac 未核验；GitHub 关联仍未打勾。
保留 AGY 已实测的环境结果，区分 implementation_complete 与 awaiting_review / accepted。当前修正提交后必须 awaiting_review；不得自行代表 Codex 或用户验收。
修正看板过期文字并打勾 GitHub 已关联。总体百分比统一口径：阶段0未验收期间可保留准备估算8%，清楚标为估算；确认通过后该阶段贡献10%。不要写当前功能实现仍为0，因为环境CLI已实现；视频检索、TTS和成片能力尚未实现。
下一项按本地计划是 L1（AGY检查点与额度续跑），不是直接素材导入；未经批准不执行。
阶段报告中的本地文件链接改为仓库相对路径；outputs/ 产物仍在本地，不强行提交全部输出。

## 本阶段交付规范

- 代码和测试进入 Git。
- reports/stage0-review.md 记录命令、退出码、实施状态、阻塞项和 code_commit。
- 新增 reports/tests/stage0-test-summary.md，保存实际 pytest 的脱敏摘要：时间、Python版本、运行命令、测试数量与结果。
- 可以把环境 JSON 的脱敏工具版本与检查结果摘录进 reports/，不要复制令牌、完整环境变量或个人目录。
- 先提交代码与测试，随后报告引用该代码提交ID，另行提交报告与看板，避免报告自身哈希循环。
- commit 并 push 用户已指定的 origin/main，禁止 force push；失败记录 blocked_github。
- 改动前先查看 git status，保留用户改动，仅暂存本任务文件。
- GitHub 是审查交接入口，不要求用户上传报告或代码。
- 本任务文档和其后续审查文件应拉取到本地；AGY不假定能自动调用GPT或自动获得新的审查。
- 本次只执行 R1–R3。修正后停止 awaiting_review，等待仓库审查。

## 可补充测试（非扩展功能）

现有实现已有 Python>=3.12 判定，可以补一条模拟旧版本的测试，验证非零返回与失败报告。这不是要求支持旧Python。

## 审查之外

AGY登录、FFmpeg安装来源、额度续跑、视频检索与TTS未在这次代码审查中验证。不得把环境检查全绿当作这些能力已验证。
