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
    parser_script = subparsers.add_parser("script")
    parser_script.add_argument("--input", required=True, type=Path)
    parser_script.add_argument("--output", type=Path, default=Path("outputs/stage2/draft"))
    parser_script.add_argument("--sample", action="store_true")

    parser_review = subparsers.add_parser("script-review")
    parser_review.add_argument("--draft", required=True, type=Path)
    parser_review.add_argument("--requirements", required=True, type=Path)
    parser_review.add_argument("--output", type=Path, default=Path("outputs/stage2/confirmed"))
    for command, flags in {
        "retrieve": ("script", "catalog", "video", "output"),
        "caption-packet": ("catalog", "video", "output"),
        "caption-import": ("packet", "response", "output"),
        "candidate-review": ("candidates", "review", "output"),
    }.items():
        sub = subparsers.add_parser(command)
        for flag in flags:
            sub.add_argument("--" + flag, required=True, type=Path)
        if command == "retrieve":
            sub.add_argument("--assisted-rankings", type=Path)
    from vmv.production_cli import register_stage4
    register_stage4(subparsers)
    from vmv.stage5_cli import register_stage5
    register_stage5(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in ("audio-import", "render"):
        from vmv.stage5_cli import run_stage5
        return run_stage5(args)

    if args.command in ("production-edit", "build-order"):
        from vmv.production_cli import run_stage4
        return run_stage4(args)

    if args.command in ("retrieve", "caption-packet", "caption-import", "candidate-review"):
        import json
        import subprocess
        from vmv.retrieval import run_retrieval, validate_review
        from vmv.retrieval_assistance import export_analysis_packet, import_descriptions
        try:
            if args.command == "retrieve":
                run_retrieval(args.script, args.catalog, args.video, args.output, args.assisted_rankings)
            elif args.command == "caption-packet":
                export_analysis_packet(args.catalog, args.video, args.output)
            elif args.command == "caption-import":
                import_descriptions(args.packet, args.response, args.output)
            else:
                if args.output.exists():
                    raise FileExistsError("输出文件已存在")
                doc = json.loads(args.candidates.read_text(encoding="utf-8"))
                review = json.loads(args.review.read_text(encoding="utf-8"))
                validate_review(review, doc)
                with args.output.open("x", encoding="utf-8") as handle:
                    json.dump(review, handle, ensure_ascii=False, indent=2)
            print("阶段3产物已生成；候选质量仍需人工审核。")
            return 0
        except (ValueError, OSError, RuntimeError) as e:
            print(f"错误: {e}")
            return 1
        except subprocess.SubprocessError:
            print("错误: 媒体处理失败或超时，未完成交付")
            return 1

    if args.command in ("script", "script-review"):
        from vmv.script import prepare_script, confirm_script
        try:
            if args.command == "script":
                res = prepare_script(args.input, args.output, sample=args.sample)
            else:
                if not getattr(args, "draft", None):
                    raise ValueError("缺少 --draft 参数")
                res = confirm_script(args.draft, args.requirements, args.output)
            state = res.get("state", "")
            state_cn = {"draft": "草稿", "confirmed": "已确认"}.get(state, state)
            count = len(res.get("segments") or [])
            print(f"状态: {state_cn} ({state})")
            print(f"分段数量: {count}")
            if res.get("sample"):
                print("【合成测试稿】")
            if state == "draft" or args.command == "script":
                print("提示: 草稿需要复核 (draft needs review)")
            return 0
        except (ValueError, UnicodeError, OSError) as e:
            print(f"错误: {e}")
            return 1

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

