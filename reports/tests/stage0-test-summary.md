# 阶段 0 测试执行摘要 (Stage 0 Test Summary)

- **执行时间**：2026-09-30 (Asia/Shanghai)
- **Python 版本**：Python 3.12.14 (Darwin arm64)
- **测试框架**：pytest 9.1.1, pluggy 1.6.0
- **运行命令**：`.venv/bin/python -m pytest tests/test_cli.py -v`
- **对应代码提交**：`84319872b0cf76e6545004f6aed65287b9e5aca8`

---

## 1. 测试结果统计

- **总用例数**：9
- **通过数量**：9 passed
- **失败数量**：0 failed
- **跳过/未运行**：0
- **执行耗时**：~0.33s

---

## 2. 详细用例清单

| 用例名称 | 判定结果 | 说明与覆盖项 |
| :--- | :---: | :--- |
| `tests/test_cli.py::test_probe_tool_version_timeout` | `PASSED` | 子进程探测命令超时异常保护 |
| `tests/test_cli.py::test_probe_tool_version_not_found` | `PASSED` | 探测未安装工具时优雅处理并返回错误说明 |
| `tests/test_cli.py::test_check_environment_missing_ffmpeg` | `PASSED` | 缺少 FFmpeg / ffprobe 时的判定与报错 |
| `tests/test_cli.py::test_status_cli_all_passed` | `PASSED` | 全环境达标时返回 0 并生成完整 JSON/HTML |
| `tests/test_cli.py::test_status_cli_chinese_and_spaces_path` | `PASSED` | 中文及带空格路径的自适应与原子写入 |
| `tests/test_cli.py::test_status_cli_missing_tool_exit_code_1` | `PASSED` | 缺失依赖项时退出码为 1 并列出清单 |
| `tests/test_cli.py::test_status_cli_rejects_non_json_output_r1` | `PASSED` | **R1 回归**：拒绝非 `.json` 目标，保护同名哨兵文件不被覆写 |
| `tests/test_cli.py::test_status_cli_filesystem_error_handling_r2` | `PASSED` | **R2 回归**：捕获目录冲突与路径阻断异常，非零退出且无误导性成功信息 |
| `tests/test_cli.py::test_status_cli_python_version_insufficient` | `PASSED` | **补充测试**：Python < 3.12 判定与报告失败校验 |
