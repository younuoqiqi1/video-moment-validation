"""CLI entrypoint for video-moment-validation (vmv)."""

import argparse
import json
import sys
from pathlib import Path

from vmv.report import run_status_stage
from vmv.runner import LocalTaskRunner
from vmv.runner_service import install_service, stop_service, get_service_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vmv",
        description="数智博主视频镜头检索技术验证命令行工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. status subcommand
    status_parser = subparsers.add_parser("status", help="检查本地运行环境并生成核验报告")
    status_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("outputs/stage0/environment.json"),
        help="环境核验 JSON 报告输出路径 (默认: outputs/stage0/environment.json)",
    )
    status_parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="单个命令探测超时秒数 (默认: 5.0)",
    )

    # 2. runner subcommand
    runner_parser = subparsers.add_parser("runner", help="本地任务后台轮询与执行器")
    runner_sub = runner_parser.add_subparsers(dest="runner_action", required=True)

    # runner once
    once_parser = runner_sub.add_parser("once", help="单次执行队列检查与任务处理")
    once_parser.add_argument("--repo", type=Path, default=Path.cwd(), help="项目根目录绝对路径")

    # runner status
    status_sub = runner_sub.add_parser("status", help="查询后台服务与任务状态")
    status_sub.add_argument("--repo", type=Path, default=Path.cwd(), help="项目根目录绝对路径")

    # runner install
    install_sub = runner_sub.add_parser("install", help="安装并启用用户级后台定时服务")
    install_sub.add_argument("--repo", type=Path, default=Path.cwd(), help="项目根目录绝对路径")
    install_sub.add_argument("--interval", type=int, default=120, help="轮询间隔秒数 (默认: 120)")

    # runner stop
    runner_sub.add_parser("stop", help="停止并卸载后台服务")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        output_path: Path = args.output
        result = run_status_stage(output_path, timeout_sec=args.timeout)

        print("=" * 60)
        print("数智博主视频镜头检索技术验证 · 阶段 0 本地环境核验")
        print("=" * 60)
        print(f"核验状态: {'✔ 通过' if result.status == 'passed' else '✘ 未通过'}")
        print("产物清单:")
        for art in result.artifacts:
            print(f"  - {art}")

        if result.errors or result.status != "passed":
            print("\n未通过原因与错误说明:")
            for err in result.errors:
                print(f"  * {err}")
            print("\n请修正上述问题后重新运行。")
            return 1

        print("\n所有环境依赖检查通过，等待阶段验收。")
        return 0

    elif args.command == "runner":
        action = args.runner_action
        if action == "once":
            runner = LocalTaskRunner(repo_root=args.repo)
            return runner.run_once()

        elif action == "status":
            svc_info = get_service_status()
            print("=" * 60)
            print("本地 AGY 自动接任务服务状态")
            print("=" * 60)
            print(f"服务标识: {svc_info['service_label']}")
            print(f"安装状态: {'已安装' if svc_info['installed'] else '未安装'}")
            print(f"Plist路径: {svc_info['plist_path'] or '-'}")
            print(f"运行状态: {'运行中 (PID: ' + str(svc_info['pid']) + ')' if svc_info['running'] else '空闲/未激活'}")

            runner = LocalTaskRunner(repo_root=args.repo)
            states = runner.load_state()
            if states:
                print("\n本地任务状态清单:")
                for k, v in states.items():
                    print(f"  - [{k}] 状态: {v.status}, 尝试次数: {v.attempt}, 启动时间: {v.started_at or '-'}")
                    if v.last_error:
                        print(f"    说明/门禁: {v.last_error}")
            else:
                print("\n本地暂无持久化任务状态记录。")

            pr_tasks = runner.discover_pr_branch_tasks()
            if pr_tasks:
                print("\n已发现的 PR 分支任务:")
                for pt in pr_tasks:
                    print(f"  - PR #{pt['pr_number']} ({pt['branch']}@{pt['remote_sha'][:7]}): {pt['task_path']}")
                    print(f"    标题: {pt['title']}")
            return 0

        elif action == "install":
            success, msg = install_service(repo_root=args.repo, interval_sec=args.interval)
            print(msg)
            return 0 if success else 1

        elif action == "stop":
            success, msg = stop_service()
            print(msg)
            return 0 if success else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
