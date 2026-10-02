import hashlib
import json
import pytest
from vmv.retrieval_assistance import assisted_candidates, import_descriptions


def test_assisted_rankings_use_grounded_times_and_binding(tmp_path):
    path=tmp_path/'ranking.json'
    data=dict(method='GPT_assisted',sample=True,script_sha256='s',catalog_sha256='c',segments=[dict(id='seg-001',candidates=[dict(shot_id='shot-1',reason='书信交接对应递出信件')])])
    path.write_text(json.dumps(data))
    result=assisted_candidates(path,'s','c',[dict(id='seg-001')],[dict(id='shot-1',start_sec=0,end_sec=2)],True)
    assert result['seg-001'][0]['start_sec']==0
    assert result['seg-001'][0]['end_sec']==2
    data['segments'][0]['candidates'][0]['shot_id']='invented';path.write_text(json.dumps(data))
    with pytest.raises(ValueError):assisted_candidates(path,'s','c',[dict(id='seg-001')],[dict(id='shot-1',start_sec=0,end_sec=2)],True)


@pytest.mark.parametrize('case',['binding','count','id','caption','sample'])
def test_description_import_rejects_tampering(tmp_path,case):
    catalog=dict(sample=True,media_id='synthetic',source_sha256='v',duration_sec=2,shots=[dict(id='shot-1',start_sec=0,end_sec=2)])
    raw=json.dumps(catalog)
    packet=dict(sample=True,catalog=catalog,catalog_original_utf8=raw,catalog_sha256=hashlib.sha256(raw.encode()).hexdigest(),source_sha256='v',shots=[dict(id='shot-1',start_sec=0,end_sec=2)])
    response=dict(catalog_sha256=packet['catalog_sha256'],source_sha256='v',descriptions=[dict(id='shot-1',caption='红色画面',subtitle='')])
    if case=='binding':response['catalog_sha256']='wrong'
    elif case=='count':response['descriptions']=[]
    elif case=='id':response['descriptions'][0]['id']='wrong'
    elif case=='caption':response['descriptions'][0]['caption']=''
    elif case=='sample':packet['catalog']['sample']=False
    pp=tmp_path/'packet.json';rp=tmp_path/'response.json'
    pp.write_text(json.dumps(packet));rp.write_text(json.dumps(response))
    with pytest.raises(ValueError):import_descriptions(pp,rp,tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_description_import_accepts_absent_subtitles_and_preserves_sample(tmp_path):
    catalog=dict(sample=True,media_id='synthetic',source_sha256='v',duration_sec=2,shots=[dict(id='shot-1',start_sec=0,end_sec=2)])
    raw=json.dumps(catalog);sha=hashlib.sha256(raw.encode()).hexdigest()
    packet=dict(sample=True,catalog=catalog,catalog_original_utf8=raw,catalog_sha256=sha,source_sha256='v',shots=catalog['shots'])
    response=dict(catalog_sha256=sha,source_sha256='v',descriptions=[dict(id='shot-1',caption='红色画面',subtitle='')])
    pp=tmp_path/'packet.json';rp=tmp_path/'response.json';pp.write_text(json.dumps(packet));rp.write_text(json.dumps(response))
    result=import_descriptions(pp,rp,tmp_path/'out')
    output=json.loads(__import__('pathlib').Path(result).read_text())
    assert output['sample'] is True and output['shots'][0]['subtitle']==''
    assert output['description_source']=='model_assisted'


def test_low_fps_packet_never_lists_missing_images(tmp_path):
    import shutil
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('需要真实ffmpeg与ffprobe')
    from vmv.generation_process import run_generation
    from vmv.retrieval import verify_visual_file
    from vmv.retrieval_assistance import export_analysis_packet
    video=tmp_path/'one-fps.mp4'
    run_generation(['ffmpeg','-v','error','-f','lavfi','-i','color=red:size=64x64:rate=1:duration=2','-c:v','libx264','-pix_fmt','yuv420p','-y',str(video)],timeout=60)
    catalog=dict(sample=True,media_id='one-fps',source_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),duration_sec=2,shots=[dict(id='shot-1',start_sec=0,end_sec=2)])
    cp=tmp_path/'catalog.json';cp.write_text(json.dumps(catalog));out=tmp_path/'packet'
    export_analysis_packet(cp,video,out)
    packet=json.loads((out/'packet.json').read_text())
    for frame in packet['shots'][0]['frames']:verify_visual_file(out/frame['path'])
    assert packet['shots'][0]['frames'][-1]['seconds'] < 1.96
