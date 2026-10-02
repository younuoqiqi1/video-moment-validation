import copy
import math
import pytest
from vmv.editorial_plan import validate_plan


@pytest.fixture
def valid_video_clip():
    return {
        "kind": "video",
        "job": "render_job_1",
        "start_sec": 1.0,
        "frames": 24,
    }


@pytest.fixture
def valid_color_clip_black():
    return {
        "kind": "color",
        "color": "black",
        "frames": 24,
    }


@pytest.fixture
def valid_color_clip_white():
    return {
        "kind": "color",
        "color": "white",
        "frames": 24,
    }


@pytest.fixture
def base_plan(valid_video_clip):
    return {
        "fps": 24,
        "expected_frames": 24,
        "clips": [valid_video_clip],
    }


def test_valid_minimal_video_plan(base_plan):
    res = validate_plan(base_plan, source_duration=5.0)
    assert res["duration_sec"] == pytest.approx(1.0)
    assert len(res["clips"]) == 1
    clip = res["clips"][0]
    assert clip["timeline_in_frame"] == 0
    assert clip["timeline_out_frame"] == 24
    assert clip["source_out_sec"] == pytest.approx(2.0)


def test_valid_reordered_touching_montage():
    # Source duration 10.0 seconds, 24 fps
    # Clip 1: [4.0, 6.0] (48 frames)
    # Clip 2: [2.0, 4.0] (48 frames) - touches clip 1 at 4.0, non-monotonic source order
    # Clip 3: [0.0, 2.0] (48 frames) - touches clip 2 at 2.0
    # Clip 4: color "black" (24 frames)
    # Total frames: 48 + 48 + 48 + 24 = 168 frames = 7.0 seconds
    plan = {
        "fps": 24,
        "expected_frames": 168,
        "clips": [
            {"kind": "video", "job": "shot_b", "start_sec": 4.0, "frames": 48},
            {"kind": "video", "job": "shot_a", "start_sec": 2.0, "frames": 48},
            {"kind": "video", "job": "shot_c", "start_sec": 0.0, "frames": 48},
            {"kind": "color", "color": "black", "frames": 24},
        ],
    }
    res = validate_plan(plan, source_duration=10.0)

    assert res["duration_sec"] == pytest.approx(7.0)
    assert len(res["clips"]) == 4

    # Clip 1
    assert res["clips"][0]["timeline_in_frame"] == 0
    assert res["clips"][0]["timeline_out_frame"] == 48
    assert res["clips"][0]["source_out_sec"] == pytest.approx(6.0)

    # Clip 2
    assert res["clips"][1]["timeline_in_frame"] == 48
    assert res["clips"][1]["timeline_out_frame"] == 96
    assert res["clips"][1]["source_out_sec"] == pytest.approx(4.0)

    # Clip 3
    assert res["clips"][2]["timeline_in_frame"] == 96
    assert res["clips"][2]["timeline_out_frame"] == 144
    assert res["clips"][2]["source_out_sec"] == pytest.approx(2.0)

    # Clip 4 (color clip has no source_out_sec)
    assert res["clips"][3]["timeline_in_frame"] == 144
    assert res["clips"][3]["timeline_out_frame"] == 168


def test_valid_color_clips_black_and_white(valid_color_clip_black, valid_color_clip_white):
    plan = {
        "fps": 30,
        "expected_frames": 48,
        "clips": [valid_color_clip_black, valid_color_clip_white],
    }
    res = validate_plan(plan, source_duration=1.0)
    assert res["duration_sec"] == pytest.approx(48 / 30)
    assert res["clips"][0]["timeline_in_frame"] == 0
    assert res["clips"][0]["timeline_out_frame"] == 24
    assert res["clips"][1]["timeline_in_frame"] == 24
    assert res["clips"][1]["timeline_out_frame"] == 48


def test_deep_copy_input_immutability(base_plan):
    original_copy = copy.deepcopy(base_plan)
    res = validate_plan(base_plan, source_duration=5.0)

    assert base_plan == original_copy
    assert res is not base_plan
    assert res["clips"] is not base_plan["clips"]
    assert res["clips"][0] is not base_plan["clips"][0]


@pytest.mark.parametrize(
    "critical_in, critical_out",
    [
        (1.0, 2.0),
        (1.2, 1.8),
    ],
)
def test_valid_critical_in_out_sec(critical_in, critical_out):
    plan = {
        "fps": 24,
        "expected_frames": 24,
        "clips": [
            {
                "kind": "video",
                "job": "shot_main",
                "start_sec": 1.0,
                "frames": 24,
                "critical_in_sec": critical_in,
                "critical_out_sec": critical_out,
            }
        ],
    }
    res = validate_plan(plan, source_duration=5.0)
    assert res["clips"][0]["critical_in_sec"] == pytest.approx(critical_in)
    assert res["clips"][0]["critical_out_sec"] == pytest.approx(critical_out)


@pytest.mark.parametrize(
    "bad_critical",
    [
        {"critical_in_sec": 1.2},
        {"critical_out_sec": 1.8},
        {"critical_in_sec": 1.8, "critical_out_sec": 1.2},
        {"critical_in_sec": 0.9, "critical_out_sec": 1.8},
        {"critical_in_sec": 1.2, "critical_out_sec": 2.1},
        {"critical_in_sec": float("nan"), "critical_out_sec": 1.8},
        {"critical_in_sec": 1.2, "critical_out_sec": float("inf")},
        {"critical_in_sec": True, "critical_out_sec": 1.8},
        {"critical_in_sec": 1.2, "critical_out_sec": False},
    ],
)
def test_invalid_critical_in_out_sec(bad_critical):
    clip = {
        "kind": "video",
        "job": "shot_crit",
        "start_sec": 1.0,
        "frames": 24,
        **bad_critical,
    }
    plan = {"fps": 24, "expected_frames": 24, "clips": [clip]}
    with pytest.raises(ValueError):
        validate_plan(plan, source_duration=5.0)


@pytest.mark.parametrize(
    "bad_fps",
    [0, -1, 121, 24.0, True, False, "24", float("nan"), float("inf"), None],
)
def test_reject_invalid_fps(base_plan, bad_fps):
    base_plan["fps"] = bad_fps
    with pytest.raises(ValueError):
        validate_plan(base_plan, source_duration=5.0)


@pytest.mark.parametrize(
    "bad_expected_frames",
    [0, -5, 24.0, True, False, "24", None, float("nan")],
)
def test_reject_invalid_expected_frames_type(base_plan, bad_expected_frames):
    base_plan["expected_frames"] = bad_expected_frames
    with pytest.raises(ValueError):
        validate_plan(base_plan, source_duration=5.0)


def test_reject_frame_sum_mismatch(base_plan):
    base_plan["expected_frames"] = 48
    with pytest.raises(ValueError):
        validate_plan(base_plan, source_duration=5.0)


@pytest.mark.parametrize(
    "bad_clips",
    [[], None, "clips", 123, [None], ["not_a_dict"], [{}]],
)
def test_reject_invalid_clips_container_or_elements(bad_clips):
    plan = {"fps": 24, "expected_frames": 24, "clips": bad_clips}
    with pytest.raises(ValueError):
        validate_plan(plan, source_duration=5.0)


@pytest.mark.parametrize(
    "bad_kind",
    ["audio", "image", "raw", "", 123, None, True],
)
def test_reject_invalid_clip_kind(bad_kind):
    plan = {
        "fps": 24,
        "expected_frames": 24,
        "clips": [{"kind": bad_kind, "frames": 24}],
    }
    with pytest.raises(ValueError):
        validate_plan(plan, source_duration=5.0)


@pytest.mark.parametrize(
    "bad_color",
    ["red", "blue", "gray", "", None, 123, True],
)
def test_reject_invalid_color_values(bad_color):
    plan = {
        "fps": 24,
        "expected_frames": 24,
        "clips": [{"kind": "color", "color": bad_color, "frames": 24}],
    }
    with pytest.raises(ValueError):
        validate_plan(plan, source_duration=5.0)


@pytest.mark.parametrize(
    "bad_frames",
    [0, -1, 10.5, True, False, "10", None, float("nan")],
)
def test_reject_invalid_clip_frames(bad_frames):
    plan = {
        "fps": 24,
        "expected_frames": 24,
        "clips": [{"kind": "color", "color": "black", "frames": bad_frames}],
    }
    with pytest.raises(ValueError):
        validate_plan(plan, source_duration=5.0)


@pytest.mark.parametrize(
    "bad_job",
    ["", "   ", "\t\n", None, 123, True],
)
def test_reject_invalid_video_job(bad_job):
    plan = {
        "fps": 24,
        "expected_frames": 24,
        "clips": [{"kind": "video", "job": bad_job, "start_sec": 0.0, "frames": 24}],
    }
    with pytest.raises(ValueError):
        validate_plan(plan, source_duration=5.0)


@pytest.mark.parametrize(
    "bad_start_sec",
    [-0.1, -1.0, True, False, "0", None, float("nan"), float("inf"), float("-inf")],
)
def test_reject_invalid_video_start_sec(bad_start_sec):
    plan = {
        "fps": 24,
        "expected_frames": 24,
        "clips": [{"kind": "video", "job": "job1", "start_sec": bad_start_sec, "frames": 24}],
    }
    with pytest.raises(ValueError):
        validate_plan(plan, source_duration=5.0)


@pytest.mark.parametrize(
    "bad_source_duration",
    [0, -1.0, -0.001, True, False, "10.0", None, float("nan"), float("inf")],
)
def test_reject_invalid_source_duration(base_plan, bad_source_duration):
    with pytest.raises(ValueError):
        validate_plan(base_plan, source_duration=bad_source_duration)


def test_reject_clip_end_beyond_source_duration():
    plan = {
        "fps": 24,
        "expected_frames": 48,
        "clips": [{"kind": "video", "job": "job_a", "start_sec": 4.0, "frames": 48}],
    }
    with pytest.raises(ValueError):
        validate_plan(plan, source_duration=5.5)


def test_reject_source_interval_overlaps_same_or_different_shots():
    plan = {
        "fps": 24,
        "expected_frames": 84,
        "clips": [
            {"kind": "video", "job": "shot_1", "start_sec": 1.0, "frames": 48},
            {"kind": "video", "job": "shot_2", "start_sec": 2.5, "frames": 36},
        ],
    }
    with pytest.raises(ValueError):
        validate_plan(plan, source_duration=10.0)


def test_reject_non_dict_plan():
    with pytest.raises(ValueError):
        validate_plan(["not_a_dict"], source_duration=5.0)


def test_null_critical_range_rejected(base_plan):
    base_plan["clips"][0]["critical_in_sec"] = None
    base_plan["clips"][0]["critical_out_sec"] = None
    with pytest.raises(ValueError):
        validate_plan(base_plan, 5.0)
