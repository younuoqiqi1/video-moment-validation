import pytest

from vmv.cut_comparison import compare_cutpoints


def test_comparison_keeps_unlabelled_candidates_unknown_and_one_to_one():
    result = compare_cutpoints([50], [50, 100, 101, 180], [100, 101, 200], tolerance_frames=1)
    assert result['reference_count'] == 3
    assert result['reference_matched_before'] == 0
    assert result['reference_matched_after'] == 2
    assert result['reference_unmatched_frames'] == [200]
    assert result['added_candidate_frames'] == [100, 101, 180]
    assert result['unlabelled_added_frames'] == [180]
    assert result['false_cut_rate'] is None
    assert result['human_visual_review'] == 'not_verified'
    assert compare_cutpoints([], [100], [100, 101], 1)['reference_matched_after'] == 1


@pytest.mark.parametrize('refs', [[100,100], [-1], [1.5], [True]])
def test_invalid_reference_frames_fail(refs):
    with pytest.raises(ValueError):
        compare_cutpoints([], [], refs)


def test_real_rerun_preserves_sources_and_generates_preview(tmp_path, monkeypatch):
    import json
    import shutil
    import subprocess
    from vmv.cut_comparison import rerun
    from vmv.media import run_stage1_media_import
    from vmv.preview import file_hash
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg unavailable')
    inputs = tmp_path / 'input'
    inputs.mkdir()
    video = inputs / 'fixture.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
        "nullsrc=s=160x90:r=25:d=4,geq=lum='if(lt(N,50),80,92)':cb=128:cr=128",
        '-c:v', 'ffv1', str(video)], check=True, capture_output=True)
    baseline = tmp_path / 'baseline'
    assert run_stage1_media_import(inputs, baseline, repo_root=tmp_path,
                                  scene_mode='fixed').status == 'passed'
    manifest = baseline / 'media_manifest.json'
    scenes = baseline / json.loads(manifest.read_text())['scene_manifest_file']
    snapshot = {p.name: p.read_bytes() for p in baseline.iterdir()}
    reference = tmp_path / 'reference.json'
    reference.write_text(json.dumps({'source_video_sha256': file_hash(video),
        'source_scenes_sha256': file_hash(scenes), 'source_media_manifest_sha256': file_hash(manifest),
        'fps': 25, 'analyzed_duration_sec': 4, 'reference_frames': [50]}))
    output = tmp_path / 'candidate'
    result = rerun(video, manifest, scenes, reference, output)
    assert result['baseline_reproduced']
    assert result['reference_matched_before'] == 0
    assert result['reference_matched_after'] == 1
    assert result['before_statistics']['total_scenes'] == 1
    assert result['after_statistics']['total_scenes'] == 2
    assert result['numeric_validation'] == 'passed'
    assert result['preview_image_count'] == 6
    assert (output / 'preview/summary.html').is_file()
    assert snapshot == {p.name: p.read_bytes() for p in baseline.iterdir()}
    assert str(tmp_path) not in json.dumps(result)
    with pytest.raises(FileExistsError):
        rerun(video, manifest, scenes, reference, output)
    import vmv.cut_comparison as comparison
    real_preview = comparison.run_stage1_preview
    def changed_during_processing(*args):
        result = real_preview(*args)
        with video.open('ab') as handle:
            handle.write(b'changed-after-preview')
        return result
    monkeypatch.setattr(comparison, 'run_stage1_preview', changed_during_processing)
    with pytest.raises(ValueError, match='发生变化'):
        rerun(video, manifest, scenes, reference, tmp_path / 'drift')
    assert not (tmp_path / 'drift/comparison.json').exists()
    data = json.loads(reference.read_text())
    data['source_video_sha256'] = '0'*64
    reference.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='不匹配'):
        rerun(video, manifest, scenes, reference, tmp_path / 'wrong')
    assert not (tmp_path / 'wrong').exists()
