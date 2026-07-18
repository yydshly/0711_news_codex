# Daily Autopilot Content Wave Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a new automatic daily report run execute the existing high-value content wave, bind the report to that exact event snapshot, and publish both audio renditions only after complete validation.

**Architecture:** Keep source catalog refresh as a separate control-plane feature. Freeze a secret-free `WavePlan` when the web action creates the parent run, queue one `high_value_news_wave` child through the existing Worker, and store that child in `event_operation_id`. Reuse the child event manifest for exact report generation, deterministic Chinese review, no-content handling, and atomic dual-audio enqueue.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL/SQLite tests, Pydantic, Typer Worker, pytest, Ruff.

## Global Constraints

- Work only in `codex/daily-autopilot-content-wave`; do not merge or push without user confirmation.
- Do not read or expose `.env` values; persist only configured credential names already reduced to fetchable booleans in the frozen plan.
- Do not touch, stage, or commit user-owned files under `reports/`.
- Reuse existing fetchers, `HighValueWaveHandler`, `EventPipeline`, report repositories, Worker retry/cancel/heartbeat behavior, and MiniMax TTS.
- Keep legacy automatic-run stages readable for runs #1 and #2; new runs start at `enqueue_content_wave`.
- Do not add a database migration: reuse `event_operation_id` for the content wave and express no-content as succeeded/completed plus `result_summary.outcome`.
- Every production behavior change begins with a failing test and ends with a focused commit.

---

### Task 1: Freeze a High-Value Wave in New Automatic Runs

**Files:**
- Modify: `src/newsradar/waves/planning.py`
- Modify: `src/newsradar/daily_reports/autopilot.py`
- Modify: `src/newsradar/daily_reports/autopilot_repository.py`
- Modify: `src/newsradar/operations/commands.py`
- Modify: `src/newsradar/web/app.py`
- Test: `tests/daily_reports/test_autopilot.py`
- Test: `tests/daily_reports/test_autopilot_repository.py`
- Test: `tests/operations/test_commands.py`
- Test: `tests/web/test_daily_autopilot_pages.py`

**Interfaces:**
- Produces `wave_plan_from_members(*, profile_id: str, members: tuple[WaveMemberSnapshot, ...], window_hours: int, trend_days: int) -> WavePlan` as the single canonical digest boundary used by both catalog planning and durable deserialization.
- Produces `serialize_wave_plan(plan: WavePlan) -> dict[str, object]`.
- Produces `deserialize_wave_plan(value: object) -> WavePlan` with digest verification.
- Changes `OperationCommandService.enqueue_daily_autopilot(*, plan: WavePlan, trigger: str) -> int`; the window comes from `plan.window_hours`.
- Changes `_high_value_wave_plan(session, window_hours: int | None = None) -> WavePlan`.

- [ ] **Step 1: Write failing serialization and digest tests**

Add tests that round-trip a real `WavePlan`, assert the serialized payload contains no credential keys or values, and reject a modified member or digest:

```python
def test_wave_plan_round_trip_is_secret_free() -> None:
    plan = wave_plan_from_members(
        profile_id="daily",
        members=(WaveMemberSnapshot("source-a", "provider-a", "hash", ("evidence",), "ready", "rss", True, None),),
        window_hours=48,
        trend_days=7,
    )
    payload = serialize_wave_plan(plan)
    restored = deserialize_wave_plan(payload)
    assert restored == plan
    assert "credential" not in repr(payload).lower()

def test_wave_plan_rejects_tampered_digest() -> None:
    payload = serialize_wave_plan(_wave_plan())
    payload["members"][0]["fetchable"] = False
    with pytest.raises(ValueError, match="invalid_daily_autopilot_wave_plan"):
        deserialize_wave_plan(payload)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `uv run --extra dev pytest tests/daily_reports/test_autopilot.py -q`

Expected: import or attribute failure because wave-plan serialization does not exist.

- [ ] **Step 3: Implement canonical planning and strict wave-plan serialization**

Extract the existing digest construction into `wave_plan_from_members`, keep `build_wave_plan` on that same boundary, serialize every `WaveMemberSnapshot` field, and reconstruct through the helper before comparing the stored digest. Do not serialize settings, environment names, probe bodies, or tokens.

- [ ] **Step 4: Write failing new-run and web-window tests**

Add assertions that a newly queued run starts at `enqueue_content_wave`, stores `wave_plan`, does not store `catalog_plan`, and that submitting `window_hours=72` builds a WavePlan whose `window_hours` is 72:

```python
assert run.stage == DailyAutopilotStage.ENQUEUE_CONTENT_WAVE.value
assert run.window_hours == 72
assert deserialize_wave_plan(run.requested_scope["wave_plan"]).window_hours == 72
assert "catalog_plan" not in run.requested_scope
```

- [ ] **Step 5: Run the focused tests and verify RED**

Run: `uv run --extra dev pytest tests/daily_reports/test_autopilot_repository.py tests/operations/test_commands.py tests/web/test_daily_autopilot_pages.py -q`

Expected: the run still starts at `enqueue_source_refresh` and the command still requires a catalog plan.

- [ ] **Step 6: Implement the new enqueue boundary**

Add `ENQUEUE_CONTENT_WAVE` and `WAIT_CONTENT_WAVE` to the enum. Change `create_run` to start new rows at `ENQUEUE_CONTENT_WAVE`. Make the command persist `serialize_wave_plan(plan)` and `plan.window_hours`. In the web route, validate 24/48/72, copy the loaded profile with the selected window, call `_high_value_wave_plan(session, window_hours)`, then enqueue the parent.

- [ ] **Step 7: Verify Task 1 and commit**

Run:

```powershell
uv run --extra dev pytest tests/daily_reports/test_autopilot.py tests/daily_reports/test_autopilot_repository.py tests/operations/test_commands.py tests/web/test_daily_autopilot_pages.py -q
uv run --extra dev ruff check src/newsradar/waves/planning.py src/newsradar/daily_reports/autopilot.py src/newsradar/daily_reports/autopilot_repository.py src/newsradar/operations/commands.py src/newsradar/web/app.py tests/daily_reports/test_autopilot.py tests/daily_reports/test_autopilot_repository.py tests/operations/test_commands.py tests/web/test_daily_autopilot_pages.py
git diff --check
```

Commit: `feat: freeze content wave for daily autopilot`

---

### Task 2: Run the Existing Content Wave and Handle Its Terminal Manifest

**Files:**
- Modify: `src/newsradar/daily_reports/autopilot_runtime.py`
- Modify: `src/newsradar/web/templates/daily_autopilot_detail.html`
- Test: `tests/daily_reports/test_autopilot_runtime.py`

**Interfaces:**
- Consumes `deserialize_wave_plan` and `OperationCommandService.enqueue_high_value_wave`.
- Stores the high-value wave Operation ID in `DailyAutopilotRunRecord.event_operation_id`.
- Produces completed/no-content summary `{"outcome": "no_content", "event_operation_id": id, ...}`.

- [ ] **Step 1: Write a failing child-operation test**

Create a parent with a frozen WavePlan, run the `enqueue_content_wave` lease, and assert the child is `high_value_news_wave`, not `source_catalog_refresh` or `event_pipeline`:

```python
result = handler(_lease(run_id, DailyAutopilotStage.ENQUEUE_CONTENT_WAVE), checkpoint)
saved = DailyAutopilotRepository(db).get(run_id)
child = db.get(OperationRunRecord, saved.event_operation_id)
assert child.operation_type == OperationType.HIGH_VALUE_NEWS_WAVE.value
assert saved.stage == DailyAutopilotStage.WAIT_CONTENT_WAVE.value
```

- [ ] **Step 2: Run and verify RED**

Run: `uv run --extra dev pytest tests/daily_reports/test_autopilot_runtime.py::test_content_stage_enqueues_high_value_wave -q`

Expected: the new stages are not handled.

- [ ] **Step 3: Implement enqueue and wait stages**

Deserialize the frozen plan, enqueue the child with trigger `autopilot`, persist its ID as `event_operation_id`, and delayed-poll `WAIT_CONTENT_WAVE`. If another high-value wave is active, delayed-requeue `ENQUEUE_CONTENT_WAVE` without creating a child.

- [ ] **Step 4: Write failing terminal-state tests**

Cover all manifest decisions with real `OperationRunRecord` rows:

```python
@pytest.mark.parametrize("status", ("succeeded", "partial"))
def test_complete_wave_with_events_advances_to_report(status): ...

def test_wave_with_fetches_and_empty_manifest_completes_no_content():
    child.result_summary = {
        "fetch_succeeded": 3,
        "event_manifest_complete": True,
        "event_manifest_count": 0,
    }
    result = handler(_lease(run_id, DailyAutopilotStage.WAIT_CONTENT_WAVE), checkpoint)
    assert saved.status == "succeeded"
    assert saved.stage == DailyAutopilotStage.COMPLETED.value
    assert saved.result_summary["outcome"] == "no_content"

def test_wave_without_fetch_runs_fails_collection():
    child.result_summary = {
        "fetch_succeeded": 0,
        "event_manifest_complete": True,
        "event_manifest_count": 0,
    }
    assert saved.error_code == "daily_autopilot_content_not_fetched"
```

Also assert incomplete manifests and failed/cancelled child states preserve a Chinese diagnostic.

- [ ] **Step 5: Run and verify RED**

Run: `uv run --extra dev pytest tests/daily_reports/test_autopilot_runtime.py -q`

Expected: the generic child wait advances empty manifests to report generation or lacks the new error code.

- [ ] **Step 6: Implement exact terminal handling**

Add `_wait_for_content_wave`. Require terminal status `succeeded` or `partial`, `event_manifest_complete is True`, integer `fetch_succeeded`, and integer `event_manifest_count`. Advance to `GENERATE_REPORT` only when both fetch and manifest counts are positive. Finish no-content only when a real fetch completed. Fail zero-fetch and incomplete-manifest cases with Chinese messages.

Keep legacy source/event stage handlers unchanged for old rows.

- [ ] **Step 7: Update the progress page and verify Task 2**

Change the stage labels to “准备真实内容抓取” and “等待内容抓取与事件处理”. Label `event_operation` as “内容抓取与事件处理”, and render child summary counts when available.

Run:

```powershell
uv run --extra dev pytest tests/daily_reports/test_autopilot_runtime.py tests/web/test_daily_autopilot_pages.py -q
uv run --extra dev ruff check src/newsradar/daily_reports/autopilot_runtime.py tests/daily_reports/test_autopilot_runtime.py
git diff --check
```

Commit: `feat: run content wave in daily autopilot`

---

### Task 3: Generate the Report from the Parent's Exact Event Snapshot

**Files:**
- Modify: `src/newsradar/web/event_queries.py`
- Modify: `src/newsradar/daily_reports/service.py`
- Modify: `src/newsradar/daily_reports/autopilot_runtime.py`
- Test: `tests/web/test_event_queries.py`
- Test: `tests/daily_reports/test_service.py`
- Test: `tests/daily_reports/test_autopilot_runtime.py`

**Interfaces:**
- Produces `EventQueryService.operation_page(operation_id, filters=None, *, now=None) -> OperationEventPage | None`.
- Produces `DailyReportService.generate_from_operation(operation_id, window_hours, *, now=None) -> DailyReportRecord`.

- [ ] **Step 1: Write a failing exact-snapshot test**

Persist two complete event operations for the same window with distinct events. Assert `generate_from_operation(older_id, 24)` creates a report whose `source_operation_id` and items belong only to the older operation even though the newer operation is globally latest.

- [ ] **Step 2: Run and verify RED**

Run: `uv run --extra dev pytest tests/daily_reports/test_service.py::test_generate_from_operation_uses_exact_snapshot -q`

Expected: `DailyReportService` has no `generate_from_operation`.

- [ ] **Step 3: Implement the exact query boundary**

In `operation_page`, call `event_snapshot_by_id`, build rows through `_operation_rows`, apply existing filters against that snapshot, and return the same view type as `latest_operation_page`. Return `None` for an invalid, incomplete, wrong-window, or future snapshot.

Refactor report assembly into a private `_generate_from_page(page, snapshot, window_hours, checked_at)` used by both public methods. `generate_from_operation` must verify `snapshot.window_hours == window_hours` before creating a draft.

- [ ] **Step 4: Write a failing autopilot binding test**

Patch only the report service seam and assert `_generate_report` passes `run.event_operation_id` to `generate_from_operation`; it must not call `generate`.

- [ ] **Step 5: Implement the runtime call and verify Task 3**

Raise `daily_autopilot_event_operation_missing` if the run has no child ID. Otherwise call:

```python
report_id = DailyReportService(session, utcnow=self._utcnow).generate_from_operation(
    run.event_operation_id,
    run.window_hours,
).id
```

Run:

```powershell
uv run --extra dev pytest tests/web/test_event_queries.py tests/daily_reports/test_service.py tests/daily_reports/test_autopilot_runtime.py -q
uv run --extra dev ruff check src/newsradar/web/event_queries.py src/newsradar/daily_reports/service.py src/newsradar/daily_reports/autopilot_runtime.py tests/web/test_event_queries.py tests/daily_reports/test_service.py tests/daily_reports/test_autopilot_runtime.py
git diff --check
```

Commit: `fix: bind daily report to content wave snapshot`

---

### Task 4: Validate and Enqueue Both Audio Renditions Atomically

**Files:**
- Modify: `src/newsradar/daily_reports/repository.py`
- Modify: `src/newsradar/operations/commands.py`
- Modify: `src/newsradar/daily_reports/autopilot_runtime.py`
- Test: `tests/daily_reports/test_repository.py`
- Test: `tests/operations/test_commands.py`
- Test: `tests/daily_reports/test_autopilot_runtime.py`

**Interfaces:**
- Produces `DailyReportRepository.assert_audio_package_ready(report_id: int) -> None`.
- Produces `OperationCommandService.archive_and_enqueue_daily_report_audios(*, report_id: int, trigger: str) -> tuple[int, int]`.

- [ ] **Step 1: Write failing repository readiness tests**

Assert readiness rejects: zero decision items, zero overview items, unreviewed decision items, unreviewed overview items, zero included decision items, zero included overview items, and corrupted Chinese text. Assert a fully reviewed nonempty draft passes without changing its status.

- [ ] **Step 2: Run and verify RED**

Run: `uv run --extra dev pytest tests/daily_reports/test_repository.py -q`

Expected: `assert_audio_package_ready` does not exist.

- [ ] **Step 3: Implement read-only readiness validation**

Use existing item/review queries and `overview_audio_readiness`. Require a latest review for every decision and overview item, at least one included item in both renditions, and call `assert_text_integrity`. Do not commit or archive in this method.

- [ ] **Step 4: Write a failing transactional command test**

For an incomplete draft, assert the command raises and leaves the report draft with zero audio operations. For a complete draft, assert the report becomes archived and exactly two queued operations exist with renditions `decision` and `overview`.

- [ ] **Step 5: Run and verify RED**

Run: `uv run --extra dev pytest tests/operations/test_commands.py -q`

Expected: only the single-decision command exists and can archive before overview validation.

- [ ] **Step 6: Implement the atomic pair command**

Within one `session.begin()` block: lock the report, call `assert_audio_package_ready`, archive with `commit=False`, then call `_enqueue_daily_report_audio` for both renditions. Return both IDs. Preserve the existing single-rendition commands for manual recovery.

- [ ] **Step 7: Change the autopilot stage and verify Task 4**

Replace the two sequential command calls with the pair command when either ID is missing. Persist both IDs in the same parent transition. Add an idempotency test for an already-populated pair.

Run:

```powershell
uv run --extra dev pytest tests/daily_reports/test_repository.py tests/operations/test_commands.py tests/daily_reports/test_autopilot_runtime.py -q
uv run --extra dev ruff check src/newsradar/daily_reports/repository.py src/newsradar/operations/commands.py src/newsradar/daily_reports/autopilot_runtime.py tests/daily_reports/test_repository.py tests/operations/test_commands.py tests/daily_reports/test_autopilot_runtime.py
git diff --check
```

Commit: `fix: publish daily audio package atomically`

---

### Task 5: Expose Collection Metrics and Complete Acceptance

**Files:**
- Modify: `src/newsradar/web/daily_report_queries.py`
- Modify: `src/newsradar/web/templates/daily_autopilot_detail.html`
- Modify: `src/newsradar/web/templates/daily_reports.html`
- Modify: `src/newsradar/web/static/app.css`
- Test: `tests/web/test_daily_autopilot_pages.py`
- Test: `tests/acceptance/test_daily_autopilot_content_wave.py`

**Interfaces:**
- Extends the automatic-run detail view with secret-free wave metrics read from the child `result_summary`.
- Adds an acceptance flow using real repositories, the real high-value wave handler with injected fetch executor, the real event pipeline, report generation, review, and queued audio operations.

- [ ] **Step 1: Write failing page assertions**

Build a completed child summary and assert the page renders Chinese labels and values for member total, fetch success, blocked, items received/inserted/unchanged, event manifest count, confirmed count, and both audio states. Assert it no longer calls the child “来源目录刷新”.

- [ ] **Step 2: Run and verify RED**

Run: `uv run --extra dev pytest tests/web/test_daily_autopilot_pages.py -q`

Expected: the new metrics and labels are absent.

- [ ] **Step 3: Implement bounded metric extraction and UI**

Read only known nonnegative integer keys from the child summary; treat malformed or absent values as unavailable. Render a responsive metric grid and a Chinese next action for collection failure, true no-content, partial success, report generation, and per-audio failure.

- [ ] **Step 4: Write the end-to-end acceptance test**

The injected executor must return normalized items for two sources and a failure for a third. The test must prove:

```python
assert fetch_run_count == 2
assert raw_item_count > 0
assert wave.result_summary["event_manifest_complete"] is True
assert report.source_operation_id == wave.id
assert report.generation_summary["overview_count"] > 0
assert all(item_has_review(item) for item in decision_and_overview_items)
assert queued_renditions == {"decision", "overview"}
```

It must also prove the failed member did not prevent completion.

- [ ] **Step 5: Run focused acceptance and verify GREEN**

Run:

```powershell
uv run --extra dev --extra research pytest tests/acceptance/test_daily_autopilot_content_wave.py tests/web/test_daily_autopilot_pages.py -q
uv run --extra dev ruff check src/newsradar/web/daily_report_queries.py src/newsradar/web/templates tests/web/test_daily_autopilot_pages.py tests/acceptance/test_daily_autopilot_content_wave.py
git diff --check
```

- [ ] **Step 6: Run full verification**

Run:

```powershell
uv run --extra dev --extra research pytest -q
uv run --extra dev ruff check .
git diff --check
```

Expected: all tests pass, only explicitly configured skips remain, Ruff reports no errors, and diff check is clean.

- [ ] **Step 7: Commit the milestone**

Commit: `feat: complete real-content daily autopilot`

- [ ] **Step 8: Prepare real browser acceptance without merging**

Do not alter the production database from the worktree. Report the verified branch and ask for user confirmation before local merge, service restart, or a real 24-hour network run.
