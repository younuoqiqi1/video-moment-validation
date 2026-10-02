import hashlib
import json
from types import SimpleNamespace
import pytest
from vmv.retrieval import rank_candidates, run_retrieval, validate_review


def requirement():
    return dict(id='seg-001', narration='余则成递出信件。', characters='余则成', setting='室内', action='递出信件', emotion='迟疑', visual_requirement='余则成递出信件的近景')


def shots():
    return [dict(id='shot-1', start_sec=0, end_sec=2, caption='余则成在室内递出信件', subtitle=''), dict(id='shot-2', start_sec=2, end_sec=4, caption='室内桌边人物读书', subtitle=''), dict(id='shot-3', start_sec=4, end_sec=6, caption='大海浪花', subtitle='')]


def test_ranking_matching_caption_and_no_fabricated_matches():
    results = rank_candidates(requirement(), shots())
    assert results[0]['shot_id'] == 'shot-1'
    assert len(results) <= 3
    assert 'shot-3' not in [r['shot_id'] for r in results]
    assert rank_candidates(requirement(), [shots()[2]]) == []


def test_maximum_three_and_duplicate_suppression():
    corpus = [{**shots()[0], 'id': f'shot-{i}'} for i in range(6)]
    results = rank_candidates(requirement(), corpus + corpus, limit=10)
    assert len(results) == 3
    assert len({r['shot_id'] for r in results}) == 3


def fixture_inputs(tmp_path):
    text = '余则成递出信件。'
    script = dict(sample=True, state='confirmed', source_text=text, source_sha256=hashlib.sha256(text.encode()).hexdigest(), segments=[{**requirement(), 'start': 0, 'end': len(text), 'status': 'confirmed'}])
    video = tmp_path / 'sample.mp4'; video.write_bytes(b'synthetic-video')
    catalog = dict(sample=True, description_source='synthetic', media_id='synthetic-01', source_sha256=hashlib.sha256(video.read_bytes()).hexdigest(), duration_sec=6, shots=shots())
    sp=tmp_path/'script.json'; cp=tmp_path/'catalog.json'
    sp.write_text(json.dumps(script)); cp.write_text(json.dumps(catalog))
    return sp, cp, video, script, catalog


def mock_media(monkeypatch):
    monkeypatch.setattr('vmv.retrieval.shutil.which', lambda name: name)
    def run(argv, timeout=60):
        if 'ffprobe' in argv[0]:
            if '-count_frames' in argv:
                return SimpleNamespace(stdout=json.dumps({'streams':[{'nb_read_frames':'50','width':480,'height':270}]}))
            return SimpleNamespace(stdout='6.0\n')
        from pathlib import Path
        Path(argv[-1]).write_bytes(b'preview')
        return SimpleNamespace(stdout='')
    monkeypatch.setattr('vmv.retrieval.run_generation', run)


def test_run_outputs_bound_playable_candidates_and_pending_review(tmp_path, monkeypatch):
    sp,cp,video,script,catalog=fixture_inputs(tmp_path); mock_media(monkeypatch)
    out=tmp_path/'out'; result=run_retrieval(sp,cp,video,out)
    data=json.loads((out/'candidates.json').read_text())
    assert data['method']=='lexical_baseline' and data['sample'] is True
    assert data['script_sha256']==hashlib.sha256(sp.read_bytes()).hexdigest()
    assert data['catalog_sha256']==hashlib.sha256(cp.read_bytes()).hexdigest()
    assert data['segments'][0]['candidates'][0]['shot_id']=='shot-1'
    assert all((out / c['preview']).exists() for c in data['segments'][0]['candidates'])
    html=(out/'review.html').read_text()
    assert '<video' in html and 'all_unsuitable' in html


@pytest.mark.parametrize('case',['hash','negative','beyond','bool','duplicate','draft','sample','offset','nan','script_root','catalog_root','field_type','offset_bool'])
def test_invalid_inputs_rejected_without_outputs(tmp_path,monkeypatch,case):
    sp,cp,video,script,catalog=fixture_inputs(tmp_path); mock_media(monkeypatch)
    if case=='hash':catalog['source_sha256']='a'*64
    elif case=='negative':catalog['shots'][0]['start_sec']=-1
    elif case=='beyond':catalog['shots'][0]['end_sec']=7
    elif case=='bool':catalog['shots'][0]['start_sec']=False
    elif case=='duplicate':catalog['shots'][1]['id']='shot-1'
    elif case=='draft':script['state']='draft'
    elif case=='sample':catalog['sample']=False
    elif case=='offset':script['segments'][0]['end']=1
    elif case=='nan':catalog['duration_sec']=float('nan')
    elif case=='script_root':script=[]
    elif case=='catalog_root':catalog=[]
    elif case=='field_type':script['segments'][0]['visual_requirement']=100
    elif case=='offset_bool':script['segments'][0]['start']=False
    sp.write_text(json.dumps(script));cp.write_text(json.dumps(catalog));out=tmp_path/'out'
    with pytest.raises(ValueError):run_retrieval(sp,cp,video,out)
    assert not out.exists()


def test_extraction_failure_atomic_no_partial_delivery(tmp_path,monkeypatch):
    sp,cp,video,script,catalog=fixture_inputs(tmp_path);mock_media(monkeypatch)
    def fail(argv,timeout=60):
        if 'ffprobe' in argv[0]:return SimpleNamespace(stdout='6.0')
        raise ValueError('extract failed')
    monkeypatch.setattr('vmv.retrieval.run_generation',fail)
    with pytest.raises(ValueError):run_retrieval(sp,cp,video,tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_review_rejects_pending_and_bindings(tmp_path,monkeypatch):
    sp,cp,video,script,catalog=fixture_inputs(tmp_path);mock_media(monkeypatch)
    run_retrieval(sp,cp,video,tmp_path/'out')
    d=json.loads((tmp_path/'out'/'candidates.json').read_text())
    candidates=d['segments'][0]['candidates']
    r={k:d[k] for k in ('sample','script_sha256','catalog_sha256','document_sha256')}
    r['segments']=[dict(id='seg-001',all_unsuitable=True,candidates=[dict(shot_id=c['shot_id'],decision='reject') for c in candidates])]
    assert validate_review(r,d)==r
    r['segments'][0]['candidates'][0]['decision']='pending'
    with pytest.raises(ValueError):validate_review(r,d)
    r['segments'][0]['candidates'][0]['decision']='reject';r['script_sha256']='wrong'
    with pytest.raises(ValueError):validate_review(r,d)


def test_zero_frame_success_is_not_delivered(tmp_path,monkeypatch):
    sp,cp,video,script,catalog=fixture_inputs(tmp_path);mock_media(monkeypatch)
    def run(argv,timeout=60):
        return SimpleNamespace(stdout='6.0' if 'ffprobe' in argv[0] else '')
    monkeypatch.setattr('vmv.retrieval.run_generation',run)
    with pytest.raises(ValueError):run_retrieval(sp,cp,video,tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_review_is_bound_to_exact_candidate_document(tmp_path,monkeypatch):
    sp,cp,video,script,catalog=fixture_inputs(tmp_path);mock_media(monkeypatch)
    run_retrieval(sp,cp,video,tmp_path/'out')
    d=json.loads((tmp_path/'out'/'candidates.json').read_text())
    r={k:d.get(k) for k in ('sample','script_sha256','catalog_sha256','document_sha256')}
    r['segments']=[dict(id='seg-001',all_unsuitable=True,candidates=[dict(shot_id=c['shot_id'],decision='reject') for c in d['segments'][0]['candidates']])]
    d['segments'][0]['candidates'][0]['start_sec']=1
    with pytest.raises(ValueError):validate_review(r,d)
