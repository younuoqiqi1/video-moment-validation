# 阶段3：候选检索与审核交付

2026-10-02用户确认阶段2验证完成并授权继续。阶段3合成首版待用户验收；阶段1全量画面验收继续保留，未自动合并或进入生产单/TTS。

## 实现

- `retrieve`接收已确认脚本、镜头catalog与视频。校验原文/段落/偏移/状态、sample、素材哈希、实际时长与镜头范围，再用中文相邻字匹配返回最多3个不同候选；无重合不给伪候选。此方法明确标lexical_baseline，不能冒充语义检索。
- `caption-packet`核验素材后导出每镜头3张抽帧、镜头ID/时间和哈希绑定分析包；当前会话人工提交图片给GPT分析，按说明保存结构化描述；`caption-import`检查数量、顺序、ID、原目录哈希与sample，保留原时间范围。无字幕允许空字符串。
- `retrieve --assisted-rankings`导入GPT_assisted排序文件，只接受绑定当前脚本/catalog、最多3个既有镜头及非空理由，时间取可信catalog；保留每段lexical_baseline结果作比较。该标识表示导入辅助文件，不能自行证明模型实际观察了视频或质量通过。
- FFmpeg预览和抽帧复用受控进程组/超时清理；输出经ffprobe验证有可解码画面。低帧率末端取不到图时回退段内中点/起点，仍失败不发布。临时目录成功后整体发布，既有目录不覆盖。
- 审核页显示旁白、已确认画面要求、候选理由/区间与视频；支持采用、淘汰、全部不合适（自动全淘汰），未审核不能导出。`candidate-review`校验源哈希、候选文档哈希、IDs、选择数量与状态，拒绝候选改变后的旧记录。无生产单编排或剪辑时间编辑。

## 本轮独立证据

AGY显式模型生成代码，Codex审查去除多余生成引号并完成接口接入和必要校验修正。新增29项阶段3测试，原129项保留，全套**158 passed**。缺模块/CLI接入先失败；最多3候选、原文偏移、错误JSON根/字段、无字幕导入、零帧成功退出、候选文档变化回归实际失败后修正通过。其余覆盖去重、无匹配、来源哈希、样本混用、越界/非法数值、提取失败不发布、辅助绑定与导回。模型/常规媒体单测采用边界模拟；另有真实1fps低帧率FFmpeg回归，确保没有列出空图片。

真实构造6秒25fps红/绿/蓝色视频，3段合成测试需求。词语基线各最多3候选，首位分别红/绿/蓝（一般词重合导致其余颜色也有弱匹配，不代表达到80%）。实际生成可解码MP4。分析包9JPEG均通过可解码检查；Codex本会话查看3张代表帧，给出颜色/无人无字观察，保存GPT辅助描述和对应排序导入，每段1个对应色块候选。该极简验证不代表电视剧语义检索质量。

实际生成页面JavaScript在Node模拟DOM中运行，pending拒绝导出、全部不合适自动淘汰、导出含sample/候选哈希的JSON，CLI成功校验导回。第一次模拟DOM缺少appendChild导致验证脚本失败，修正模拟DOM后复跑通过；未当作产品缺陷或浏览器通过。独立审查发现媒体零帧、全部不合适操作和画面要求显示问题，修正后复核无新增重要问题。

## 验收入口与限制

本机 `/private/tmp/vmv-stage3-synthetic/final-review/review.html`。这是明确标注的合成色块数据，不是《潜伏》真实候选。用户打开后播放每段、选择采用或全部不合适、下载审核JSON。需要文件旁的MP4完整保留。

尚未独立验证真实浏览器播放/点击下载、真实稿与真实片段的候选可用率/语义准确性，也未处理全量原片的新描述。阶段1尚未视觉验收，不能以本阶段合成结果替代。阶段3保持awaiting_review。

## CLI与数据接口

catalog需含sample（布尔）、media_id、原视频source_sha256、完整视频duration_sec、shots列表，每项有id/start_sec/end_sec/caption/subtitle。catalog时间须来自阶段1清单；真实素材数据不能用测试夹具替换。`caption-packet`允许待描述caption缺省，导回后方能retrieve。辅助排序格式为method=GPT_assisted、script_sha256/catalog_sha256/sample、segments列表，每段id及candidates[{shot_id,reason}]。镜头ID和候选归属不可自行编造。

```bash
PYTHONPATH=src python -m vmv caption-packet --catalog catalog.json --video source.mp4 --output analysis-packet
PYTHONPATH=src python -m vmv caption-import --packet analysis-packet/packet.json --response descriptions.json --output described-catalog
PYTHONPATH=src python -m vmv retrieve --script confirmed-script.json --catalog described-catalog/catalog.json --video source.mp4 --assisted-rankings rankings.json --output candidate-review
PYTHONPATH=src python -m vmv candidate-review --candidates candidate-review/candidates.json --review review.json --output validated-review.json
```

所有输出位置需未存在。无GPT后台API；抽帧分析与语义排序采用既定会话文件往返方式。测试样例在examples/stage3-synthetic-fixture.json，视频仅本机保留，重生成后须重算素材哈希。
