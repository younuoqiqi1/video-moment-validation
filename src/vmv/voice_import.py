import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Any, Dict, Mapping, Union

from vmv.generation_process import run_generation

ALLOWED_EXTS = {".wav", ".aiff", ".aif", ".mp3"}
ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
CANONICAL_ORDER_KEYS = (
    "state",
    "sample",
    "media_id",
    "source_sha256",
    "document_sha256",
    "source_path",
    "timing_basis",
    "duration_sec",
    "segments",
)
CANONICAL_SHOT_KEYS = (
    "shot_id",
    "source_in_sec",
    "source_out_sec",
    "timeline_in_sec",
    "timeline_out_sec",
)


def import_audio(
    order_path: Union[str, Path],
    sources: Mapping[str, Union[str, Path]],
    outdir: Union[str, Path],
    ffprobe: str = "ffprobe",
) -> Dict[str, Any]:
    deadline = time.monotonic() + 60.0

    def check_timeout() -> float:
        rem = deadline - time.monotonic()
        if rem <= 0:
            raise TimeoutError("Global 60-second deadline exceeded during audio import")
        return rem

    try:
        outdir = Path(outdir)
        if outdir.exists() or outdir.is_symlink():
            raise FileExistsError(f"Output directory or link already exists: {outdir}")

        order_file = Path(order_path)
        if order_file.is_symlink():
            raise OSError(f"Order file cannot be a symlink: {order_file}")
        if not order_file.is_file():
            raise OSError(f"Order file does not exist: {order_file}")

        check_timeout()
        with open(order_file, "rb") as f:
            order_bytes = f.read()
        order_sha256 = hashlib.sha256(order_bytes).hexdigest()
        order = json.loads(order_bytes.decode("utf-8"))

        if not isinstance(order, dict):
            raise ValueError("Order must be a JSON object")
        for k in CANONICAL_ORDER_KEYS:
            if k not in order:
                raise ValueError(f"Missing canonical order field: {k}")

        if order["state"] != "ready_for_tts":
            raise ValueError(f"Expected state 'ready_for_tts', got {order['state']!r}")
        if type(order["sample"]) is not bool:
            raise ValueError("Order sample field must be an exact bool")

        segments = order["segments"]
        if not isinstance(segments, list) or len(segments) == 0:
            raise ValueError("Segments must be a non-empty list")

        seg_ids = []
        for seg in segments:
            if not isinstance(seg, dict):
                raise ValueError("Segment must be a dict")
            for sk in ("id", "narration", "shots"):
                if sk not in seg:
                    raise ValueError(f"Missing canonical segment field: {sk}")

            sid = seg["id"]
            if not isinstance(sid, str) or not ID_PATTERN.fullmatch(sid):
                raise ValueError(f"Segment ID must match ^[a-zA-Z0-9_-]+$: {sid!r}")
            if sid in seg_ids:
                raise ValueError(f"Duplicate segment ID found: {sid!r}")
            seg_ids.append(sid)

            narration = seg["narration"]
            if not isinstance(narration, str) or not narration.strip():
                raise ValueError(f"Segment {sid} narration must be non-blank")

            shots = seg["shots"]
            if not isinstance(shots, list) or len(shots) == 0:
                raise ValueError(f"Segment {sid} shots must be a non-empty list")
            for shot in shots:
                if not isinstance(shot, dict):
                    raise ValueError("Shot must be a dict")
                for k in CANONICAL_SHOT_KEYS:
                    if k not in shot:
                        raise ValueError(f"Missing canonical shot field: {k}")

        if set(sources.keys()) != set(seg_ids):
            raise ValueError("Source mappings keys must exactly match order segment IDs")

        for sid in seg_ids:
            p = Path(sources[sid])
            if p.is_symlink():
                raise OSError(f"Source audio file cannot be a symlink: {p}")
            if not p.is_file():
                raise OSError(f"Source audio file does not exist: {p}")
            if p.suffix.lower() not in ALLOWED_EXTS:
                raise ValueError(f"Source file {p} extension not allowed (WAV/AIFF/AIF/MP3)")
            if p.stat().st_size == 0:
                raise ValueError(f"Source audio file is empty: {p}")

        outdir.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=".tmp_voice_import_", dir=outdir.parent))
        committed = False

        try:
            manifest_segments = []
            for idx, seg in enumerate(segments):
                sid = seg["id"]
                src_path = Path(sources[sid])
                canon_name = f"voice-{idx:03d}{src_path.suffix.lower()}"
                dst_path = temp_dir / canon_name

                hasher = hashlib.sha256()
                bytes_copied = 0
                with open(src_path, "rb") as fsrc, open(dst_path, "wb") as fdst:
                    while True:
                        check_timeout()
                        chunk = fsrc.read(1024 * 1024)
                        if not chunk:
                            break
                        hasher.update(chunk)
                        fdst.write(chunk)
                        bytes_copied += len(chunk)

                if bytes_copied == 0:
                    raise ValueError(f"Copied audio snapshot is empty: {dst_path}")
                snapshot_sha = hasher.hexdigest()

                rem = check_timeout()
                cmd = [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(dst_path),
                ]
                try:
                    res = run_generation(cmd, timeout=rem)
                    stdout_str = getattr(res, "stdout", res)
                    probe_data = json.loads(stdout_str)
                except Exception as exc:
                    raise ValueError(f"ffprobe failure on {canon_name}: {exc}") from exc

                streams = probe_data.get("streams", [])
                audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
                if not audio_streams:
                    raise ValueError(f"No audio stream found in snapshot: {canon_name}")

                fmt = probe_data.get("format", {})
                dur_val = audio_streams[0].get("duration") or fmt.get("duration")
                try:
                    dur_sec = float(dur_val)
                    if not math.isfinite(dur_sec) or dur_sec <= 0:
                        raise ValueError(f"Non-positive or non-finite duration: {dur_sec}")
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"ffprobe invalid duration for {canon_name}: {exc}") from exc

                narr_hash = hashlib.sha256(seg["narration"].encode("utf-8")).hexdigest()
                manifest_segments.append(
                    {
                        "id": sid,
                        "narration_sha256": narr_hash,
                        "path": canon_name,
                        "sha256": snapshot_sha,
                        "duration_sec": dur_sec,
                    }
                )

            manifest = {
                "sample": order["sample"],
                "provider": "local_import",
                "order_sha256": order_sha256,
                "segments": manifest_segments,
            }

            with open(temp_dir / "audio_manifest.json", "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)

            if outdir.exists() or outdir.is_symlink():
                raise FileExistsError(f"Destination outdir appeared before atomic rename: {outdir}")

            temp_dir.rename(outdir)
            committed = True
            return manifest

        finally:
            if not committed and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    except (KeyError, TypeError, json.JSONDecodeError) as err:
        raise ValueError(f"Order or mapping validation failed: {err}") from err
