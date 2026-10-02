import json
import subprocess
import sys
from types import SimpleNamespace
import pytest
from vmv.script import prepare_script

FIELDS = ('characters', 'setting', 'action', 'emotion', 'visual_requirement')


def test_prepare_prefills_generated_fields_and_keeps_review_pending(tmp_path, monkeypatch):
    fields = dict(zip(FIELDS, ('人物甲', '室内桌边', '放书抬头', '警觉', '人物放下书并望向门口的近景')))
    monkeypatch.setitem(sys.modules, 'vmv.script_generation', SimpleNamespace(generate_requirements=lambda segments: [fields]))
    source = tmp_path / 'source.txt'
    source.write_text('人物甲放下书，抬头望向门口。')
    result = prepare_script(source, tmp_path / 'draft', sample=True)
    assert all(result['segments'][0][key] == value for key, value in fields.items())
    assert result['segments'][0]['status'] == 'needs_review'
    assert result['state'] == 'draft'
    html = (tmp_path / 'draft' / 'summary.html').read_text()
    assert '人物放下书并望向门口的近景' in html


def test_generation_failure_never_creates_empty_review_page(tmp_path, monkeypatch):
    def fail(segments):
        raise ValueError('生成失败')
    monkeypatch.setitem(sys.modules, 'vmv.script_generation', SimpleNamespace(generate_requirements=fail))
    source = tmp_path / 'source.txt'
    source.write_text('人物甲放下书。')
    with pytest.raises(ValueError, match='生成失败'):
        prepare_script(source, tmp_path / 'draft')
    assert not (tmp_path / 'draft').exists()


def test_existing_output_rejected_before_generation(tmp_path, monkeypatch):
    def forbidden(segments):
        raise AssertionError('不得调用模型')
    monkeypatch.setitem(sys.modules, 'vmv.script_generation', SimpleNamespace(generate_requirements=forbidden))
    source = tmp_path / 'source.txt'
    source.write_text('人物甲放下书。')
    output = tmp_path / 'draft'
    output.mkdir()
    with pytest.raises(FileExistsError):
        prepare_script(source, output)
