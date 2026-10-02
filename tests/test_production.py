import copy
import hashlib
import importlib
import pytest


def get_builder():
    try:
        return getattr(importlib.import_module("vmv.production"), "build_production_order")
    except (ImportError, AttributeError) as exc:
        pytest.fail(f"vmv.production.build_production_order missing: {exc}")


def get_doc_hash(doc_obj):
    try:
        return importlib.import_module("vmv.retrieval").document_hash(doc_obj)
    except (ImportError, AttributeError):
        import json
        return hashlib.sha256(json.dumps(doc_obj, sort_keys=True).encode("utf-8")).hexdigest()


@pytest.fixture
def fixtures():
    text = "红色画面。"
    text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    media_sha = "a" * 64
    script = {
        "sample": True,
        "state": "confirmed",
        "source_text": text,
        "source_sha256": text_sha,
        "segments": [{"id": "seg-001", "start": 0, "end": 5, "narration": text, "status": "confirmed"}],
    }
    catalog = {
        "sample": True,
        "media_id": "test",
        "source_sha256": media_sha,
        "duration_sec": 10,
        "shots": [
            {"id": "shot-a", "start_sec": 0, "end_sec": 5, "caption": "shot a"},
            {"id": "shot-b", "start_sec": 5, "end_sec": 10, "caption": "shot b"},
        ],
    }
    doc = {
        "sample": True,
        "media_id": "test",
        "script_sha256": text_sha,
        "catalog_sha256": media_sha,
        "segments": [
            {
                "id": "seg-001",
                "narration": text,
                "visual_requirement": "red screen",
                "candidates": [
                    {"shot_id": "shot-a", "start_sec": 0, "end_sec": 5, "preview": "a.mp4"},
                    {"shot_id": "shot-b", "start_sec": 5, "end_sec": 10, "preview": "b.mp4"},
                ],
            }
        ],
    }
    doc_sha = get_doc_hash(doc)
    doc["document_sha256"] = doc_sha
    selection = {
        "sample": True,
        "document_sha256": doc_sha,
        "segments": [
            {
                "id": "seg-001",
                "shots": [
                    {"shot_id": "shot-b", "in_sec": 6, "out_sec": 9},
                    {"shot_id": "shot-a", "in_sec": 1, "out_sec": 3},
                ],
            }
        ],
    }
    media = {"media": {"media_id": "test", "relative_path": "data/input/test.mp4", "duration_sec": 10, "source_sha256": media_sha}}
    return script, doc, catalog, selection, media


def test_build_production_order_success(fixtures):
    build = get_builder()
    script, doc, catalog, selection, media = copy.deepcopy(fixtures)
    order = build(script, doc, catalog, selection, media)

    assert order["state"] == "ready_for_tts"
    assert order["timing_basis"] == "source_clip_duration_not_voice"
    assert order["source_sha256"] == catalog["source_sha256"]
    assert order["duration_sec"] == 5

    segs = order["segments"]
    assert len(segs) == 1
    assert segs[0]["id"] == "seg-001"
    assert segs[0]["narration"] == "红色画面。"

    shots = segs[0]["shots"]
    assert len(shots) == 2
    assert shots[0] == {
        "shot_id": "shot-b",
        "source_in_sec": 6,
        "source_out_sec": 9,
        "timeline_in_sec": 0,
        "timeline_out_sec": 3,
    }
    assert shots[1] == {
        "shot_id": "shot-a",
        "source_in_sec": 1,
        "source_out_sec": 3,
        "timeline_in_sec": 3,
        "timeline_out_sec": 5,
    }


MUTATIONS = [
    ("out_of_range", lambda s, d, c, sel, m: sel["segments"][0]["shots"][0].__setitem__("out_sec", 11)),
    ("unknown_shot", lambda s, d, c, sel, m: sel["segments"][0]["shots"][0].__setitem__("shot_id", "shot-z")),
    ("duplicate_chosen_id", lambda s, d, c, sel, m: sel["segments"][0]["shots"][1].__setitem__("shot_id", "shot-b")),
    ("empty_segment_selection", lambda s, d, c, sel, m: sel["segments"][0].__setitem__("shots", [])),
    ("changed_doc_hash", lambda s, d, c, sel, m: sel.__setitem__("document_sha256", "0" * 64)),
    ("sample_mismatch", lambda s, d, c, sel, m: s.__setitem__("sample", False)),
    ("sample_wrong_type", lambda s, d, c, sel, m: s.__setitem__("sample", "True")),
    ("draft_script", lambda s, d, c, sel, m: s["segments"][0].__setitem__("status", "draft")),
    ("changed_narration", lambda s, d, c, sel, m: d["segments"][0].__setitem__("narration", "变更旁白")),
    ("nan_time", lambda s, d, c, sel, m: sel["segments"][0]["shots"][0].__setitem__("in_sec", float("nan"))),
    ("bool_time", lambda s, d, c, sel, m: sel["segments"][0]["shots"][0].__setitem__("in_sec", True)),
    ("unsafe_relative_source_path", lambda s, d, c, sel, m: m["media"].__setitem__("relative_path", "../test.mp4")),
    ("invalid_source_sha", lambda s, d, c, sel, m: c.__setitem__("source_sha256", "invalid_sha")),
]


@pytest.mark.parametrize("name,mutate", MUTATIONS)
def test_build_production_order_rejections(fixtures, name, mutate):
    build = get_builder()
    script, doc, catalog, selection, media = copy.deepcopy(fixtures)
    mutate(script, doc, catalog, selection, media)
    with pytest.raises((ValueError, TypeError, KeyError)):
        build(script, doc, catalog, selection, media)

@pytest.mark.parametrize('mutation', ['alias', 'hash', 'precision', 'paragraph'])
def test_reject_validation_bypasses(fixtures, mutation):
    s, d, c, r, m = copy.deepcopy(fixtures)
    if mutation == 'alias':
        r['segments'][0]['shots'] = [dict(r['segments'][0]['shots'][0])]
        r['segments'][0]['shots'][0]['chosen_id'] = 'shot-a'
        r['segments'][0]['shots'][0]['in_sec'] = 1
        r['segments'][0]['shots'][0]['out_sec'] = 3
    elif mutation == 'hash':
        del s['source_sha256']
    elif mutation == 'precision':
        r['segments'][0]['shots'][0].update(in_sec=6, out_sec=6.0000001)
    else:
        text = '红色画面。\n\n红色画面。'
        s['source_text'] = text
        s['source_sha256'] = hashlib.sha256(text.encode()).hexdigest()
        first = s['segments'][0]
        second = dict(first, id='seg-002', start=7, end=12)
        first.update(start=7, end=12)
        s['segments'].append(second)
        d['segments'].append(dict(copy.deepcopy(d['segments'][0]), id='seg-002'))
        r['segments'].append(dict(copy.deepcopy(r['segments'][0]), id='seg-002'))
        d['document_sha256'] = get_doc_hash(d)
        r['document_sha256'] = d['document_sha256']
    with pytest.raises(ValueError):
        get_builder()(s, d, c, r, m)


def test_prepare_production_files_and_embedded_text(fixtures, tmp_path):
    import json
    import re
    from vmv.production_editor import prepare_production
    _, doc, _, _, _ = copy.deepcopy(fixtures)
    doc['segments'][0]['narration'] = '__JS__ </script>'
    doc['document_sha256'] = get_doc_hash(doc)
    raw = json.dumps(doc, ensure_ascii=False, indent=3).encode()
    path = tmp_path / 'candidates.json'
    path.write_bytes(raw)
    for name in ('a.mp4', 'b.mp4'):
        (tmp_path / name).write_bytes(b'preview-copy-test')
    out = tmp_path / 'out'
    prepare_production(path, out)
    assert (out / 'candidates.json').read_bytes() == raw
    assert (out / 'a.mp4').read_bytes() == b'preview-copy-test'
    html = (out / 'editor.html').read_text()
    data = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    assert data and json.loads(data.group(1)) == doc
    with pytest.raises(FileExistsError):
        prepare_production(path, out)


@pytest.mark.parametrize('bad_preview', ['../secret.mp4', 'missing.mp4', 'linked.mp4'])
def test_prepare_production_rejects_preview(fixtures, tmp_path, bad_preview):
    import json
    from vmv.production_editor import prepare_production
    _, doc, _, _, _ = copy.deepcopy(fixtures)
    doc['segments'][0]['candidates'][0]['preview'] = bad_preview
    doc['document_sha256'] = get_doc_hash(doc)
    path = tmp_path / 'candidates.json'
    path.write_text(json.dumps(doc))
    (tmp_path / 'secret.mp4').write_bytes(b'preview')
    (tmp_path / 'linked.mp4').symlink_to(tmp_path / 'secret.mp4')
    with pytest.raises(ValueError):
        prepare_production(path, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('tamper', [False, True])
def test_write_order_file_bindings(fixtures, tmp_path, tamper):
    import json
    from vmv.production import write_order
    s, d, c, r, m = copy.deepcopy(fixtures)
    def write(name, obj):
        p = tmp_path / name
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
        return p
    ps, pc = write('script.json', s), write('catalog.json', c)
    d['script_sha256'] = hashlib.sha256(ps.read_bytes()).hexdigest()
    d['catalog_sha256'] = hashlib.sha256(pc.read_bytes()).hexdigest()
    d['document_sha256'] = get_doc_hash(d)
    r['document_sha256'] = d['document_sha256']
    pd, pr, pm = write('candidates.json', d), write('selection.json', r), write('media.json', m)
    po = tmp_path / 'production-order.json'
    if tamper:
        pc.write_bytes(pc.read_bytes() + b'\n')
        with pytest.raises(ValueError):
            write_order(ps, pd, pc, pr, pm, po)
        assert not po.exists()
    else:
        result = write_order(ps, pd, pc, pr, pm, po)
        assert json.loads(po.read_text()) == result
        assert result['duration_sec'] == 5
        assert result['source_bindings']['selection_sha256'] == hashlib.sha256(pr.read_bytes()).hexdigest()
        with pytest.raises(FileExistsError):
            write_order(ps, pd, pc, pr, pm, po)


def test_editor_javascript_behavior(fixtures, tmp_path):
    import json
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is required for editor logic verification')
    doc = fixtures[1]
    inp, out = tmp_path / 'candidates.json', tmp_path / 'selection.json'
    inp.write_text(json.dumps(doc))
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, str(root / 'tests/production_editor_behavior.cjs'), str(inp), str(out)], cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    exported = json.loads(out.read_text())
    assert exported['document_sha256'] == doc['document_sha256']
    assert [s['shot_id'] for s in exported['segments'][0]['shots']] == ['shot-a', 'shot-b']


@pytest.mark.parametrize('target', ['candidate', 'catalog'])
def test_reject_conflicting_candidate_and_catalog_ids(fixtures, target):
    s, d, c, r, m = copy.deepcopy(fixtures)
    r['segments'][0]['shots'] = [{'shot_id': 'shot-b', 'in_sec': 6, 'out_sec': 9}]
    if target == 'candidate':
        cand = d['segments'][0]['candidates'][1]
        cand['id'] = 'shot-b'
        cand['shot_id'] = 'shot-a'
        d['document_sha256'] = get_doc_hash(d)
        r['document_sha256'] = d['document_sha256']
    else:
        c['shots'][1]['shot_id'] = 'shot-a'
    with pytest.raises(ValueError):
        get_builder()(s, d, c, r, m)
