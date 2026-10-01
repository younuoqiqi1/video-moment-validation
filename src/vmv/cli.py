"""CLI entrypoint for video-moment-validation (vmv)."""

import argparse
import sys
from pathlib import Path

from vmv.report import run_status_stage
from vmv.media import run_stage1_media_import
from vmv.preview import run_stage1_preview


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vmv",
        description="数智博主视频镜头检索技术验证命令行工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status subcommand (Stage 0)
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

    # import subcommand (Stage 1)
    import_parser = subparsers.add_parser("import", help="导入媒体素材并生成时间码清单 (阶段 1)")
    import_parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=Path("data/input"),
        help="素材输入目录 (默认: data/input)",
    )
    import_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("outputs/stage1"),
        help="阶段 1 产物输出目录 (默认: outputs/stage1)",
    )
    import_parser.add_argument(
        "--target",
        "-t",
        type=str,
        default="qianfu",
        help="优先匹配的素材文件名特征 (默认: qianfu)",
    )
    import_parser.add_argument(
        "--max-duration",
        type=float,
        default=1800.0,
        help="最大分析时长秒数 (默认: 1800.0，即 30 分钟；传 0 分析全片)",
    )
    import_parser.add_argument(
        "--threshold",
        type=float,
        default=0.35,
        help="镜头场景切分敏感度阈值 (默认: 0.35)",
    )

    import_parser.add_argument("--scene-mode", choices=("adaptive", "fixed"), default="adaptive",
                               help="自适应补检或旧固定阈值对照")

    preview_parser = subparsers.add_parser("preview", help="核对现有完整 JSON 并生成本机画面预览")
    preview_parser.add_argument("--media-manifest", type=Path, required=True)
    preview_parser.add_argument("--scenes", type=Path, required=True)
    preview_parser.add_argument("--video", type=Path, required=True)
    preview_parser.add_argument("--output", type=Path, default=Path("outputs/stage1/preview"))
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

    elif args.command == "preview":
        result = run_stage1_preview(args.media_manifest, args.scenes, args.video, args.output)
        if result.status != "passed":
            for error in result.errors:
                print(error)
            return 1
        stats = result.details["statistics"]
        print(f"完整清单数值核对通过：{stats['total_scenes']} 条；最长 {stats['max_duration_sec']} 秒。")
        print("画面预览已生成；真实镜头质量仍需查看图片确认。")
        for artifact in result.artifacts:
            print(artifact)
        return 0

    elif args.command == "import":
        max_dur = args.max_duration if args.max_duration > 0 else None
        result = run_stage1_media_import(
            input_dir=args.input,
            output_dir=args.output,
            target_pattern=args.target,
            max_duration_sec=max_dur,
            scene_threshold=args.threshold,
            scene_mode=args.scene_mode,
        )

        print("=" * 60)
        print("数智博主视频镜头检索技术验证 · 阶段 1 素材导入与时间码清单")
        print("=" * 60)
        print(f"导入状态: {'✔ 通过' if result.status == 'passed' else ('⚠ 阻塞' if result.status == 'blocked' else '✘ 失败')}")

        if result.status == "passed":
            det = result.details
            print(f"素材标识: {det.get('media_id')}")
            print(f"素材文件: {det.get('filename')}")
            print(f"素材时长: {det.get('duration_timecode')} ({det.get('duration_sec')} 秒)")
            print(f"画面尺寸: {det.get('resolution')} @ {det.get('fps')} fps ({det.get('video_codec')})")
            print(f"音频编码: {det.get('audio_codec')}")
            print(f"字幕状态: {det.get('subtitles')}")
            print(f"镜头总数: {det.get('total_scenes')} 个切分镜头")
            print("\n生成产物:")
            for art in result.artifacts:
                print(f"  - {art}")
            return 0
        else:
            print("\n问题说明:")
            for err in result.errors:
                print(f"  * {err}")
            if result.artifacts:
                print("\n生成诊断报告:")
                for art in result.artifacts:
                    print(f"  - {art}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

