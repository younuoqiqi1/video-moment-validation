"""Unit tests for VMV Stage 4/5 render command and pipeline."""

import json
from pathlib import Path
import pytest
from vmv.cli import build_parser
from vmv.render import parse_timecode_to_seconds, seconds_to_ass_time, split_subtitle_lines


def test_timecode_helpers():
    assert parse_timecode_to_seconds("00:01:23.450") == 83.45
    assert parse_timecode_to_seconds("01:23.500") == 83.5
    assert seconds_to_ass_time(83.45) == "0:01:23.45"
    assert seconds_to_ass_time(3661.05) == "1:01:01.05"


def test_split_subtitle_lines():
    short = "这是简短文字"
    assert split_subtitle_lines(short) == short

    long_text = "老周重看第18集：余则成最大的危机，正是这顿东来顺涮肉。"
    split_res = split_subtitle_lines(long_text)
    assert "\\N" in split_res
    lines = split_res.split("\\N")
    assert len(lines) == 2
    assert lines[0] == "老周重看第18集：余则成最大的危机，"
    assert lines[1] == "正是这顿东来顺涮肉。"


def test_cli_parser_render():
    parser = build_parser()
    args = parser.parse_args([
        "render",
        "--order", "test_order.json",
        "--output", "test_out.mp4",
        "--source", "test_src.mp4",
        "--force-fallback-tts",
    ])
    assert args.command == "render"
    assert args.order == Path("test_order.json")
    assert args.output == Path("test_out.mp4")
    assert args.source == Path("test_src.mp4")
    assert args.force_fallback_tts is True
