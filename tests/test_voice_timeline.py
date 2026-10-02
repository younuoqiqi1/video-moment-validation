# tests/test_voice_timeline.py
import copy
import math
import pytest


def _get_plan_timeline():
    """Lazily import plan_timeline to prevent pytest collection failures."""
    try:
        from vmv.voice_timeline import plan_timeline
        return plan_timeline
    except Exception as exc:
        pytest.fail(f"Failed to import vmv.voice_timeline.plan_timeline: {exc}")


@pytest.fixture
def base_order():
    """Standard valid order dictionary matching the generic public specification."""
    return {
        "state": "ready_for_tts",
        "sample": True,
        "media_id": "test",
        "source_sha256": "a" * 64,
        "source_path": "data/input/test.mp4",
        "document_sha256": "b" * 64,
        "timing_basis": "source_clip_duration_not_voice",
        "duration_sec": 8,
        "segments": [
            {
                "id": "seg-001",
                "narration": "合成测试。",
                "shots": [
                    {
                        "shot_id": "a",
                        "source_in_sec": 1,
                        "source_out_sec": 5,
                        "timeline_in_sec": 0,
                        "timeline_out_sec": 4,
                    },
                    {
                        "shot_id": "b",
                        "source_in_sec": 8,
                        "source_out_sec": 12,
                        "timeline_in_sec": 4,
                        "timeline_out_sec": 8,
                    },
                ],
            }
        ],
    }


def test_normal_two_shot_four_sec_output_ranges(base_order):
    plan_timeline = _get_plan_timeline()
    """Test normal 2-shot 4-sec output ranges, verifying immutability and literal expectations."""
    order_snapshot = copy.deepcopy(base_order)
    audio_durations = {"seg-001": 4}

    result = plan_timeline(base_order, audio_durations, fps=25)

    # Immutability assertion
    assert base_order == order_snapshot, "plan_timeline must not mutate the input order"

    # Literal output assertions
    assert result["fps"] == 25
    assert result["timing_basis"] == "voice_duration"
    assert result["duration_sec"] == 4
    assert len(result["segments"]) == 1

    seg = result["segments"][0]
    assert seg["id"] == "seg-001"
    assert seg["narration"] == "合成测试。"
    assert seg["audio_duration_sec"] == 4
    assert seg["timeline_in_sec"] == 0
    assert seg["timeline_out_sec"] == 4
    assert len(seg["shots"]) == 2

    # Capacity-weighted frame allocation:
    # Shot a capacity = 4s, Shot b capacity = 4s -> equal 2s each
    shot_a = seg["shots"][0]
    assert shot_a["shot_id"] == "a"
    assert shot_a["source_in_sec"] == 1
    assert shot_a["source_out_sec"] == 3
    assert shot_a["timeline_in_sec"] == 0
    assert shot_a["timeline_out_sec"] == 2

    shot_b = seg["shots"][1]
    assert shot_b["shot_id"] == "b"
    assert shot_b["source_in_sec"] == 8
    assert shot_b["source_out_sec"] == 10
    assert shot_b["timeline_in_sec"] == 2
    assert shot_b["timeline_out_sec"] == 4


def test_voice_duration_ceiling_to_frames_continuous_and_no_overflow(base_order):
    plan_timeline = _get_plan_timeline()
    """Voice duration 4.01s ceilings to 101 frames (4.04s at 25fps) without gaps or source overflow."""
    audio_durations = {"seg-001": 4.01}
    result = plan_timeline(base_order, audio_durations, fps=25)

    assert result["fps"] == 25
    assert result["timing_basis"] == "voice_duration"
    assert math.isclose(result["duration_sec"], 4.04, abs_tol=1e-5)

    seg = result["segments"][0]
    assert seg["id"] == "seg-001"
    assert seg["audio_duration_sec"] == 4.01
    assert seg["timeline_in_sec"] == 0
    assert math.isclose(seg["timeline_out_sec"], 4.04, abs_tol=1e-5)

    shots = seg["shots"]
    assert len(shots) == 2

    shot_0, shot_1 = shots[0], shots[1]

    # Continuous timeline slots with no gaps/freezes
    assert shot_0["timeline_in_sec"] == 0
    assert math.isclose(shot_0["timeline_out_sec"], shot_1["timeline_in_sec"], abs_tol=1e-5)
    assert math.isclose(shot_1["timeline_out_sec"], 4.04, abs_tol=1e-5)

    dur_0 = shot_0["timeline_out_sec"] - shot_0["timeline_in_sec"]
    dur_1 = shot_1["timeline_out_sec"] - shot_1["timeline_in_sec"]

    # Each chosen shot >= 1 frame (1/25 = 0.04s)
    assert dur_0 >= 0.04
    assert dur_1 >= 0.04
    assert math.isclose(dur_0 + dur_1, 4.04, abs_tol=1e-5)

    # Source intervals trimmed from their selected start without source overflow
    assert shot_0["source_in_sec"] == 1
    assert math.isclose(shot_0["source_out_sec"], 1 + dur_0, abs_tol=1e-5)
    assert shot_0["source_out_sec"] <= 5

    assert shot_1["source_in_sec"] == 8
    assert math.isclose(shot_1["source_out_sec"], 8 + dur_1, abs_tol=1e-5)
    assert shot_1["source_out_sec"] <= 12


def test_voice_duration_exceeding_available_source_rejected(base_order):
    plan_timeline = _get_plan_timeline()
    """Voice duration of 9s exceeds total available source capacity (8s) and must be rejected."""
    audio_durations = {"seg-001": 9}
    with pytest.raises(ValueError):
        plan_timeline(base_order, audio_durations, fps=25)


def test_missing_audio_rejected(base_order):
    plan_timeline = _get_plan_timeline()
    """Missing audio duration entry for required segment must be rejected."""
    with pytest.raises(ValueError):
        plan_timeline(base_order, {}, fps=25)

    with pytest.raises(ValueError):
        plan_timeline(base_order, {"other-segment": 4}, fps=25)


@pytest.mark.parametrize(
    "invalid_duration",
    [0, -1, -0.01, float("nan"), float("inf"), float("-inf"), True, False],
)
def test_invalid_voice_duration_parametrized_rejected(base_order, invalid_duration):
    plan_timeline = _get_plan_timeline()
    """Zero, negative, NaN, Inf, and boolean audio durations must be rejected."""
    with pytest.raises(ValueError):
        plan_timeline(base_order, {"seg-001": invalid_duration}, fps=25)


@pytest.mark.parametrize(
    "unconfirmed_state",
    ["draft", "unconfirmed", "processing", "ready_for_audio", "completed", ""],
)
def test_unconfirmed_state_rejected(base_order, unconfirmed_state):
    plan_timeline = _get_plan_timeline()
    """Orders with state other than 'ready_for_tts' must be rejected."""
    base_order["state"] = unconfirmed_state
    with pytest.raises(ValueError):
        plan_timeline(base_order, {"seg-001": 4}, fps=25)


def test_duplicate_selected_id_rejected(base_order):
    plan_timeline = _get_plan_timeline()
    """Duplicate shot IDs within the same segment must be rejected."""
    base_order["segments"][0]["shots"][1]["shot_id"] = "a"
    with pytest.raises(ValueError):
        plan_timeline(base_order, {"seg-001": 4}, fps=25)


def test_audio_point_zero_one_sec_for_two_shots_rejected(base_order):
    plan_timeline = _get_plan_timeline()
    """0.01s (1 frame ceiling) cannot accommodate 2 shots with >=1 frame each, so it must be rejected."""
    audio_durations = {"seg-001": 0.01}
    with pytest.raises(ValueError):
        plan_timeline(base_order, audio_durations, fps=25)


@pytest.mark.parametrize("invalid_fps", [True, False, 0, -25, 23.976, 29.97, 0.5])
def test_invalid_fps_rejected(base_order, invalid_fps):
    plan_timeline = _get_plan_timeline()
    """FPS values that are boolean, zero, negative, or fractional must be rejected."""
    with pytest.raises(ValueError):
        plan_timeline(base_order, {"seg-001": 4}, fps=invalid_fps)


def test_repeated_same_shot_id_in_different_segments_permitted():
    plan_timeline = _get_plan_timeline()
    """Repeated shot_id across DIFFERENT segments is permitted if unique per segment.

    Uses seg-001 and seg-002 with 2 shots each (4s capacity), 1s audio per segment,
    verifying 2s total output and 0, 1, 2 segment boundaries.
    """
    two_segment_order = {
        "state": "ready_for_tts",
        "sample": True,
        "media_id": "test",
        "source_sha256": "a" * 64,
        "source_path": "data/input/test.mp4",
        "document_sha256": "b" * 64,
        "timing_basis": "source_clip_duration_not_voice",
        "duration_sec": 16,
        "segments": [
            {
                "id": "seg-001",
                "narration": "第一段解说。",
                "shots": [
                    {
                        "shot_id": "shot-shared-1",
                        "source_in_sec": 1,
                        "source_out_sec": 5,
                        "timeline_in_sec": 0,
                        "timeline_out_sec": 4,
                    },
                    {
                        "shot_id": "shot-shared-2",
                        "source_in_sec": 8,
                        "source_out_sec": 12,
                        "timeline_in_sec": 4,
                        "timeline_out_sec": 8,
                    },
                ],
            },
            {
                "id": "seg-002",
                "narration": "第二段解说。",
                "shots": [
                    # Same shot_ids reused in different segment
                    {
                        "shot_id": "shot-shared-1",
                        "source_in_sec": 1,
                        "source_out_sec": 5,
                        "timeline_in_sec": 8,
                        "timeline_out_sec": 12,
                    },
                    {
                        "shot_id": "shot-shared-2",
                        "source_in_sec": 8,
                        "source_out_sec": 12,
                        "timeline_in_sec": 12,
                        "timeline_out_sec": 16,
                    },
                ],
            },
        ],
    }

    audio_durations = {"seg-001": 1, "seg-002": 1}

    result = plan_timeline(two_segment_order, audio_durations, fps=25)

    assert result["fps"] == 25
    assert result["timing_basis"] == "voice_duration"
    assert result["duration_sec"] == 2
    assert len(result["segments"]) == 2

    seg1 = result["segments"][0]
    seg2 = result["segments"][1]

    # Verify 0, 1, 2 segment boundaries
    assert seg1["id"] == "seg-001"
    assert seg1["audio_duration_sec"] == 1
    assert seg1["timeline_in_sec"] == 0
    assert seg1["timeline_out_sec"] == 1

    assert seg2["id"] == "seg-002"
    assert seg2["audio_duration_sec"] == 1
    assert seg2["timeline_in_sec"] == 1
    assert seg2["timeline_out_sec"] == 2

    # Check that each shot inside each segment was scheduled without error
    for seg in (seg1, seg2):
        assert len(seg["shots"]) == 2
        for shot in seg["shots"]:
            dur = shot["timeline_out_sec"] - shot["timeline_in_sec"]
            assert dur >= 0.04  # >= 1 frame
            assert math.isclose(shot["source_out_sec"] - shot["source_in_sec"], dur, abs_tol=1e-5)


def test_reject_newline_in_segment_identifier(base_order):
    plan = _get_plan_timeline()
    base_order['segments'][0]['id'] = 'seg-001\n'
    with pytest.raises(ValueError):
        plan(base_order, {'seg-001\n': 4})
