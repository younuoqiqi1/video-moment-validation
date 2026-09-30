"""CLI entrypoint for video-moment-validation (vmv)."""

import argparse
import sys
from pathlib import Path

from vmv.report import run_status_stage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vmv",
        description="数智博主视频镜头检索技术验证命令行工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status subcommand
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

        print("\n所有环境依赖检查通过，可以进入下一阶段。")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
