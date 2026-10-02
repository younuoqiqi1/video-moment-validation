from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import tempfile

try:
    from vmv.retrieval.document_hash import document_hash
except ImportError:
    from vmv.retrieval import document_hash

__all__ = ["generate_editor", "prepare_production"]

_SAFE_ASCII_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_PREVIEW_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\.mp4$")


def generate_editor(doc: dict) -> str:
    """
    校验输入文档并基于同目录的 HTML/JS 模板生成编辑器 HTML。

    严格遵循字段约束：
    - 根字典必须包含布尔类型的 sample
    - document_sha256 必须与 document_hash(doc) 一致（严禁使用 content_hash 等别名）
    - segments 必须为非空列表（严禁使用 shots 等别名）
    - 每个 segment 必须具有安全 ASCII 的 id
    - 每个 candidate 必须具有安全 ASCII 的 shot_id（严禁使用 id/candidate_id 等别名）
    """
    if not isinstance(doc, dict):
        raise ValueError("Document root must be a dictionary")

    if "sample" not in doc or type(doc["sample"]) is not bool:
        raise ValueError("Document root 'sample' must be an exact boolean")

    if "document_sha256" not in doc or doc["document_sha256"] != document_hash(doc):
        raise ValueError(
            "Document 'document_sha256' is missing or does not match document_hash(doc)"
        )

    segments = doc.get("segments")
    if not isinstance(segments, list) or len(segments) == 0:
        raise ValueError("Document 'segments' must be a non-empty list")

    for seg in segments:
        if not isinstance(seg, dict):
            raise ValueError("Every segment must be a dictionary")
        seg_id = seg.get("id")
        if not isinstance(seg_id, str) or not _SAFE_ASCII_PATTERN.fullmatch(seg_id):
            raise ValueError(f"Segment id must be a safe ASCII string: {seg_id!r}")

        candidates = seg.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError(f"Segment {seg_id!r} 'candidates' must be a list")

        for cand in candidates:
            if not isinstance(cand, dict):
                raise ValueError("Every candidate must be a dictionary")
            shot_id = cand.get("shot_id")
            if not isinstance(shot_id, str) or not _SAFE_ASCII_PATTERN.fullmatch(shot_id):
                raise ValueError(
                    f"Candidate shot_id must be a safe ASCII string: {shot_id!r}"
                )

    module_dir = Path(__file__).resolve().parent
    html_path = module_dir / "production_editor.html"
    js_path = module_dir / "production_editor.js"

    html_template = html_path.read_text(encoding="utf-8")
    js_content = js_path.read_text(encoding="utf-8")

    # 防止内联 <script> 被截断注入，将 '<' 替换为 '\\u003c'
    data_json = json.dumps(doc, ensure_ascii=False).replace("<", "\\u003c")

    editor_html = html_template.replace("__JS__", js_content).replace("__DATA__", data_json)
    return editor_html


def prepare_production(path: str | Path, outdir: str | Path) -> str:
    """
    校验输入文件与候选视频预览文件，通过原子同级临时目录构建生产产物目录。

    步骤：
    1. 若输出目录已存在则直接拒绝 (refuseexists)
    2. 读取 JSON 文件原始二进制并解析校验
    3. 调用 generate_editor 校验并生成 editor.html
    4. 扁平化收集 candidates 并逐一校验预览文件（名称规范、非软链接、存在且非空、父目录与文档一致）
    5. 全部校验通过后创建同级临时目录
    6. 复制 preview 视频，写入 candidates.json (raw bytes) 和 editor.html (generated)
    7. 原子重命名临时目录至目标目录，finally 中清理残留临时文件
    8. 返回目标路径字符串
    """
    doc_path = Path(path).resolve()
    out_dest = Path(outdir)

    if out_dest.exists():
        raise FileExistsError(f"Output directory already exists: {out_dest}")

    raw_bytes = doc_path.read_bytes()
    doc = json.loads(raw_bytes)

    editor_html = generate_editor(doc)

    candidates = []
    for seg in doc.get("segments", []):
        candidates.extend(seg.get("candidates", []))

    doc_parent = doc_path.parent.resolve()
    previews_to_copy: list[tuple[Path, str]] = []

    for cand in candidates:
        preview = cand.get("preview")
        if not isinstance(preview, str) or not _PREVIEW_FILENAME_PATTERN.fullmatch(preview):
            raise ValueError(f"Candidate preview filename is invalid: {preview!r}")

        preview_path = doc_path.parent / preview
        if preview_path.is_symlink():
            raise ValueError(f"Candidate preview cannot be a symlink: {preview_path}")

        if not preview_path.is_file() or preview_path.stat().st_size == 0:
            raise ValueError(
                f"Candidate preview file must exist and be non-empty: {preview_path}"
            )

        if preview_path.resolve().parent != doc_parent:
            raise ValueError(
                f"Candidate preview resolved parent must match document parent: {preview_path}"
            )

        previews_to_copy.append((preview_path, preview))

    out_parent = out_dest.parent if str(out_dest.parent) else Path(".")
    out_parent.mkdir(parents=True, exist_ok=True)

    tmp_dir: Path | None = None
    try:
        # 在输出目录同级创建临时目录以保证同文件系统原子 rename
        tmp_dir = Path(tempfile.mkdtemp(prefix=".tmp_", dir=out_parent))

        copied_set: set[str] = set()
        for src_file, filename in previews_to_copy:
            if filename not in copied_set:
                shutil.copy2(src_file, tmp_dir / filename)
                copied_set.add(filename)

        (tmp_dir / "candidates.json").write_bytes(raw_bytes)
        (tmp_dir / "editor.html").write_text(editor_html, encoding="utf-8")

        tmp_dir.rename(out_dest)
        tmp_dir = None
    finally:
        if tmp_dir is not None and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return str(out_dest)
