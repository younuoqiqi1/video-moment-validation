from pathlib import Path


def register_stage5(subparsers):
    p_audio = subparsers.add_parser("audio-import", help="导入音频分段映射")
    p_audio.add_argument("--order", type=Path, required=True, help="工单路径")
    p_audio.add_argument("--audio", action="append", required=True, help="音频条目，格式: SEG_ID=FILE")
    p_audio.add_argument("--output", type=Path, required=True, help="输出音频快照目录")

    p_render = subparsers.add_parser("render", help="执行视频画面与音频渲染")
    p_render.add_argument("--order", type=Path, required=True, help="工单路径")
    p_render.add_argument("--media-root", type=Path, required=True, help="素材根目录路径")
    p_render.add_argument("--audio-manifest", type=Path, required=True, help="音频清单路径")
    p_render.add_argument("--subtitle-font-name", help="自定义字体的家族名")
    p_render.add_argument("--subtitle-font", type=Path, help="支持中文的本地字体文件")
    p_render.add_argument("--output", type=Path, required=True, help="输出产物目录")


def run_stage5(args) -> int:
    try:
        if args.command == "audio-import":
            from vmv.voice_import import import_audio

            sources = {}
            for item in args.audio:
                parts = item.split("=", 1)
                if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                    raise ValueError(f"无效的音频映射项（需符合 SEG_ID=FILE 且不可为空）: {item}")
                seg_id, file_path = parts[0].strip(), parts[1].strip()
                if seg_id in sources:
                    raise ValueError(f"检测到重复的 SEG_ID: {seg_id}")
                sources[seg_id] = Path(file_path)

            import_audio(args.order, sources, args.output)
        elif args.command == "render":
            from vmv.render import render

            render(args.order, args.media_root, args.audio_manifest, args.output, subtitle_font=args.subtitle_font, subtitle_font_name=args.subtitle_font_name)
        else:
            raise ValueError(f"不支持的子命令: {args.command}")

        print(f"执行成功，结果位置: {args.output}\n模拟配音，仅供样片验证")
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(f"执行失败: {exc}")
        return 1
