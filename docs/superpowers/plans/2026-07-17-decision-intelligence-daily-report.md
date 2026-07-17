# 决策与情报全览日报 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为归档中文日报提供决策简报、情报全览和 MiniMax `speech-2.8-hd` MP3。

**Architecture:** 决策稿由固定日报快照和人工审核确定性拼接；情报全览重建日报绑定操作快照的可展示事件。音频通过现有 durable Worker 生成，保存为受控本地成品并记录脱敏状态。

**Tech Stack:** Python、FastAPI/Jinja、SQLAlchemy/Alembic、HTTPX、pytest、ruff。

## Global Constraints

- 不读取、输出或提交 `.env`；仅服务端以 `SecretStr` 使用 `MINIMAX_TTS_API_KEY`。
- 固定模型 `speech-2.8-hd`，MP3/32kHz/128kbps/单声道；MiniMax 不改变事实或审核结论。
- 音频操作具备超时、有限重试、取消、心跳、结构化脱敏日志和中文诊断。
- 根目录的 reports 绝不修改、暂存或提交。

---

### Task 1: 音频成品持久化

**Files:**
- Modify: `src/newsradar/settings.py`, `src/newsradar/db/models.py`
- Create: `src/newsradar/daily_reports/audio_schema.py`, `migrations/versions/20260717_0026_daily_report_audio_artifacts.py`
- Test: `tests/daily_reports/test_audio_schema.py`, `tests/test_migrations.py`

**Interfaces:** `DailyReportAudioRequest.create(report_id, rendition)` 返回固定 `speech-2.8-hd` 请求；`DailyReportAudioArtifactRecord` 保存脚本哈希、状态和相对音频路径。

- [ ] Write `test_decision_audio_request_uses_speech_2_8_hd`, asserting `DailyReportAudioRequest.create(report_id=12, rendition="decision").model == "speech-2.8-hd"`.
- [ ] Run `python -m pytest tests/daily_reports/test_audio_schema.py -q`; it must fail because the request does not exist.
- [ ] Add the append-only artifact record: report FK, rendition, status, script, SHA-256, model, voice settings, operation id, trace id, duration, size, relative path, file SHA-256, error code/message and timestamps. Add checks for `decision|overview` and the four lifecycle states.
- [ ] Add `Settings.minimax_tts_api_key: SecretStr | None`; never include its value in models, logs or views.
- [ ] Run `python -m pytest tests/daily_reports/test_audio_schema.py tests/test_migrations.py -q` and commit `feat: add daily report audio artifacts`.

### Task 2: 决策稿与全览投影

**Files:**
- Create: `src/newsradar/daily_reports/intelligence.py`
- Modify: `src/newsradar/web/daily_report_queries.py`
- Test: `tests/daily_reports/test_intelligence.py`, `tests/web/test_daily_report_pages.py`

**Interfaces:** `build_decision_script(report, items) -> str` 和 `DailyReportIntelligenceView`；输入是固定日报项、审核记录及 report 的 operation snapshot。

- [ ] Write a failing test that `build_decision_script` does not contain a duplicate/excluded title and does contain the `needs_evidence` warning.
- [ ] Write a failing test that overview returns every confirmed/hotspot/signal event from the report's bound operation snapshot, rather than current mutable event state.
- [ ] Run `python -m pytest tests/daily_reports/test_intelligence.py -q` and observe both failures.
- [ ] Compose decision text only from included snapshots and latest review fields. Reconstruct overview from the report operation snapshot, group by category/status and expose evidence/limitations without changing persisted event state.
- [ ] Run `python -m pytest tests/daily_reports/test_intelligence.py tests/web/test_daily_report_pages.py -q` and commit `feat: project decision and intelligence daily reports`.

### Task 3: MiniMax HD Worker 操作

**Files:**
- Create: `src/newsradar/daily_reports/audio_client.py`, `src/newsradar/daily_reports/audio_runtime.py`
- Modify: `src/newsradar/operations/schema.py`, `src/newsradar/operations/commands.py`, `src/newsradar/cli.py`
- Test: `tests/daily_reports/test_audio_client.py`, `tests/daily_reports/test_audio_runtime.py`, `tests/operations/test_commands.py`

**Interfaces:** `MiniMaxSpeechClient.synthesize(script)` 和 `DailyReportAudioHandler`；新增 `OperationType.DAILY_REPORT_AUDIO`。

- [ ] Write a failing test that the client submits `speech-2.8-hd`, decodes a valid hex MP3, and never stores the authorization value.
- [ ] Write failing tests mapping 401/403 to non-retryable authentication/permission diagnostics, 429/5xx/timeouts to retryable diagnostics, malformed hex to non-retryable parsing diagnostics, and cancellation to no saved file.
- [ ] Run `python -m pytest tests/daily_reports/test_audio_client.py tests/daily_reports/test_audio_runtime.py -q` and observe failures.
- [ ] POST to `/v1/t2a_v2` with server-only Bearer authorization, HD configuration, bounded HTTPX timeout, and Chinese language boost. Atomically save a validated MP3 under `.local/daily-report-audio/<report-id>/`, hash it, checkpoint around I/O, persist only sanitized diagnostics, and use the existing operation retry policy.
- [ ] Register the handler in `cli.py`; run `python -m pytest tests/daily_reports/test_audio_client.py tests/daily_reports/test_audio_runtime.py tests/operations/test_commands.py -q`; commit `feat: generate daily report audio with minimax hd`.

### Task 4: 阅读页面与安全音频端点

**Files:**
- Modify: `src/newsradar/web/app.py`, `src/newsradar/web/daily_report_queries.py`, `src/newsradar/web/templates/daily_report_detail.html`, `src/newsradar/web/static/site.css`
- Test: `tests/web/test_daily_report_pages.py`

**Interfaces:** 归档日报可 POST 入队 `decision|overview` 音频；GET 音频只允许服务端记录的相对路径。

- [ ] Write failing page tests expecting “今日决策简报”, “情报全览”, and “生成决策版语音” on archived reports.
- [ ] Write a failing test that draft reports return 409 for audio enqueue and a traversal-like artifact request returns 404.
- [ ] Run `python -m pytest tests/web/test_daily_report_pages.py -q` and observe failure.
- [ ] Show decision first, a collapsible overview, read-only source-health counts, player/status/retry action and Chinese diagnostic. Preserve editorial behavior and action-token protection.
- [ ] Run `python -m pytest tests/web/test_daily_report_pages.py -q` and commit `feat: show decision intelligence reports and audio`.

### Task 5: 验收与文档

**Files:**
- Modify: `.env.example`, `README.md`
- Create: `tests/acceptance/test_daily_report_decision_audio.py`

- [ ] Write a failing end-to-end test asserting an archived artifact script hash equals the deterministic audited script hash and excludes excluded titles.
- [ ] Run `python -m pytest tests/acceptance/test_daily_report_decision_audio.py -q` and observe failure.
- [ ] Add only the name `MINIMAX_TTS_API_KEY` to `.env.example`; document server-only Token Plan use and user-triggered real generation.
- [ ] Run `python -m pytest -q` and `python -m ruff check src tests`.
- [ ] Run migration, open archived report #1, verify decision/overview rendering, then generate one real `speech-2.8-hd` MP3 only after detecting configuration without displaying the secret. Confirm browser playback and Chinese diagnostics.
