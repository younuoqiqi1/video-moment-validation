# Codex 自动读取审查意见补充实现
日期：2026-09-30（Asia/Shanghai）
用户已明确要求完成自动读取意见。此实现遵循已有本地Python单次检查器+用户launchd每120秒的设计，补充当前PR#3，无视频阶段授权。

## 实现
scripts/auto_review.py仅白名单PR#3。每周期核对真实GitHub PR状态/完整head SHA，fetch独立内部ref，git show精确审查路径。request_changes派发一次，pass仅记录停止。独立worktree新分支，不-B、不reset、不删已有目录；不改用户checkout。
调用AGY的参数数组采用AGY已经报告实测的模板，本机忽略配置可核对调整。实际PID在等待前保存；超时或状态保存失败终止回收进程组；崩溃遗留running状态停止待核查。与旧runner共享runner.lock。
完成只在同一PRhead确已更新且与工作区HEAD一致时awaiting_review，否则blocked。正常push，不force、不合并、不另开交付PR。
安装器用户级launchd为120秒、RunAtLoad；保留失败诊断。停止轮询不会被当作用户验收。当前只允许PR3，不用于未经授权的其他任务。

## 独立测试
python3 -m unittest discover -s autoreview-fix -p test_auto_review.py -v
7 tests，0 failures，退出0（0.094s）。
覆盖两周期一次派发、通过不派发、closed/draft不派发、fetch失败不派发、负面结论不误认、未知任务不读取、真实临时Git中已有分支额外提交不被重置。
测试GitHub与AGY调用是mock，分支保护使用真实Git。未验证用户Mac的launchd、真实凭据、关闭App或真实AGY启动。本报告不宣称本机已安装或端到端已通过。

## 给AGY的一次安装与验证
先安全读取远程任务并保留本地未提交修改；fetch codex/pr3-review-followup。审查并取得scripts/auto_review.py。此分支以PR3当前head为基础，没有自动修改AGY分支，不自动合并。
1. 原runner不得同时使用另外的state派发同一PR；核对当前没有旧runner/AGY后台写任务，停止旧com.vmv.runner轮询（只该服务、核对unload退出码）。共享锁避免同时启动，但不同state不能替代任务去重。
2. 从该分支git show提取脚本到独立临时路径，使用项目真实Python执行：
   python3 <提取后的auto_review.py绝对路径> install --repo <项目绝对路径>
   安装前确认.gitignore忽略.vmv-runner/。参数模板须与本机已验证AGY一致。不要覆盖已有配置，不要打印凭据。
3. install自动复制稳定脚本到忽略目录，再注册用户服务；不能只看安装命令退出0，应观察本地review-followup-state.json的PR3:SHA、实际PID和日志，120秒内是否收到当前审查。
4. 当前程序会修正PR3时正常推送原分支。单周期完成后观察新head，再观察对应新审查仅派发一次，提交脱敏报告更新PR3。
5. App关闭验证仍需用户/独立后台探测；不能把本报告7个测试冒充Mac实测。
6. stop命令停止本轮询；若存在已启动AGY，其现场应核查，不擅自杀其他服务。state损坏或running遗留都应人工核查，不清空重跑。
此补充实现需在Mac一次性安装；Codex当前不能直接操作用户Mac。未安装前，Git提交不会自动通知AGY。
