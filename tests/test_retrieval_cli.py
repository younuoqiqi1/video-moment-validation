from vmv.cli import main
from test_retrieval import fixture_inputs, mock_media


def test_retrieve_cli_outputs_candidates(tmp_path,monkeypatch):
    sp,cp,video,script,catalog=fixture_inputs(tmp_path);mock_media(monkeypatch)
    assert main(['retrieve','--script',str(sp),'--catalog',str(cp),'--video',str(video),'--output',str(tmp_path/'out')])==0
    assert (tmp_path/'out'/'review.html').exists()
