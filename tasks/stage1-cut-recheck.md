## 最新复验入口（2026-10-02）

最终代码为`89f8117c415c917274a6233a5e12c6ade555e027`（检测器v4）。Codex在本轮桌面环境已独立读取原片局部，合成/分数序列测试67项通过；详细证据和最终数值见 `reports/stage1-dark-fade-recheck.md`。下方abb5/f1e任务与queued状态均为历史快照，不代表本轮最终版本的执行状态，也不表示AGY正在编程。

1373.64秒为渐黑亮度低谷候选，需按渐黑转场核对前后画面，不应要求与AGY观察1373.72秒按硬切±1帧匹配。1379.72秒附近连续帧未发现硬切，暂不加入参考索引。v3在1377.72秒的运动误切已用通用帧差确认修正；不能据此宣布所有候选质量通过。

仍需对最终版本的14个暂定参考点、全部新增/移除候选及最长区间逐项画面分类，未经查看不可算通过。`human_visual_review`保持`not_verified`，阶段1待人工验收，阶段2未授权。此处记录当前任务和证据，并非给AGY新派发任务或声称其已重新开工。

---

## 历史续做入口（2026-10-01，Codex 低分数漏切修正）

- 当前修正代码 SHA：`abb5f973f2b7cc07ee3eaf743d05f2f24f54af2c`。合成图案复现了旧绝对下限0.06漏掉分数0.0465的边界；新下限0.04，Codex合成复验通过。
- 固定 Mac 复跑已派发，GitHub Actions run [36890338194](https://github.com/younuoqiqi1/video-moment-validation/actions/runs/36890338194) 目前为 queued；只有 self-hosted Mac job 实际运行/完成才算开始/完成证据。
- 运行结果必须核对 `code_sha=abb5...`、安全 comparison 数值及本机新预览。重点核用户截图报告的 **34343帧（1373.72秒）与34493帧（1379.72秒）**，以及旧参考点35297帧、14个已登记参考和所有新增/移除候选。截图观察来源是用户转交的 AGY 画面反馈，Codex尚未独立看过原片。
- 如果任务未能在 Mac runner 上开始，报告具体 Actions 状态/阻塞；不要把排队说成已开始。真实素材和帧图只留 Mac 本机，阶段1保持 awaiting_review。

---

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


## 2026-10-01 当前续做入口：修正后候选画面复核

旧 tasks/stage1-codex-local-run.md 已完成并改为历史入口。21:51交付仍是130条旧基线，不能据此判断 f1e 自适应检测失败，也不需要再次开发同一修正。

1. 同步 PR #5 最新任务文件，保留本机用户改动。采用代码 f1e3b5f5da041a2fb68bfb4aa405696245ce6d0e 的 [Mac run 36862013598](https://github.com/younuoqiqi1/video-moment-validation/actions/runs/36862013598) 产物。本机项目下该执行器输出相对目录为 `outputs/stage1/cut-recheck/36862013598-1/`（来自固定执行脚本的目录规则；需在本机确认存在，不能猜成功）。读取同目录 comparison.json、media_manifest.json、候选 scenes JSON 与 preview/summary.html；原 outputs/stage1 下的130条JSON只作为 before 对照。
2. 先实际确认候选 total_scenes=320、after_statistics 最长87秒(#260)、328张预览、before130/after320及来源哈希与完成回执一致；若不一致，记录真实数字和阻塞，禁止改数迎合预期。目录不存在则按上方已授权 cut_comparison 命令在全新输出目录复跑，不重复 baseline-only preview，不覆盖旧产物。
3. 先核第35297帧与#260，报告是否仍漏切；复核14暂定参考点，再逐项标注 comparison.json 内199新增及9移除。单独记录实际查看/未查看/无法确认项，给每项帧号、分类与安全短描述；参考命中不能自动算正确。
4. 追加修正后章节到 reports/stage1-local-preview-result.md，保留130条旧基线历史；注明本轮代码SHA、来源run、实际开始/完成时间、检查量、剩余漏切与误切。同步进度为“数值复跑完成，修正后画面验收待补充/实际完成”，保持 awaiting_review及总体已验收10%。
5. 先回报第35297帧及#260的真实观察结果，再继续其余项目；若本地执行端无法打开候选图或原片，直接给具体安全阻塞。不要等待新的算法提交，不向 Codex 机器人发送仅 @codex 的启动留言，不把发评论当执行。真实素材和帧图只留本地。

依据：[本轮审查](https://github.com/younuoqiqi1/video-moment-validation/blob/main/reviews/pr-5-46d9e8d0a5cbd16b7e1a14b7e14d1e819bd94fce.md)。
