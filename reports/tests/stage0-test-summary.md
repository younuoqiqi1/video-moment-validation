# 阶段 0 测试执行摘要 (Stage 0 Test Summary)

- **执行时间**：2026-09-30 (Asia/Shanghai)
- **Python 版本**：Python 3.12.14 (Darwin arm64)
- **测试框架**：pytest 9.1.1, pluggy 1.6.0
- **运行命令**：`.venv/bin/python -m pytest tests/test_cli.py -v`
- **对应代码提交 (code_commit)**：`56c4a9eb49bc091ecb6ae6d944e85741639d7fc2`

---

## 1. 测试结果统计

- **总用例数**：16
- **通过数量**：16 passed
- **失败数量**：0 failed
- **跳过/未运行**：0
- **执行耗时**：~5.20s

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
| `tests/test_cli.py::test_status_cli_html_directory_failure_r2a` | `PASSED` | **R2a 回归**：HTML 目标为目录时，不残留误导性成功 JSON，保留用户原目录 |
| `tests/test_cli.py::test_status_cli_html_permission_error_r2a` | `PASSED` | **R2a 回归**：模拟 HTML 写入权限异常，断言非零且产物不含伪造成功 |
| `tests/test_cli.py::test_status_cli_symlink_loop_r2b` | `PASSED` | **R2b 回归**：符号链接死循环捕获为中文错误，不抛出未处理 RuntimeError |
| `tests/test_cli.py::test_status_cli_resolve_permission_error_r2b` | `PASSED` | **R2b 回归**：Path.resolve 路径权限异常捕获与优雅退出 |
| `tests/test_cli.py::test_status_cli_json_permission_error_r2a_1` | `PASSED` | **R2a-1 必修**：JSON 发布失败时回滚撤销新发布的 HTML，断言不残留任何“通过”结论 |
| `tests/test_cli.py::test_status_cli_preexisting_json_untouched_r2a_2` | `PASSED` | **R2a-2 必修**：预置旧 JSON 哨兵，报告失败时断言旧 JSON 字节完全不变 |
| `tests/test_cli.py::test_status_cli_preexisting_both_restored_on_json_failure_r2a` | `PASSED` | **R2a-1/2 必修**：双预置文件场景下 JSON 失败，断言旧 HTML 与旧 JSON 均完整恢复 |
