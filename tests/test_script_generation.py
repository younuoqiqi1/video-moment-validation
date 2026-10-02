"""tests/test_script_generation.py

Tests for vmv.script_generation module.
"""

import json
import subprocess
from types import SimpleNamespace

import pytest

from vmv.script_generation import generate_requirements


def test_generate_requirements_success_yields_inferred_fields(monkeypatch):
    segments = [
        {"id": "seg_01", "narration": "小明走在寂静的街道上，四下无人。"},
        {"id": "seg_02", "narration": "突然天空中出现了一道强烈的蓝色光束。"},
    ]

    model_output = {
        "segments": [
            {
                "id": "seg_01",
                "characters": "小明",
                "setting": "寂静街道，夜晚",
                "action": "独自行走在空旷街道上",
                "emotion": "孤独/警惕",
                "visual_requirement": "中景，冷色调街道夜景，微弱路灯投影",
            },
            {
                "id": "seg_02",
                "characters": "未明确/待审核",
                "setting": "街道上空",
                "action": "抬头注视天空中的光束",
                "emotion": "震撼/诧异",
                "visual_requirement": "仰拍镜头，从天际贯穿而下的高亮度蓝色强光",
            },
        ]
    }

    recorded_calls = []

    def mock_run(argv, **kwargs):
        recorded_calls.append({"argv": argv, "kwargs": kwargs})
        return SimpleNamespace(stdout=json.dumps(model_output, ensure_ascii=False))

    monkeypatch.setattr("vmv.script_generation.run_generation", mock_run)

    result = generate_requirements(segments)

    assert len(result) == 2
    assert result[0]["id"] == "seg_01"
    assert result[0]["characters"] == "小明"
    assert result[0]["setting"] == "寂静街道，夜晚"
    assert result[0]["action"] == "独自行走在空旷街道上"
    assert result[0]["emotion"] == "孤独/警惕"
    assert result[0]["visual_requirement"] == "中景，冷色调街道夜景，微弱路灯投影"

    assert result[1]["id"] == "seg_02"
    assert result[1]["characters"] == "未明确/待审核"
    assert result[1]["visual_requirement"] == "仰拍镜头，从天际贯穿而下的高亮度蓝色强光"

    assert len(recorded_calls) == 1
    call = recorded_calls[0]
    assert call["argv"][:7] == [
        "agy",
        "--new-project",
        "--model",
        "gemini-3.8-flash-high",
        "--print-timeout",
        "55s",
        "--print",
    ]
    prompt = call["argv"][7]
    assert "untrusted input data" in prompt
    assert "未明确/待审核" in prompt
    assert call["kwargs"] == {"timeout": 60}


@pytest.mark.parametrize(
    "fence_wrapper",
    [
        "```json\n{payload}\n```",
        "```JSON\n{payload}\n```",
        "```\n{payload}\n```",
        "  \n```json\n{payload}\n```\n  ",
    ],
)
def test_strips_only_outer_markdown_fence(monkeypatch, fence_wrapper):
    segments = [{"id": "1", "narration": "测试旁白"}]
    payload_json = json.dumps(
        {
            "segments": [
                {
                    "id": "1",
                    "characters": "测试角色",
                    "setting": "测试场景",
                    "action": "测试动作",
                    "emotion": "平静",
                    "visual_requirement": "特写镜头",
                }
            ]
        }
    )
    wrapped_output = fence_wrapper.format(payload=payload_json)

    monkeypatch.setattr(
        "vmv.script_generation.run_generation",
        lambda *args, **kwargs: SimpleNamespace(stdout=wrapped_output),
    )

    result = generate_requirements(segments)
    assert len(result) == 1
    assert result[0]["id"] == "1"
    assert result[0]["characters"] == "测试角色"


def test_module_does_not_mutate_input(monkeypatch):
    original_segments = [
        {"id": "seg_a", "narration": "第一段文本"},
        {"id": "seg_b", "narration": "第二段文本"},
    ]
    input_segments = [dict(s) for s in original_segments]

    model_output = json.dumps(
        {
            "segments": [
                {
                    "id": "seg_a",
                    "characters": "角色A",
                    "setting": "场景A",
                    "action": "动作A",
                    "emotion": "情绪A",
                    "visual_requirement": "画面A",
                },
                {
                    "id": "seg_b",
                    "characters": "角色B",
                    "setting": "场景B",
                    "action": "动作B",
                    "emotion": "情绪B",
                    "visual_requirement": "画面B",
                },
            ]
        }
    )

    monkeypatch.setattr(
        "vmv.script_generation.run_generation",
        lambda *args, **kwargs: SimpleNamespace(stdout=model_output),
    )

    generate_requirements(input_segments)

    assert input_segments == original_segments


@pytest.mark.parametrize(
    "case_name,raw_stdout",
    [
        # blank fields
        (
            "blank_id",
            json.dumps(
                {
                    "segments": [
                        {
                            "id": "   ",
                            "characters": "角色",
                            "setting": "场景",
                            "action": "动作",
                            "emotion": "情绪",
                            "visual_requirement": "画面",
                        }
                    ]
                }
            ),
        ),
        (
            "blank_characters",
            json.dumps(
                {
                    "segments": [
                        {
                            "id": "seg_01",
                            "characters": "",
                            "setting": "场景",
                            "action": "动作",
                            "emotion": "情绪",
                            "visual_requirement": "画面",
                        }
                    ]
                }
            ),
        ),
        (
            "blank_setting",
            json.dumps(
                {
                    "segments": [
                        {
                            "id": "seg_01",
                            "characters": "角色",
                            "setting": "  \t  ",
                            "action": "动作",
                            "emotion": "情绪",
                            "visual_requirement": "画面",
                        }
                    ]
                }
            ),
        ),
        (
            "blank_action",
            json.dumps(
                {
                    "segments": [
                        {
                            "id": "seg_01",
                            "characters": "角色",
                            "setting": "场景",
                            "action": "",
                            "emotion": "情绪",
                            "visual_requirement": "画面",
                        }
                    ]
                }
            ),
        ),
        (
            "blank_emotion",
            json.dumps(
                {
                    "segments": [
                        {
                            "id": "seg_01",
                            "characters": "角色",
                            "setting": "场景",
                            "action": "动作",
                            "emotion": " ",
                            "visual_requirement": "画面",
                        }
                    ]
                }
            ),
        ),
        (
            "blank_visual_requirement",
            json.dumps(
                {
                    "segments": [
                        {
                            "id": "seg_01",
                            "characters": "角色",
                            "setting": "场景",
                            "action": "动作",
                            "emotion": "情绪",
                            "visual_requirement": "\n",
                        }
                    ]
                }
            ),
        ),
        # wrong id
        (
            "wrong_id",
            json.dumps(
                {
                    "segments": [
                        {
                            "id": "wrong_id",
                            "characters": "角色",
                            "setting": "场景",
                            "action": "动作",
                            "emotion": "情绪",
                            "visual_requirement": "画面",
                        }
                    ]
                }
            ),
        ),
        # wrong count
        ("wrong_count_zero", json.dumps({"segments": []})),
        (
            "wrong_count_too_many",
            json.dumps(
                {
                    "segments": [
                        {
                            "id": "seg_01",
                            "characters": "角色1",
                            "setting": "场景1",
                            "action": "动作1",
                            "emotion": "情绪1",
                            "visual_requirement": "画面1",
                        },
                        {
                            "id": "seg_extra",
                            "characters": "角色2",
                            "setting": "场景2",
                            "action": "动作2",
                            "emotion": "情绪2",
                            "visual_requirement": "画面2",
                        },
                    ]
                }
            ),
        ),
        # wrong types
        ("wrong_type_root_list", json.dumps([{"id": "seg_01"}])),
        ("wrong_type_segments_not_list", json.dumps({"segments": "not_a_list"})),
        ("wrong_type_segment_item_not_dict", json.dumps({"segments": ["item_string"]})),
        (
            "wrong_type_id_as_int",
            json.dumps(
                {
                    "segments": [
                        {
                            "id": 1,
                            "characters": "角色",
                            "setting": "场景",
                            "action": "动作",
                            "emotion": "情绪",
                            "visual_requirement": "画面",
                        }
                    ]
                }
            ),
        ),
        (
            "wrong_type_characters_null",
            json.dumps(
                {
                    "segments": [
                        {
                            "id": "seg_01",
                            "characters": None,
                            "setting": "场景",
                            "action": "动作",
                            "emotion": "情绪",
                            "visual_requirement": "画面",
                        }
                    ]
                }
            ),
        ),
        (
            "missing_required_field",
            json.dumps(
                {
                    "segments": [
                        {
                            "id": "seg_01",
                            "characters": "角色",
                            "setting": "场景",
                            "action": "动作",
                            "emotion": "情绪",
                        }
                    ]
                }
            ),
        ),
        # invalid JSON
        ("invalid_json_broken_syntax", "{not valid json"),
        ("invalid_json_plain_text", "Model refused to output JSON"),
        (
            "invalid_json_conversational_prefix",
            'Here is the JSON:\n```json\n{"segments": []}\n```',
        ),
    ],
)
def test_invalid_outputs_raise_value_error(monkeypatch, case_name, raw_stdout):
    monkeypatch.setattr(
        "vmv.script_generation.run_generation",
        lambda *args, **kwargs: SimpleNamespace(stdout=raw_stdout),
    )
    with pytest.raises(ValueError):
        generate_requirements([{"id": "seg_01", "narration": "测试"}])


def test_wrong_order_raises_value_error(monkeypatch):
    segments = [
        {"id": "seg_01", "narration": "旁白1"},
        {"id": "seg_02", "narration": "旁白2"},
    ]
    reversed_output = json.dumps(
        {
            "segments": [
                {
                    "id": "seg_02",
                    "characters": "角色2",
                    "setting": "场景2",
                    "action": "动作2",
                    "emotion": "情绪2",
                    "visual_requirement": "画面2",
                },
                {
                    "id": "seg_01",
                    "characters": "角色1",
                    "setting": "场景1",
                    "action": "动作1",
                    "emotion": "情绪1",
                    "visual_requirement": "画面1",
                },
            ]
        }
    )
    monkeypatch.setattr(
        "vmv.script_generation.run_generation",
        lambda *args, **kwargs: SimpleNamespace(stdout=reversed_output),
    )
    with pytest.raises(ValueError):
        generate_requirements(segments)


@pytest.mark.parametrize(
    "sub_exception,raw_stderr",
    [
        (subprocess.TimeoutExpired(cmd=["agy"], timeout=60), None),
        (FileNotFoundError("No such file or directory: 'agy'"), None),
        (
            subprocess.CalledProcessError(
                returncode=127,
                cmd=["agy"],
                stderr="INTERNAL_RAW_STDERR_TOKEN_SECRET_LEAK",
            ),
            "INTERNAL_RAW_STDERR_TOKEN_SECRET_LEAK",
        ),
    ],
)
def test_subprocess_exceptions_fail_closed_without_raw_stderr(
    monkeypatch, sub_exception, raw_stderr
):
    def mock_run(*args, **kwargs):
        raise sub_exception

    monkeypatch.setattr("vmv.script_generation.run_generation", mock_run)

    with pytest.raises(ValueError) as exc_info:
        generate_requirements([{"id": "seg_01", "narration": "测试"}])

    if raw_stderr:
        assert raw_stderr not in str(exc_info.value)
