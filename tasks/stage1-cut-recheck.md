# AGY 本机任务：阶段 1 漏切修正复验

已授权，不重复询问是否开始。Codex 负责此次编码，官方 Mac 执行器负责固定版本复跑；AGY 负责本机画面观察。严格限于阶段 1。

## 自动固定任务

`codex/mac-actions` 分支的 `stage1-cut-check` 任务只运行该分支脚本中白名单的 PR #5 完整代码 SHA。以 Actions 真实开始/完成/失败回执为状态依据，任务文件存在不算执行完成。

执行入口：

```bash
python -m vmv.cut_comparison --video data/input/qianfu_ep18.mp4 \
  --manifest outputs/stage1/media_manifest.json \
  --scenes outputs/stage1/scenes_qianfu_ep18_720p_25fps.json \
  --reference tasks/stage1-cut-reference.json \
  --output outputs/stage1/cut-recheck/独立运行编号
```

执行器自行使用本机既有项目配置、Python 和素材，不要求用户复制命令。输出目录必须不存在，保留此前产物。不要上传帧、视频、凭据、绝对本机路径或原始日志。

## AGY 画面抽查与回执

1. 查看这次运行的本地 `preview/summary.html`，复核参考 14 点的前后帧。第 21523 帧需区分运动与硬切。
2. 查 `comparison.json` 的未匹配参考、所有新增和移除切点。新增切点逐项查看视频前后帧，记录硬切/运动/闪光/渐变/未确认。统计实际抽查数、确认正确数、确认误切数、无法确认数；没有查看的项不能算通过。
3. 查新最长区间及原 #083/#125/#105/#074/#049 对应范围与相邻区间。仍漏切则回报帧号和安全描述。
4. 将安全数字与来源 SHA/Actions 链接追加到 `reports/stage1-local-preview-result.md`，保留历史内容；发“AGY 协同回执：实际完成”或具体阻塞，不只说轮询成功。不要把数值匹配当人工验收。
5. 保持 awaiting_review，不合并、不进入阶段 2。
