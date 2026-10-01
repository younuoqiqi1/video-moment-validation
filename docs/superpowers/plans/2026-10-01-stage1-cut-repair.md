# Stage 1 Cut Repair Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. User explicitly selected Codex implementation; proceed without another authorization question.

**Goal:** Recover low-contrast hard-cut candidates and provide a reproducible, private Mac comparison.

**Architecture:** Collect original-frame FFmpeg scene scores and YDIF. Keep the fixed detector as baseline; add local relative peaks with a minimum score and single-frame pulse suppression. Bind comparisons to existing input hashes and export only safe numbers.

**Tech Stack:** Python 3.12 standard library, FFmpeg, pytest, existing GitHub self-hosted Mac runner.

**Spec:** `tasks/stage1-media-import.md`, `tasks/stage1-cut-recheck.md`; current PR #5 R4 findings.

## Global Constraints

- Only stage 1; no merge, automatic acceptance or next stage.
- No media, paths, secrets or raw logs committed/uploaded; retain original outputs.

## Review Focus

Low contrast, continuous motion, pulse lighting, input hash drift, reused output directory. Each has a synthetic or safety test. Real film quality remains a Mac visual check.

### Task 1: Detector and comparison

Files: `src/vmv/scene_detection.py`, `media.py`, `cli.py`, `cut_comparison.py`; tests `test_adaptive_cuts.py`, `test_cut_comparison.py`.

- [x] Reproduce 0.12-score cut missed by 0.35 and observe failing regression tests.
- [x] Implement adaptive candidates, original fixed mode, parameter validation and metadata.
- [x] Implement ±1-frame one-to-one comparison, source hashes and fresh outputs; verify full pipeline on synthetic video.
- [x] Run `python -m pytest -q`: 54 pass.

### Task 2: Fixed Mac execution and visual review

Files on dispatch branch: `scripts/mac_actions.py`, `.github/workflows/mac-local.yml`, fixed dispatch JSON, `tests/test_cut_dispatch.py`.

- [x] Observe failing dispatch/routing/disclosure tests before implementation.
- [x] Add one pinned SHA mode for PR #5 and sanitized result fields; preserve output on configured local project.
- [x] Run dispatch tests: 14 pass, including existing runner tests.
- [ ] Pin committed code SHA and dispatch; verify real Mac result.
- [ ] AGY visual review of reference and changed boundaries; user stage acceptance remains separate.
