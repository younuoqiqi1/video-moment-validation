> 2026-10-01 当前执行更正：本文件下方的旧基线预览任务已经完成，保留为历史，不再重复执行。当前唯一续做入口为 [stage1-cut-recheck.md](./stage1-cut-recheck.md)，核查 Mac run 36862013598 的修正后候选，而不是再次查看原130条清单。vmv preview 不会重新检测切点，仅展示输入清单。用户已授权继续阶段1，无需再询问是否开始。

# AGY 任务：只运行 Codex 阶段 1 代码并回报真实素材结果

用户已选择“Codex 写代码，AGY 在 Mac 运行素材”。本任务替代此前编码任务；旧任务文档仅作历史记录。

## 唯一范围

只运行 PR #5 中 Codex 已写好的程序、查看真实素材、提交脱敏结果。不要修改 src/ 或 tests/，不要调整镜头检测阈值，不合并 PR，不进入阶段 2。遇到程序问题交回 Codex 修复。

## 运行步骤

1. 核对当前工作区为 PR #5 最新提交，保留原工作区及素材。若目录有未知修改，停止并报告，不能覆盖。后台 runner 会提供独立 worktree 和本机素材链接。
2. 真正开始运行后，在 PR #5 评论：`AGY 协同回执：已开始运行 Codex 阶段1代码`，附当前代码提交 SHA。不能以轮询成功代替实际开工。
3. 不重新 import。以本机 `outputs/stage1/media_manifest.json` 中 `scene_manifest_file` 指定的 JSON 为唯一数据源。不要选择旧清单迎合 130 或 58.88 等数字。
4. 使用本机已有虚拟环境 Python；在当前 worktree 运行以下命令。独立 worktree 无 .venv 时，将 `.venv/bin/python` 替换为 runner 提供的原仓库 Python 绝对路径。

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
import json
from pathlib import Path
from vmv.cli import main
manifest = Path('outputs/stage1/media_manifest.json')
name = json.loads(manifest.read_text())['scene_manifest_file']
scene_file = manifest.parent / name
raise SystemExit(main(['preview', '--media-manifest', str(manifest),
    '--scenes', str(scene_file), '--video', 'data/input/qianfu_ep18.mp4',
    '--output', 'outputs/stage1/codex-preview']))
PY
```

5. 打开 `outputs/stage1/codex-preview/summary.html`。查看完整清单、最长区间、所有超过 30 秒区间的五处预览，以及前后相邻区间。需要判断是否漏切时，在原视频播放这些位置；仅凭几张图不足以确认没有漏切。不能实际查看时明确写“画面未验证”。
6. 新增 `reports/stage1-local-preview-result.md`：记录代码 SHA、清单 SHA256、全部条数、平均/最短/最长时长、最长序号、实际检查的区间及观察。核实用户所见 210.90/210.96 秒与历史报告 58.88 秒来自何处；无法确定原因就列为未解决。保留历史报告，不覆盖原 JSON。报告不得含机器路径、凭据、视频或帧图。
7. 成功运行或阻塞都提交该报告并推送 `git push origin HEAD:feat/stage1-media-import`。仅 add 报告文件，核对暂存文件无媒体。PR #5 评论实际完成/阻塞和报告链接，保持 awaiting_review。程序失败时报告安全错误摘要，不自行改代码，不宣称阶段通过。

## 判断标准

- 数值核对与画面检查分开记录；合成视频测试不能替代真实素材观察。
- 代码能够生成完整预览，不代表镜头检索或成片已完成。
- 没有真实 Mac 执行结果，不得写“已运行”或“已验证”。
