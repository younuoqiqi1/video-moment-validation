from pathlib import Path
from vmv import production
from vmv import production_editor


def register_stage4(subparsers):
    p_edit = subparsers.add_parser("production-edit")
    p_edit.add_argument("--candidates", required=True, type=Path)
    p_edit.add_argument("--output", required=True, type=Path)

    p_order = subparsers.add_parser("build-order")
    for opt in (
        "--script",
        "--candidates",
        "--catalog",
        "--selection",
        "--media",
        "--output",
    ):
        p_order.add_argument(opt, required=True, type=Path)


def run_stage4(args):
    try:
        if args.command == "production-edit":
            production_editor.prepare_production(args.candidates, args.output)
        elif args.command == "build-order":
            production.write_order(
                args.script,
                args.candidates,
                args.catalog,
                args.selection,
                args.media,
                args.output,
            )
        print("完成，生产单时序尚未配音")
        return 0
    except (ValueError, OSError, TypeError, KeyError) as e:
        print(f"错误: {e}")
        return 1
