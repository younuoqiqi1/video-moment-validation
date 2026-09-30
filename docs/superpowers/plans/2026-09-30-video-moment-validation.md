# Video Moment Validation Implementation Plan

> 2026-09-30 本地执行修订：以 `LOCAL_START.md` 和 `docs/superpowers/plans/2026-09-30-local-execution.md` 为准。执行位置改为用户 Mac；先执行本地环境阶段（下方 Task 1），随后实现并验证本地 AGY 续跑。旧 Task 0 的 GPT 计划任务创建步骤暂缓，尚未证明可用。旧云端 CPU、内存、磁盘和工具版本仅为历史环境信息，不能用于宣称 Mac 已通过检查。关键词评分仅为基线；GPT 通过导出/导入文件参与描述与语义排序，不存在已接通的 GPT API。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible, stage-by-stage validation pipeline that turns one confirmed Chinese voice-over script and 20–30 minutes of source video into ranked candidate clips, a reviewed production order, and a subtitled MP4.

**Architecture:** A Python command-line pipeline writes versioned JSON manifests and self-contained HTML review artifacts for every stage. FFmpeg handles all media probing, shot detection, cutting, and rendering; retrieval combines subtitle text, optional imported frame captions, and deterministic scoring. Alibaba Cloud TTS is isolated behind an adapter so every earlier stage works before credentials are available.

**Tech Stack:** Python 3.12, standard library, pytest, FFmpeg/ffprobe 6.1, self-contained HTML/JavaScript, Alibaba Cloud TTS adapter, Antigravity CLI 1.2.13.

**Spec:** `docs/superpowers/specs/2026-09-29-video-moment-validation-design.md`

## Global Constraints

- Use one work only, with 20–30 minutes of source video and one human-confirmed voice-over script.
- Return at most three candidate clips per script segment.
- Keep all source video, credentials, intermediate media, and rendered MP4 files out of Git.
- Every stage must produce an artifact the user can open before the next stage begins.
- Target a final video no longer than three minutes.
- Record all candidate selections, rejections, timecode edits, script edits, elapsed time, and external service cost.
- Run on CPU with 9.7 GiB RAM and 30 GiB available disk; GPU-only dependencies are not allowed.
- Treat the hook script copied from Notion as provisional until its plot claims are confirmed against the supplied source range.

## Review Focus

- Missing or unsupported video must stop with a Chinese error and must not create a misleading success manifest.
- Videos without embedded or sidecar subtitles must be marked `subtitle_missing`; retrieval must not silently treat them as indexed.
- A script segment with no credible candidates must return an empty list and `needs_manual_material`, rather than a low-quality forced match.
- Timecode edits outside source duration or with `out <= in` must be rejected before production-order export.
- TTS or FFmpeg failure must preserve previous stage outputs and record a readable failure reason.
- A quota retry must resume from the last committed task and must not retry ordinary test, permission, authentication, or coding errors forever.

---

### Task 0: Resumable Antigravity and GPT orchestration

**Files:**
- Create: `automation/tasks.json`
- Create: `automation/run-state.json`
- Create: `tools/agy_runner.py`
- Create: `tests/test_agy_runner.py`
- Create: `docs/automatic-resume.md`
- Modify: `PROGRESS.md`

**Interfaces:**
- Produces: `python tools/agy_runner.py run-next --plan docs/superpowers/plans/2026-09-30-video-moment-validation.md --state automation/run-state.json`.
- Produces: `RunState(current_task: str, status: str, conversation_id: str | None, last_commit: str, resume_after: str | None, error: str | None)`.
- Produces statuses: `ready`, `running`, `waiting_antigravity_quota`, `waiting_gpt_quota`, `blocked`, and `complete`.

- [ ] **Step 1: Write failing state, checkpoint, and error-classification tests**

Cover successful task completion, quota error with a supplied reset timestamp, quota error without a timestamp, authentication failure, permission failure, test failure, process interruption, and restart from an existing `conversation_id`.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest tests/test_agy_runner.py -v`

- [ ] **Step 3: Implement one-task-at-a-time Antigravity execution**

Invoke `agy` with `--output-format stream-json`, record the `conversation_id`, stream logs to `outputs/automation/`, use `--conversation <id>` for continuation, and require a successful Git commit before advancing the task pointer. Use scoped Antigravity permissions for Git, Python, pytest, FFmpeg, and ffprobe commands.

- [ ] **Step 4: Implement quota waiting without indefinite error retries**

When the terminal result is an Antigravity quota error, use the reset timestamp when present; otherwise set the first retry to five hours plus five minutes after failure. A later quota error retries hourly. Every other failure sets `blocked` and requires review.

- [ ] **Step 5: Configure GPT/Codex continuation after GitHub is connected**

Create one hourly ChatGPT condition task that reads the Notion progress page and GitHub `automation/run-state.json`. It acts only when status is `waiting_gpt_quota`, continues the first unchecked implementation step, pushes a checkpoint commit, updates Notion, and otherwise produces no notification. The schedule uses `FREQ=HOURLY`, the highest supported automation frequency.

- [ ] **Step 6: Run tests, update the board, and commit**

```bash
python -m pytest tests/test_agy_runner.py -v
git add automation tools tests docs/automatic-resume.md PROGRESS.md
git commit -m "feat: add quota-aware coding resume"
```

### Task 1: Stage runner and environment report

**Files:**
- Create: `pyproject.toml`
- Create: `src/vmv/__init__.py`
- Create: `src/vmv/cli.py`
- Create: `src/vmv/stages.py`
- Create: `src/vmv/report.py`
- Create: `tests/test_cli.py`
- Modify: `README.md`
- Modify: `PROGRESS.md`

**Interfaces:**
- Produces: `python -m vmv status --output outputs/stage0/environment.json`
- Produces: `StageResult(stage: str, status: str, artifacts: list[str], errors: list[str])`

- [ ] **Step 1: Write failing tests for environment detection and missing FFmpeg reporting**

Assert that the status command records Python, FFmpeg, ffprobe, Git, and Antigravity versions; a missing required executable returns a failed `StageResult` with a Chinese error.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest tests/test_cli.py -v`

- [ ] **Step 3: Implement the CLI, stage result model, and JSON/HTML status report**

Keep process execution in one helper and write artifacts atomically.

- [ ] **Step 4: Run tests and the real environment probe**

Run: `python -m pytest tests/test_cli.py -v && python -m vmv status --output outputs/stage0/environment.json`

- [ ] **Step 5: Update the board and commit**

```bash
git add pyproject.toml src tests README.md PROGRESS.md
git commit -m "feat: add staged validation runner"
```

### Task 2: Media ingest and shot manifest

**Files:**
- Create: `src/vmv/media.py`
- Create: `src/vmv/ffmpeg.py`
- Create: `src/vmv/subtitles.py`
- Create: `src/vmv/templates/stage1.html`
- Create: `tests/test_media.py`
- Create: `tests/fixtures/generate_fixture.py`
- Modify: `src/vmv/cli.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: `StageResult` from Task 1.
- Produces: `probe_media(path: Path) -> MediaInfo`
- Produces: `detect_shots(path: Path, threshold: float = 0.32) -> list[Shot]`
- Produces: `ingest_media(video: Path, subtitle: Path | None, output_dir: Path) -> IngestManifest`
- Produces: `outputs/stage1/manifest.json`, contact sheet, and `outputs/stage1/index.html`.

- [ ] **Step 1: Generate a deterministic synthetic fixture and write failing ingest tests**

Cover valid 16:9 video, missing input, malformed subtitle, video without subtitles, ordered shot boundaries, and source-duration bounds.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest tests/test_media.py -v`

- [ ] **Step 3: Implement ffprobe metadata, FFmpeg scene detection, keyframes, subtitle parsing, and manifest generation**

Prefer embedded or supplied SRT/ASS subtitles. Mark missing subtitles explicitly; do not add ASR until the actual source proves it is needed.

- [ ] **Step 4: Run tests and inspect the generated Stage 1 HTML**

Run: `python -m pytest tests/test_media.py -v && python -m vmv ingest tests/fixtures/sample.mp4 --output outputs/stage1`

- [ ] **Step 5: Update the board and commit**

```bash
git add src tests PROGRESS.md
git commit -m "feat: ingest media into shot manifest"
```

### Task 3: Confirmed script import and visual requirements

**Files:**
- Create: `src/vmv/script.py`
- Create: `schemas/script.schema.json`
- Create: `configs/potential-hook-script.example.json`
- Create: `src/vmv/templates/stage2.html`
- Create: `tests/test_script.py`
- Modify: `src/vmv/cli.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Produces: `load_script(path: Path) -> ScriptDocument`
- Produces: `build_visual_queries(script: ScriptDocument) -> list[VisualRequirement]`
- Produces: `outputs/stage2/requirements.json` and `outputs/stage2/index.html`.

- [ ] **Step 1: Write failing schema and segmentation tests**

Assert stable segment IDs, exact retention of source text, explicit `fact_check_status`, ordered time ranges, target duration, people, scenes, actions, emotions, and forbidden revelations.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest tests/test_script.py -v`

- [ ] **Step 3: Implement JSON script import and deterministic visual-query generation**

The provisional Notion script stays an example until the user marks each plot claim confirmed or revises it.

- [ ] **Step 4: Run tests and inspect the Stage 2 HTML**

Run: `python -m pytest tests/test_script.py -v && python -m vmv prepare-script configs/potential-hook-script.example.json --output outputs/stage2`

- [ ] **Step 5: Update the board and commit**

```bash
git add src schemas configs tests PROGRESS.md
git commit -m "feat: prepare script visual requirements"
```

### Task 4: Caption import and candidate retrieval

**Files:**
- Create: `src/vmv/captions.py`
- Create: `src/vmv/retrieval.py`
- Create: `src/vmv/scoring.py`
- Create: `schemas/captions.schema.json`
- Create: `schemas/candidates.schema.json`
- Create: `tests/test_retrieval.py`
- Modify: `src/vmv/cli.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: `IngestManifest`, `VisualRequirement`, optional frame-caption JSON.
- Produces: `rank_candidates(requirement: VisualRequirement, shots: list[Shot], captions: CaptionIndex | None, limit: int = 3) -> CandidateSet`
- Produces: `outputs/stage3/candidates.json` and extracted preview MP4 files.

- [ ] **Step 1: Write failing ranking tests with a labeled miniature corpus**

Cover subtitle match, person/scene caption match, chronological context, duplicate suppression, maximum three results, no-match behavior, and candidates that cross source duration.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest tests/test_retrieval.py -v`

- [ ] **Step 3: Implement CPU-safe deterministic retrieval and caption import**

Use normalized Chinese character n-grams, token overlap, subtitle-window context, explicit people/scene/action matches, and score explanations. Generate contact-sheet prompt packets for optional Antigravity-assisted frame captions; import only schema-valid JSON. Do not require a local vision model for the first run.

- [ ] **Step 4: Run tests and generate preview clips from the synthetic fixture**

Run: `python -m pytest tests/test_retrieval.py -v && python -m vmv retrieve --manifest outputs/stage1/manifest.json --requirements outputs/stage2/requirements.json --output outputs/stage3`

- [ ] **Step 5: Update the board and commit**

```bash
git add src schemas tests PROGRESS.md
git commit -m "feat: rank and preview candidate clips"
```

### Task 5: Self-contained human review artifact

**Files:**
- Create: `src/vmv/review.py`
- Create: `src/vmv/templates/stage3-review.html`
- Create: `tests/test_review.py`
- Modify: `src/vmv/cli.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: `outputs/stage3/candidates.json` and preview MP4 files.
- Produces: self-contained review page with adopt/reject/no-match controls and an `Export review.json` button.
- Produces: `validate_review(review: ReviewDocument, candidates: CandidateDocument) -> list[ValidationError]`.

- [ ] **Step 1: Write failing tests for review export and timecode validation**

Cover one decision per segment, no-match selection, edited timecodes, out-of-range edits, `out <= in`, and preservation of original candidate IDs.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest tests/test_review.py -v`

- [ ] **Step 3: Implement the static review page and review JSON validator**

The page must work from a local file without a server and show script text, match reason, score components, timecodes, and playable previews.

- [ ] **Step 4: Run tests and open the generated review artifact**

Run: `python -m pytest tests/test_review.py -v && python -m vmv build-review --candidates outputs/stage3/candidates.json --output outputs/stage3/review.html`

- [ ] **Step 5: Update the board and commit**

```bash
git add src tests PROGRESS.md
git commit -m "feat: add candidate review artifact"
```

### Task 6: Production order, TTS adapter, and MP4 renderer

**Files:**
- Create: `src/vmv/production.py`
- Create: `src/vmv/tts.py`
- Create: `src/vmv/render.py`
- Create: `schemas/production-order.schema.json`
- Create: `tests/test_production.py`
- Create: `tests/test_render.py`
- Modify: `.env.example`
- Modify: `src/vmv/cli.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: confirmed script, validated `review.json`, media manifest, and `TTSProvider`.
- Produces: `build_production_order(script: ScriptDocument, review: ReviewDocument, media: IngestManifest, audio: dict[str, AudioResult]) -> ProductionOrder`.
- Produces: `TTSProvider.synthesize(text: str, output: Path) -> AudioResult`.
- Produces: `render(order: ProductionOrder, output: Path) -> RenderResult`.
- Produces: `outputs/stage4/production-order.json` and `outputs/stage5/sample.mp4`.

- [ ] **Step 1: Write failing production-order and renderer tests**

Use a fake TTS provider to test audio-duration driven timing, multiple shots per narration segment, insufficient material, subtitle timing, invalid review input, TTS failure, and FFmpeg failure.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest tests/test_production.py tests/test_render.py -v`

- [ ] **Step 3: Implement production order and fake TTS rendering path**

Do not implement the real Alibaba adapter until the user supplies the exact product/model documentation and environment-variable names.

- [ ] **Step 4: Implement the Alibaba adapter from supplied documentation, then render the approved sample**

Run: `python -m vmv build-order --script outputs/stage2/script.json --review outputs/stage3/review.json --media outputs/stage1/manifest.json --output outputs/stage4/production-order.json` followed by `python -m vmv render --order outputs/stage4/production-order.json --output outputs/stage5/sample.mp4`; credentials must stay in `.env` or the process environment.

- [ ] **Step 5: Verify the MP4 and commit**

Run: `python -m pytest -v` and use ffprobe to assert H.264/AAC, 1920×1080, valid duration, and no zero-length streams.

```bash
git add src schemas tests .env.example PROGRESS.md
git commit -m "feat: generate production order and sample video"
```

### Task 7: Validation metrics and decision report

**Files:**
- Create: `src/vmv/metrics.py`
- Create: `src/vmv/templates/final-report.html`
- Create: `tests/test_metrics.py`
- Create: `docs/validation-report-template.md`
- Modify: `src/vmv/cli.py`
- Modify: `PROGRESS.md`

**Interfaces:**
- Consumes: requirements, candidates, review decisions, production order, timing log, and cost log.
- Produces: `calculate_metrics(inputs: ValidationInputs) -> ValidationMetrics`.
- Produces: `outputs/stage6/report.json`, `outputs/stage6/report.html`, and completed Markdown conclusion.

- [ ] **Step 1: Write failing metric tests**

Assert candidate usable rate, material coverage, replacement count, timecode edit count, script edit count, manual minutes, per-stage elapsed time, external cost, and pass/fail against the 80% threshold.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest tests/test_metrics.py -v`

- [ ] **Step 3: Implement metrics and report generation**

Separate observed results from interpretation and list every no-match reason.

- [ ] **Step 4: Run the full verification suite and generate the final report**

Run: `python -m pytest -v && python -m vmv report --run outputs --output outputs/stage6`

- [ ] **Step 5: Update the final board and commit**

```bash
git add src tests docs PROGRESS.md
git commit -m "feat: report video retrieval validation results"
```
