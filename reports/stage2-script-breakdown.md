# 阶段2首版：口播拆段与画面需求

2026-10-02用户明确授权启动阶段2，并选择先用合成稿开发验证。阶段1全量画面验收仍未完成；本授权不改写阶段1验收结论。阶段2首版为awaiting_review，不自动进入阶段3。

## 实际实现

- `vmv script`读取UTF-8口播稿，按空行拆成段落，保留原文、顺序、段内换行、原始文本和SHA-256，生成草稿JSON和可填写的本地HTML。
- 每段可填写人物、场景、动作、情绪和画面需求，并明确选择待确认/已确认；页面在本机导出requirements.json，不发送网络请求。
- `vmv script-review`校验草稿源文本、哈希、段落ID/顺序/原文/偏移，拒绝缺段、乱序、篡改、非法类型、空画面需求及未确认状态；只有通过校验才导出确认稿。
- 既有目录不可覆盖；合成稿始终携带sample标识，草稿不会自动变为已确认稿。

此版提供拆段与人工需求填写/导回能力；没有自动语义理解或自动生成画面需求，也没有镜头检索、TTS或视频合成。真实稿的画面需求是否准确仍需用户确认。

## 本轮独立检查

AGY以显式模型`gemini-3.8-flash-high`生成代码。无头工具权限不足，未修改全局授权或使用宽泛跳过权限；改为AGY输出代码文本，由Codex审查落盘、修正接口接入和明显生成错误后独立执行。

新增模块测试26项、CLI测试3项，完整`python -m pytest -q`为**96 passed**（原67项也通过）。新模块缺失及CLI未接入时实际检查失败；随后畸形根JSON、错误段落类型、布尔偏移4个回归在初版实际失败，输入校验补充后通过。测试错误断言经过收紧，未保留接受任意Exception的伪保护，也未保留猜测文件名或切换目录后重试的测试。

合成稿 `examples/stage2-script-sample.txt` 实际拆为3段、state=draft、sample=true。使用真实生成页面的JavaScript，在Node隔离上下文中提供模拟输入控件，实际调用导出函数，获得绑定原文与哈希的3段requirements.json；再通过函数及CLI导入到新目录，state=confirmed且sample仍为true。确认字段为测试填写，不代表真实口播稿或人工验收已通过。

## 明确未验证

- 浏览器安全策略阻止`file:`页面访问，本轮没有浏览器渲染、实际点击和浏览器下载验证；没有通过其他浏览器或协议规避限制。Node导出检查不能冒充浏览器端到端测试。
- 用户真实口播稿尚未提供；其段落边界和画面需求语义准确性未验证。
- 阶段1未匹配35297帧、全量候选画面验收和误切率仍未完成；本轮未改动镜头检测代码。

## 本地使用

```bash
python -m vmv script --input examples/stage2-script-sample.txt \
  --output outputs/stage2/sample-draft --sample
# 用户自行打开输出summary.html，填写需求并导出requirements.json。
python -m vmv script-review --draft outputs/stage2/sample-draft/segments.json \
  --requirements requirements.json --output outputs/stage2/sample-confirmed
```

阶段2独立分支基于PR #5当前代码，交付PR以`feat/stage1-media-import`为base，仅包含阶段2差异。不自动合并任一PR，也不将阶段1或阶段2计为用户验收完成。

## 独立审查补充

独立审查在初版发现合成需求导出缺少sample，以及requirements可选偏移未校验。AGY生成最小修正片段，Codex审查时修正其误将可选偏移当作必填的问题；补充5个非法偏移/合成标识回归，修正前全部失败，修正后全套96项通过。重新执行真实生成页面的导出函数（Node模拟控件），导出sample=true、3段需求，再经CLI确认导回成功。初次CLI复跑因未设置src导入路径失败，设置PYTHONPATH=src后成功；不将失败算作通过。浏览器验收限制保持不变。
