"""Real FFmpeg regression fixtures; no private footage or fitted timestamps."""
import shutil
import subprocess

import pytest

from vmv.media import detect_scenes


def fixture(tmp_path, luminance):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg unavailable')
    path = tmp_path / 'fixture.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
        f"nullsrc=s=160x90:r=25:d=4,geq=lum='{luminance}':cb=128:cr=128",
        '-c:v', 'ffv1', str(path)], capture_output=True, check=True)
    return path


def test_low_contrast_hard_cut_recovers_exact_frame(tmp_path):
    video = fixture(tmp_path, 'if(lt(N,50),80,92)')
    scenes = detect_scenes(video, 4, fps=25)
    assert [s.start_frame for s in scenes] == [0, 50]
    assert scenes[0].end_frame == scenes[1].start_frame
    assert scenes[-1].end_sec == 4


def test_dark_low_contrast_composition_cut_below_old_floor(tmp_path):
    # A dark highlight moves across the frame at a hard cut. The FFmpeg scene
    # score is below the former absolute 0.06 floor, but above the tuned floor.
    video = fixture(tmp_path,
        'if(lt(N,50),if(lt(X,16),32,8),if(gt(X,144),32,8))')
    scenes = detect_scenes(video, 4, fps=25)
    assert [s.start_frame for s in scenes] == [0, 50]
    assert scenes[0].end_frame == scenes[1].start_frame


@pytest.mark.parametrize('luminance', [
    'if(lt(N,50),if(lt(X,80),20,24),if(lt(X,80),24,20))',
    'if(lt(N,50),40-N/3,28)',
])
def test_dark_spatial_cut_and_cut_after_fade_recover_boundary(tmp_path, luminance):
    # Same mean brightness, different spatial layout; or a cut after fading.
    # The physical edit is at frame 50, independently of detector output.
    video = fixture(tmp_path, luminance)
    assert [s.start_frame for s in detect_scenes(video, 4)] == [0, 50]
    assert [s.start_frame for s in detect_scenes(video, 4, mode='fixed')] == [0]


@pytest.mark.parametrize('luminance', [
    '40-N/4', '22+mod(N,2)', 'if(eq(N,50),26,22)',
    'if(lt(mod(X+N,160),80),20,24)',
])
def test_dark_fade_noise_and_flash_are_not_cuts(tmp_path, luminance):
    assert [s.start_frame for s in detect_scenes(fixture(tmp_path, luminance), 4)] == [0]


def test_fade_through_black_has_one_transition_candidate(tmp_path):
    video = fixture(tmp_path,
        '16+min(30,abs(N-50))*1.0+if(lt(N,50),if(lt(X,80),2,0),if(lt(X,80),0,2))')
    assert [s.start_frame for s in detect_scenes(video, 4)] == [0, 50]


def test_one_frame_black_pulse_is_not_a_fade_transition(tmp_path):
    assert [s.start_frame for s in detect_scenes(
        fixture(tmp_path, 'if(eq(N,50),16,46)'), 4)] == [0]


def test_continuing_motion_speed_change_is_not_a_low_score_cut():
    from vmv.scene_detection import select_cutpoints
    # Sustained inter-frame motion changes speed once: scene-score is a
    # local peak, but the absolute frame difference continues at that level.
    rows = [(i/25, .05 if i == 50 else .001,
             .08 if i < 50 else .13, 50) for i in range(100)]
    assert select_cutpoints(rows, 25, 4) == []


def test_fixed_mode_preserves_baseline_for_comparison(tmp_path):
    video = fixture(tmp_path, 'if(lt(N,50),80,92)')
    assert len(detect_scenes(video, 4, mode='fixed')) == 1


@pytest.mark.parametrize('luminance', ['80+N/2', '80', 'if(eq(N,50),180,80)'])
def test_gradual_light_static_and_single_frame_flash_are_not_cuts(tmp_path, luminance):
    assert len(detect_scenes(fixture(tmp_path, luminance), 4)) == 1


def test_strong_cut_and_duration_limit(tmp_path):
    video = fixture(tmp_path, 'if(lt(N,50),30,180)')
    assert [s.start_frame for s in detect_scenes(video, 4)] == [0, 50]
    assert len(detect_scenes(video, 4, max_duration_sec=1.5)) == 1
    assert detect_scenes(video, 4, max_duration_sec=1.5)[-1].end_sec == 1.5


def test_continuous_motion_does_not_create_cuts(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg unavailable')
    path = tmp_path / 'motion.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
        'testsrc2=s=160x90:r=25:d=4', '-c:v', 'ffv1', str(path)], check=True, capture_output=True)
    assert len(detect_scenes(path, 4)) == 1


@pytest.mark.parametrize('rows', [[(0, 0, 0)], [(0, 0, 0), (1, 0, 0)],
    [(0,0,0),(.04,0,0),(.02,0,0)]])
def test_incomplete_or_nonmonotonic_scores_cannot_claim_full_coverage(monkeypatch, rows):
    import vmv.media as media
    monkeypatch.setattr(media, 'read_frame_scores', lambda *a: rows)
    with pytest.raises(media.MediaProbeError):
        detect_scenes(None, 1800, fps=25)


@pytest.mark.parametrize('frame', [98,99])
def test_endpoint_flash_is_not_a_tiny_final_scene(tmp_path, frame):
    assert len(detect_scenes(fixture(tmp_path, f'if(eq(N,{frame}),180,80)'), 4)) == 1


def test_long_metadata_output_has_no_interleaved_writers(tmp_path):
    import subprocess
    from vmv.scene_detection import read_frame_scores
    video = tmp_path / 'metadata-buffer.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
        'testsrc2=s=32x32:r=25:d=100', '-c:v', 'ffv1', str(video)],
        capture_output=True, check=True)
    rows = read_frame_scores(video, 100)
    assert len(rows) == 2500
    assert rows[0][0] == 0
    assert rows[-1][0] == 99.96
    assert all(right[0] > left[0] for left, right in zip(rows, rows[1:]))
