# 阶段 1 测试执行摘要 (Stage 1 Test Summary)

- **执行时间**：2026-09-30 (Asia/Shanghai)
- **Python 版本**：Python 3.12.14 (Darwin arm64)
- **测试框架**：pytest 9.1.1, pluggy 1.6.0
- **运行命令**：`.venv/bin/pytest tests/test_cli.py tests/test_media.py -v`
- **判定总览**：**31/31 passed in 0.79s**（全部通过，实测非声称）

---

## 1. 测试用例清单

| 测试模块 | 用例名称 | 结果 | 覆盖要点 |
| :--- | :--- | :---: | :--- |
| `test_media` | `test_seconds_to_timecode_broadcast_formats` | `PASSED` | 广播时间码 `HH:MM:SS:FF` 进位与边界 |
| `test_media` | `test_seconds_to_timecode_ms_format` | `PASSED` | 毫秒时间码 `HH:MM:SS.mmm` 格式化 |
| `test_media` | `test_timecode_to_seconds_roundtrip` | `PASSED` | 时间码与浮点秒数双向无损往返解析 |
| `test_media` | `test_timecode_invalid_inputs` | `PASSED` | 负数时间、非法字符、零帧率异常防护 |
| `test_media` | `test_generate_stable_media_id` | `PASSED` | 稳定素材 ID 生成与特殊字符净化 |
| `test_media` | `test_probe_media_file_not_found` | `PASSED` | 媒体文件不存在异常防护并报错 |
| `test_media` | `test_probe_synthetic_media` | `PASSED` | 合成视频流/音频流/尺寸/编码格式精确检测 |
| `test_media` | `test_detect_scenes_synthetic` | `PASSED` | 场景切分时间点连续性与边界覆盖校验 |
| `test_media` | `test_run_stage1_media_import_empty_dir_blocked` | `PASSED` | 无视频素材时生成 `import_blocked.json` 且状态为 blocked |
| `test_media` | `test_run_stage1_media_import_synthetic_success` | `PASSED` | 端到端生成 manifest、scenes JSON 与 summary.html |
| `test_cli` | `test_cli_import_empty_directory_returns_1` | `PASSED` | 命令行 `vmv import` 空素材目录返回 1 并报告问题 |
| `test_cli` | `test_cli_import_success_mock` | `PASSED` | 命令行 `vmv import` 参数解析与正常流转返回 0 |
| `test_cli` | `test_probe_tool_version_timeout` | `PASSED` | 阶段 0 工具版本探测超时回归 |
| `test_cli` | `test_probe_tool_version_not_found` | `PASSED` | 阶段 0 缺失工具处理回归 |
| `test_cli` | `test_check_environment_missing_ffmpeg` | `PASSED` | 阶段 0 依赖项检测回归 |
| `test_cli` | `test_status_cli_all_passed` | `PASSED` | 阶段 0 全通过场景回归 |
| `test_cli` | `test_status_cli_chinese_and_spaces_path` | `PASSED` | 中文及带空格路径原子写入回归 |
| `test_cli` | `test_status_cli_missing_tool_exit_code_1` | `PASSED` | 缺失依赖退出码回归 |
| `test_cli` | `test_status_cli_rejects_non_json_output_r1` | `PASSED` | R1 非 JSON 输出拒绝回归 |
| `test_cli` | `test_status_cli_filesystem_error_handling_r2` | `PASSED` | R2 路径冲突异常回归 |
| `test_cli` | `test_status_cli_python_version_insufficient` | `PASSED` | Python 版本检查回归 |
| `test_cli` | `test_status_cli_html_directory_failure_r2a` | `PASSED` | R2a 目录冲突保护回归 |
| `test_cli` | `test_status_cli_html_permission_error_r2a` | `PASSED` | R2a 权限异常保护回归 |
| `test_cli` | `test_status_cli_symlink_loop_r2b` | `PASSED` | R2b 软链接死循环保护回归 |
| `test_cli` | `test_status_cli_resolve_permission_error_r2b` | `PASSED` | R2b 路径解析权限保护回归 |
| `test_cli` | `test_status_cli_json_permission_error_r2a_1` | `PASSED` | R2a-1 失败回滚撤回回归 |
| `test_cli` | `test_status_cli_preexisting_json_untouched_r2a_2` | `PASSED` | R2a-2 预置哨兵保护回归 |
| `test_cli` | `test_status_cli_preexisting_both_restored_on_json_failure_r2a` | `PASSED` | R2a 双文件恢复回归 |
| `test_cli` | `test_status_cli_dual_fault_json_publish_and_html_restore_failed_r2a` | `PASSED` | R2a 双故障保留现场回归 |
| `test_cli` | `test_status_cli_html_unlink_failed_on_rollback_r2a` | `PASSED` | R2a 撤销失败记录残留回归 |
| `test_cli` | `test_status_cli_output_path_embedded_null_is_reported` | `PASSED` | 空字符路径解析报错回归 |

---

## 2. 独立测试特点

- 阶段 1 新增测试均使用合成微型视频（`testsrc` + `sine`）或精确计算，测试耗时极短（< 0.8s），完全不依赖 200MB 的真实电视剧文件；
- 格式识别、时间码边界、错误提示等均具备完全可独立运行与重跑的自动化测试覆盖。
