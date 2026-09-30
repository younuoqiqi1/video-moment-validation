# Mac 本地启动与 AGY 交接

项目代码、视频处理、索引、生产单、TTS 调用与 MP4 输出全部在 Mac 运行。AGY 编码，Codex 拆任务、审查代码与测试证据，用户验收各阶段。AGY 和 TTS 仍是联网服务。

当前包包含文档与 Git 历史，不是已经实现的视频工具。

## 在 Mac 开始

1. 下载并解压交接包，把 `video-moment-validation` 文件夹放在你方便的位置；不要覆盖已有同名项目。
2. 用本地 Antigravity 打开这个文件夹。已有 AGY 登录先复用，不需要云端授权。
3. 将下面整段指令交给 AGY。也可以在终端进入这个文件夹后运行 `agy`，再粘贴指令。
4. 阶段完成后，打开它生成的环境报告；把 `reports/stage0-review.md` 和代码改动交回当前聊天。尚无 GitHub 连接时，报告本身不能代替代码审查，可同时上传该阶段源码包。

## 交给 AGY 的第一条指令

```text
你是此项目的编码执行者。项目在当前 Mac 本地运行，Codex 负责计划和代码审查，用户逐阶段验收。

先完整阅读 LOCAL_START.md、README.md、PROGRESS.md、
docs/superpowers/specs/2026-09-29-video-moment-validation-design.md、
docs/superpowers/plans/2026-09-30-local-execution.md。
本地执行修订优先于旧计划的云端安排。

这次只执行 local-execution 计划的 L0：实现并验证环境检查与阶段报告。
先只读核验 macOS/架构、Python、FFmpeg、ffprobe、Git 和 AGY；不要读取或输出登录令牌。
使用当前已有 AGY 登录。缺工具时报告阻塞与需要的安装步骤，不擅自修改系统、升级系统工具或重新登录。
不需要 GPT API，不调用 TTS，不处理正式视频，不开始后续阶段。

实现 Python CLI status、JSON/HTML 环境报告及必要的环境检测测试。
依赖仅安装在项目虚拟环境；已有文件先检查差异，不覆盖用户工作。
HTML 使用中文、可直接在本地浏览器打开，不依赖 CDN。
缺依赖必须列出缺失项并返回失败状态，禁止伪造成功或测试结果。

输出 reports/stage0-review.md，包含实际运行命令、退出码、通过/失败/未运行、
改动文件、报告路径、阻塞项和 Git 提交；不得记录密钥、原始授权信息或视频。
把本地检查状态更新到 PROGRESS.md；仅提交本阶段文件，不推送到未知 GitHub 仓库。
若任务中断，保存任务、完成步骤、失败原因和下一步，不自动重做已完成步骤。

最后停在 awaiting_review。不要自动进入素材导入或额度续跑开发。
```

## Git 历史与 GitHub

包内的 `project-history.bundle` 保存交接前的提交。若要保留这些历史，可先在当前项目文件夹执行：

```bash
git clone project-history.bundle ../video-moment-validation-history
```

只在目标文件夹不存在时执行，然后使用新建的 `video-moment-validation-history` 文件夹作为项目根目录。也可以直接使用解压目录，让 AGY 建立新的本地 Git 仓库，旧历史 bundle 作为备份保留。

GitHub 仓库尚未指定或连接。建议使用私人仓库；确定仓库后再设置 remote 和推送。视频、音频、图片中间产物、`.env` 和 AGY 会话凭据都不进 Git。

## 后续监督

每阶段只回传报告、代码差异、测试证据与必要的预览，避免把完整日志反复放进聊天。Codex 审查后生成修改任务；用户通过阶段验收才进入下一阶段。

镜头理解时，AGY 编写导出和导入功能，GPT 在当前聊天分析抽帧与字幕包。此过程需要用户传递文件，不是本地程序无人值守调用 GPT。

AGY 额度续跑仍需开发、测试，并受 Mac 开机与休眠状态影响。GPT 自动续跑尚未接通；本包不会自动唤醒当前聊天。
