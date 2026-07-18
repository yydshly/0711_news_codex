# Daily Automation Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a low-CPU, webpage-controlled 07:30 daily-report scheduler plus 90-day retention, pinning, a 30-day recycle bin, and resumable permanent cleanup on top of the existing durable Worker and daily-autopilot pipeline.

**Architecture:** Persist one automation configuration row and let the existing Worker perform one indexed due check per 60 seconds before enqueuing the existing `DailyAutopilotRun`. Keep all heavy work in durable operations. Add soft-delete fields to daily reports, then perform permanent audio-file and database cleanup through a bounded durable purge operation.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL/SQLite tests, Jinja2, Typer, pytest, Ruff.

## Global Constraints

- Automatic execution is disabled by default and runs every day at `07:30` in `Asia/Shanghai` only after the user enables it in the webpage.
- Scheduled runs always use a 24-hour window; manual “run now” keeps 24/48/72-hour choices.
- Pausing prevents future schedules and never cancels the active run.
- Missed schedules catch up the current Shanghai date once and never backfill earlier dates.
- Same-day duplicate triggers reuse `queued`, `running`, or `succeeded` runs; `failed` and `cancelled` runs may be retried.
- Standard limits are global fetch concurrency 8, provider concurrency 2, and model concurrency 2.
- The scheduling due query runs at most once per 60 seconds and must not create a busy loop or extra network thread.
- Non-pinned reports move to trash after 90 days; trash retains them for 30 more days.
- Purge batches contain at most 20 reports and must yield before another batch.
- Purge deletes report rows, report reviews, audio records, and controlled MP3 files only. It preserves RawItem, Event, Source, Evidence, FetchRun, and Operation history.
- Active report/audio work blocks trash and purge with a Chinese diagnostic.
- All webpage mutations use POST, the existing action token, and same-origin enforcement.
- No test may delete a real report, contact an external source, or call MiniMax.
- Do not read, print, stage, or commit `.env` or the user-owned `reports/` files.
- Use test-driven development: observe each new test fail before implementation, then rerun it to green.

---

## File Structure Map

**Create**

- `migrations/versions/20260718_0029_daily_automation_retention.py` — configuration table and retention columns/indexes.
- `src/newsradar/daily_reports/automation.py` — pure Shanghai-time scheduling calculations and immutable result types.
- `src/newsradar/daily_reports/automation_repository.py` — singleton configuration locking and state transitions.
- `src/newsradar/daily_reports/automation_service.py` — due tick, catch-up, retention sweep, and enqueue orchestration.
- `src/newsradar/daily_reports/retention.py` — report pin/trash/restore eligibility and bounded purge planning.
- `src/newsradar/daily_reports/purge_runtime.py` — durable, resumable MP3/database purge handler.
- `src/newsradar/waves/local_plan.py` — one shared local-only high-value `WavePlan` factory for Web, CLI, and Worker.
- `src/newsradar/web/daily_automation_queries.py` — control-console and trash-page read models.
- `src/newsradar/web/templates/daily_report_trash.html` — recycle-bin page.
- `tests/daily_reports/test_automation.py`
- `tests/daily_reports/test_automation_repository.py`
- `tests/daily_reports/test_automation_service.py`
- `tests/daily_reports/test_retention.py`
- `tests/daily_reports/test_purge_runtime.py`
- `tests/daily_reports/test_automation_migration.py`
- `tests/web/test_daily_automation_pages.py`

**Modify**

- `src/newsradar/db/models.py` — automation config and report retention columns.
- `src/newsradar/operations/schema.py` — add `DAILY_REPORT_PURGE` operation type.
- `src/newsradar/operations/commands.py` — enqueue bounded purge operations and reuse the shared wave-plan boundary.
- `src/newsradar/waves/runtime.py` — read and enforce frozen standard wave concurrency (8 global, 2 per provider).
- `src/newsradar/cli.py` — call the low-frequency scheduler tick and register the purge handler.
- `src/newsradar/web/app.py` — automation and retention POST routes plus trash GET route.
- `src/newsradar/web/daily_report_queries.py` — exclude trash by default and expose retention metadata.
- `src/newsradar/web/templates/daily_reports.html` — console, retention filters, pin/trash/bulk controls.
- `src/newsradar/web/templates/daily_report_detail.html` — pin/trash controls and trash isolation.
- `src/newsradar/daily_reports/autopilot_runtime.py` — treat report success plus one failed audio rendition as partial audio completion, not report loss.
- `src/newsradar/web/static/app.js` — ten-second polling only while an active task exists and bulk-selection behavior.
- `src/newsradar/web/static/styles.css` — compact control-console, state, and trash layouts.
- `tests/operations/test_commands.py`
- `tests/waves/test_runtime.py`
- `tests/daily_reports/test_autopilot_runtime.py`
- `tests/web/test_daily_report_pages.py`
- `tests/web/test_daily_autopilot_pages.py`
- `tests/test_migrations.py`

---

## Milestone A — Persistent Scheduling and Web Control

### Task 1: Add the Automation and Retention Schema

**Files:**
- Create: `migrations/versions/20260718_0029_daily_automation_retention.py`
- Create: `tests/daily_reports/test_automation_migration.py`
- Modify: `src/newsradar/db/models.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Produces: `DailyAutomationConfigRecord` and retention fields on `DailyReportRecord`.
- Consumes: existing SQLAlchemy `Base`, Alembic head `20260718_0028`, and UTC timestamps.

- [ ] **Step 1: Write the failing model and migration tests**

```python
def _upgrade(database_url: str, revision: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, revision)


def test_0029_adds_schedule_and_retention_columns(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'daily-automation.db').as_posix()}"
    _upgrade(database_url, "20260718_0028")
    _upgrade(database_url, "20260718_0029")
    inspector = inspect(create_engine(database_url))
    assert "daily_automation_config" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("daily_reports")}
    assert {"pinned_at", "deleted_at", "purge_after"} <= columns
```

- [ ] **Step 2: Run the tests and verify the missing symbols/schema fail**

Run: `uv run --extra dev pytest tests/daily_reports/test_automation_migration.py tests/test_migrations.py -q`

Expected: FAIL because revision `0029`, `DailyAutomationConfigRecord`, and the retention columns do not exist.

- [ ] **Step 3: Add exact ORM fields and migration constraints**

```python
class DailyAutomationConfigRecord(Base):
    __tablename__ = "daily_automation_config"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_daily_automation_singleton"),
        CheckConstraint("window_hours = 24", name="ck_daily_automation_window"),
        CheckConstraint(
            "resource_profile IN ('standard', 'power_saver')",
            name="ck_daily_automation_resource_profile",
        ),
        Index("ix_daily_automation_next_run", "enabled", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    daily_time: Mapped[str] = mapped_column(String(5), nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    resource_profile: Mapped[str] = mapped_column(String(16), nullable=False)
    last_scheduled_date: Mapped[date | None] = mapped_column(Date)
    last_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_autopilot_runs.id", ondelete="SET NULL")
    )
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

Add nullable `pinned_at`, `deleted_at`, and `purge_after` UTC columns to `DailyReportRecord`; add indexes `ix_daily_reports_deleted_purge` on `(deleted_at, purge_after)` and `ix_daily_reports_pinned_date` on `(pinned_at, report_date)`.

The Alembic upgrade creates the table and columns without inserting the singleton row. The repository creates it lazily with disabled defaults. Downgrade drops indexes, columns, then the table.

- [ ] **Step 4: Run migration, model, and full migration tests**

Run: `uv run --extra dev pytest tests/daily_reports/test_automation_migration.py tests/test_migrations.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the schema boundary**

```powershell
git add migrations/versions/20260718_0029_daily_automation_retention.py src/newsradar/db/models.py tests/daily_reports/test_automation_migration.py tests/test_migrations.py
git commit -m "feat: add daily automation retention schema"
```

### Task 2: Implement Pure Scheduling Rules and the Singleton Repository

**Files:**
- Create: `src/newsradar/daily_reports/automation.py`
- Create: `src/newsradar/daily_reports/automation_repository.py`
- Create: `tests/daily_reports/test_automation.py`
- Create: `tests/daily_reports/test_automation_repository.py`

**Interfaces:**
- Produces: `next_daily_run(now: datetime, daily_time: time) -> datetime`.
- Produces: `DailyAutomationRepository.get_or_create()`, `enable()`, `pause()`, `lock_due()`, and `mark_scheduled()`.
- Consumes: `DailyAutomationConfigRecord` from Task 1.

- [ ] **Step 1: Write failing timezone, catch-up, pause, and lock tests**

```python
def test_next_daily_run_uses_shanghai_time() -> None:
    now = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)  # 08:00 Shanghai
    assert next_daily_run(now, time(7, 30)) == datetime(
        2026, 7, 18, 23, 30, tzinfo=UTC
    )


def test_lock_due_returns_today_once(db_session: Session) -> None:
    now = datetime(2026, 7, 18, 1, 0, tzinfo=UTC)  # 09:00 Shanghai
    repository = DailyAutomationRepository(db_session, utcnow=lambda: now)
    repository.enable()
    due = repository.lock_due()
    assert due is not None and due.schedule_date == date(2026, 7, 18)
    repository.mark_scheduled(due, run_id=7)
    assert repository.lock_due() is None


def test_pause_keeps_last_run_and_blocks_due(db_session: Session) -> None:
    repository = DailyAutomationRepository(db_session)
    repository.enable()
    repository.pause()
    assert repository.get_or_create().enabled is False
    assert repository.lock_due() is None


def test_automation_config_is_created_disabled(db_session: Session) -> None:
    row = DailyAutomationRepository(db_session).get_or_create()
    assert row.id == 1
    assert row.enabled is False
    assert row.timezone == "Asia/Shanghai"
    assert row.daily_time == "07:30"
```

- [ ] **Step 2: Run and observe failures**

Run: `uv run --extra dev pytest tests/daily_reports/test_automation.py tests/daily_reports/test_automation_repository.py -q`

Expected: FAIL because both modules are absent.

- [ ] **Step 3: Implement pure time calculations**

```python
REPORT_ZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class DueSchedule:
    schedule_date: date
    due_at: datetime


def next_daily_run(now: datetime, daily_time: time = time(7, 30)) -> datetime:
    local_now = _aware_utc(now).astimezone(REPORT_ZONE)
    candidate = datetime.combine(local_now.date(), daily_time, REPORT_ZONE)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def due_schedule(now: datetime, last_scheduled_date: date | None) -> DueSchedule | None:
    local_now = _aware_utc(now).astimezone(REPORT_ZONE)
    due_local = datetime.combine(local_now.date(), time(7, 30), REPORT_ZONE)
    if local_now < due_local or last_scheduled_date == local_now.date():
        return None
    return DueSchedule(local_now.date(), due_local.astimezone(UTC))
```

- [ ] **Step 4: Implement repository transaction semantics**

`get_or_create()` inserts singleton ID 1 with `enabled=False`. `lock_due()` uses `SELECT ... FOR UPDATE`; PostgreSQL additionally acquires `pg_advisory_xact_lock(hashtext('newsradar:daily-automation-due'))`. `enable()` computes the next scheduled time but allows same-day catch-up through `due_schedule()`. `pause()` never touches a run. `mark_scheduled()` verifies the locked schedule date, then sets `last_scheduled_date`, `last_run_id`, and next-day `next_run_at`.

- [ ] **Step 5: Run all scheduling tests**

Run: `uv run --extra dev pytest tests/daily_reports/test_automation.py tests/daily_reports/test_automation_repository.py -q`

Expected: PASS, including SQLite-aware naive timestamp normalization.

- [ ] **Step 6: Commit scheduling rules**

```powershell
git add src/newsradar/daily_reports/automation.py src/newsradar/daily_reports/automation_repository.py tests/daily_reports/test_automation.py tests/daily_reports/test_automation_repository.py
git commit -m "feat: persist daily automation schedule"
```

### Task 3: Share the Local Wave-Plan Boundary and Enqueue Due Runs

**Files:**
- Create: `src/newsradar/waves/local_plan.py`
- Create: `src/newsradar/daily_reports/automation_service.py`
- Create: `tests/daily_reports/test_automation_service.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/cli.py`
- Modify: `src/newsradar/operations/commands.py`
- Modify: `src/newsradar/waves/runtime.py`
- Modify: `tests/operations/test_commands.py`
- Modify: `tests/waves/test_runtime.py`

**Interfaces:**
- Produces: `build_local_wave_plan(session, *, profile_path: Path, window_hours: int) -> WavePlan`.
- Produces: `DailyAutomationService.tick() -> DailyAutomationTickResult`.
- `DailyAutomationService` accepts `plan_factory: Callable[[Session, int], WavePlan]`; production injects `lambda session, hours: build_local_wave_plan(session, window_hours=hours)` so the keyword-only shared factory remains explicit.
- Produces: `OperationCommandService.enqueue_daily_autopilot_result() -> DailyAutopilotEnqueueResult`; the existing `enqueue_daily_autopilot() -> int` remains a compatibility wrapper.
- Consumes: Tasks 1–2 and `OperationCommandService.enqueue_daily_autopilot()`.

- [ ] **Step 1: Write failing tests proving no I/O and one enqueue**

```python
def test_tick_enqueues_one_existing_autopilot(monkeypatch, db_session) -> None:
    service = DailyAutomationService(
        db_session,
        plan_factory=lambda session, hours: _wave_plan(hours),
        utcnow=lambda: datetime(2026, 7, 18, 1, 0, tzinfo=UTC),
    )
    DailyAutomationRepository(db_session, utcnow=service.utcnow).enable()
    result = service.tick()
    assert result.outcome == "enqueued"
    assert result.run_id is not None
    assert db_session.query(DailyAutopilotRunRecord).count() == 1


def test_second_tick_reuses_same_run(db_session) -> None:
    first = _service(db_session).tick()
    second = _service(db_session).tick()
    assert second.outcome == "not_due"
    assert db_session.query(DailyAutopilotRunRecord).count() == 1
    assert first.run_id is not None


def test_scheduled_wave_freezes_standard_concurrency(db_session) -> None:
    result = _enabled_service(db_session).tick()
    run = db_session.get(DailyAutopilotRunRecord, result.run_id)
    wave = deserialize_wave_plan(run.requested_scope["wave_plan"])
    operation_id = OperationCommandService(db_session).enqueue_high_value_wave(
        plan=wave,
        trigger="test",
        global_concurrency=8,
        provider_concurrency=2,
    )
    scope = db_session.get(OperationRunRecord, operation_id).requested_scope
    assert scope["global_concurrency"] == 8
    assert scope["provider_concurrency"] == 2
```

- [ ] **Step 2: Run and observe missing service failures**

Run: `uv run --extra dev pytest tests/daily_reports/test_automation_service.py -q`

Expected: FAIL because the service and shared local plan factory do not exist.

- [ ] **Step 3: Extract the local-only plan factory**

Move the duplicated Web `_high_value_wave_plan` and CLI `_wave_plan_from_local_catalog` behavior into:

```python
def build_local_wave_plan(
    session: Session,
    *,
    profile_path: Path = Path("wave_profiles/high-value-ai-tech.yaml"),
    window_hours: int = 24,
) -> WavePlan:
    profile = load_wave_profile(profile_path).model_copy(
        update={"window_hours": window_hours}
    )
    sources = load_source_tree(Path("sources"))
    providers = load_provider_tree(Path("providers"))
    ProviderRepository(session).sync(providers)
    SourceRepository(session).sync(sources)
    session.commit()
    repository = SourceRepository(session)
    source_ids = list(profile.source_ids)
    return build_wave_plan(
        profile,
        sources,
        repository.latest_probe_snapshots(source_ids),
        SettingsCredentials().configured_names(),
        successful_fetch_access=repository.successful_fetch_access(source_ids),
    )
```

The factory reads local reviewed YAML and persisted probe history only. It must not construct an HTTP client or invoke MiniMax.

- [ ] **Step 4: Implement the due-tick transaction**

```python
@dataclass(frozen=True, slots=True)
class DailyAutomationTickResult:
    outcome: Literal["disabled", "not_due", "enqueued", "reused"]
    run_id: int | None = None


@dataclass(frozen=True, slots=True)
class DailyAutopilotEnqueueResult:
    run_id: int
    created: bool


def tick(self) -> DailyAutomationTickResult:
    due = self.schedules.lock_due()
    if due is None:
        return DailyAutomationTickResult(self.schedules.idle_reason())
    plan = self.plan_factory(self.session, 24)
    enqueue = OperationCommandService(
        self.session, utcnow=self.utcnow
    ).enqueue_daily_autopilot_result(plan=plan, trigger="schedule")
    self.schedules.mark_scheduled(due, run_id=enqueue.run_id)
    self.session.commit()
    outcome = "enqueued" if enqueue.created else "reused"
    return DailyAutomationTickResult(outcome, enqueue.run_id)
```

Move the current enqueue body into `enqueue_daily_autopilot_result()`. Return `created=False` when `reusable_for_daily_wave()` finds an existing run and `created=True` after creating the run plus its first continuation. Keep `enqueue_daily_autopilot()` as a wrapper that forwards `plan` and `trigger`, then returns `.run_id`, so all existing callers and tests remain compatible.

Extend `enqueue_high_value_wave()` with validated keyword arguments `global_concurrency: int = 8` and `provider_concurrency: int = 2`, persist both in the frozen operation scope, and make `HighValueWaveHandler._run()` construct semaphores from those values. Reject values outside 1–16 global or 1–8 per provider before any member starts. Add an async executor test that records simultaneous calls and proves the configured limits are honored.

- [ ] **Step 5: Run service, Web, CLI, and command tests**

Run: `uv run --extra dev pytest tests/daily_reports/test_automation_service.py tests/operations/test_commands.py tests/waves/test_runtime.py tests/web/test_daily_autopilot_pages.py tests/web/test_cli.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the shared enqueue boundary**

```powershell
git add src/newsradar/waves/local_plan.py src/newsradar/waves/runtime.py src/newsradar/daily_reports/automation_service.py src/newsradar/operations/commands.py src/newsradar/web/app.py src/newsradar/cli.py tests/daily_reports/test_automation_service.py tests/operations/test_commands.py tests/waves/test_runtime.py tests/web/test_daily_autopilot_pages.py tests/web/test_cli.py
git commit -m "feat: enqueue due daily automation runs"
```

### Task 4: Integrate a Low-Frequency Tick into the Existing Worker

**Files:**
- Modify: `src/newsradar/cli.py`
- Modify: `tests/web/test_cli.py`
- Modify: `tests/daily_reports/test_automation_service.py`

**Interfaces:**
- Consumes: `DailyAutomationService.tick()` from Task 3.
- Produces: one schedule check per 60 seconds without changing operation polling responsiveness.

- [ ] **Step 1: Write failing fake-clock tests for the 60-second gate**

```python
def test_worker_checks_schedule_at_most_once_per_minute(monkeypatch) -> None:
    clock = iter((0.0, 1.0, 59.9, 60.0, 60.1))
    ticks: list[float] = []
    monkeypatch.setattr("newsradar.cli.monotonic", lambda: next(clock))
    monkeypatch.setattr(
        "newsradar.cli._tick_daily_automation", lambda: ticks.append(1.0)
    )
    _exercise_idle_worker_iterations(5)
    assert len(ticks) == 2
```

Also assert `--once` performs no implicit recurring wait and that a schedule tick only enqueues database work.

- [ ] **Step 2: Run the worker tests and observe over-calling/missing helper failure**

Run: `uv run --extra dev pytest tests/web/test_cli.py -k "schedule or worker" -q`

Expected: FAIL before the gate exists.

- [ ] **Step 3: Add a monotonic deadline to the existing loop**

```python
SCHEDULE_CHECK_SECONDS = 60.0
next_schedule_check = 0.0

while True:
    now_monotonic = monotonic()
    if not once and now_monotonic >= next_schedule_check:
        _tick_daily_automation()
        next_schedule_check = now_monotonic + SCHEDULE_CHECK_SECONDS
    with create_session() as session:
        processed = Worker(
            OperationRepository(session),
            identifier,
            lease_guard=guard,
            lease_seconds=settings.worker_lease_seconds,
            monitor_interval_seconds=settings.worker_heartbeat_seconds,
        ).run_once(handler)
    if once:
        break
    if not processed:
        time.sleep(poll_seconds)
```

`_tick_daily_automation()` opens and closes one session, catches `SQLAlchemyError`, emits one structured warning without secrets, and lets the Worker continue consuming existing operations.

- [ ] **Step 4: Run worker and performance-contract tests**

Run: `uv run --extra dev pytest tests/web/test_cli.py tests/daily_reports/test_automation_service.py -q`

Expected: PASS; fake time proves no busy schedule loop.

- [ ] **Step 5: Commit Worker scheduling**

```powershell
git add src/newsradar/cli.py tests/web/test_cli.py tests/daily_reports/test_automation_service.py
git commit -m "feat: tick daily schedule without busy polling"
```

### Task 5: Build the Web Automation Console

**Files:**
- Create: `src/newsradar/web/daily_automation_queries.py`
- Create: `tests/web/test_daily_automation_pages.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/daily_reports.html`
- Modify: `src/newsradar/web/static/app.js`
- Modify: `src/newsradar/web/static/styles.css`

**Interfaces:**
- Produces: `DailyAutomationView` with enabled state, next run, last run, Worker health, and active-run link.
- Consumes: Tasks 2–4, existing action-token helpers, and existing autopilot query views.

- [ ] **Step 1: Write failing GET and POST route tests**

```python
def test_daily_report_page_shows_paused_console(client) -> None:
    response = client.get("/daily-reports")
    assert response.status_code == 200
    assert "日报自动化控制台" in response.text
    assert "已暂停" in response.text
    assert "每天 07:30" in response.text


def test_enable_requires_safe_action(client) -> None:
    response = client.post("/daily-automation/enable")
    assert response.status_code == 403


def test_enable_then_pause_does_not_cancel_active_run(safe_client, db_session) -> None:
    active = _seed_active_autopilot(db_session)
    safe_client.post("/daily-automation/enable", data=_token(safe_client))
    safe_client.post("/daily-automation/pause", data=_token(safe_client))
    assert DailyAutopilotRepository(db_session).get(active.id).status == "running"
```

- [ ] **Step 2: Run and verify missing UI/routes fail**

Run: `uv run --extra dev pytest tests/web/test_daily_automation_pages.py -q`

Expected: FAIL with missing console text and 404 routes.

- [ ] **Step 3: Add the read model and exact POST routes**

```python
@dataclass(frozen=True, slots=True)
class DailyAutomationView:
    enabled: bool
    status_zh: str
    daily_time: str
    timezone: str
    window_hours: int
    resource_profile_zh: str
    next_run_at: datetime | None
    last_run: DailyAutopilotSummaryView | None
    active_run: DailyAutopilotSummaryView | None
    worker_online: bool
    diagnostic_zh: str
```

Worker health is online only when the newest `WorkerRecord.last_heartbeat_at` or active operation heartbeat is newer than `now - 2 * worker_lease_seconds`; otherwise render “调度服务离线”。Do not query operation history beyond the newest matching rows.

Add `POST /daily-automation/enable`, `/pause`, and `/run-now`. Each calls `require_safe_action`. `run-now` validates 24/48/72, calls the same shared plan factory and `enqueue_daily_autopilot`, then redirects to the run detail. Enable/pause redirect to `/daily-reports`.

- [ ] **Step 4: Render the console and conditional polling contract**

Render enabled/paused state, 07:30, next/last run, active stage, run-now selector, and existing cancel link. Add `data-active-daily-run="true"` only while queued/running. JavaScript schedules a page reload after 10 seconds only when that attribute is present; no timer exists on idle pages.

- [ ] **Step 5: Run Web security and rendering tests**

Run: `uv run --extra dev pytest tests/web/test_daily_automation_pages.py tests/web/test_daily_report_pages.py tests/web/test_daily_autopilot_pages.py -q`

Expected: PASS, including escaped Chinese diagnostics and no secrets in HTML.

- [ ] **Step 6: Commit Milestone A UI**

```powershell
git add src/newsradar/web/daily_automation_queries.py src/newsradar/web/app.py src/newsradar/web/templates/daily_reports.html src/newsradar/web/static/app.js src/newsradar/web/static/styles.css tests/web/test_daily_automation_pages.py tests/web/test_daily_report_pages.py tests/web/test_daily_autopilot_pages.py
git commit -m "feat: add webpage daily automation controls"
```

- [ ] **Step 7: Run the Milestone A gate**

Run: `uv run --extra dev pytest tests/daily_reports/test_automation.py tests/daily_reports/test_automation_repository.py tests/daily_reports/test_automation_service.py tests/operations/test_commands.py tests/web/test_cli.py tests/web/test_daily_automation_pages.py tests/web/test_daily_report_pages.py tests/web/test_daily_autopilot_pages.py -q`

Expected: PASS. Verify the automation row remains disabled in a fresh database.

---

## Milestone B — Retention, Pinning, and Recycle Bin

### Task 6: Implement Retention Eligibility, Pin, Trash, and Restore

**Files:**
- Create: `src/newsradar/daily_reports/retention.py`
- Create: `tests/daily_reports/test_retention.py`
- Modify: `src/newsradar/daily_reports/repository.py`
- Modify: `src/newsradar/web/daily_report_queries.py`

**Interfaces:**
- Produces: `DailyReportRepository.pin()`, `unpin()`, `move_to_trash()`, `restore()`, and `trash_candidates()`.
- Produces: `RetentionActionResult(report_id, outcome, diagnostic_zh)`.
- Consumes: Task 1 retention columns and existing Operation/Autopilot status.

- [ ] **Step 1: Write failing retention rule tests**

```python
def test_pinned_report_is_not_an_automatic_trash_candidate(db_session) -> None:
    report = _archived_report(db_session, report_date=date(2026, 3, 1))
    DailyReportRepository(db_session).pin(report.id)
    candidates = DailyReportRepository(db_session).trash_candidates(
        cutoff=date(2026, 4, 19), limit=50
    )
    assert report.id not in {row.id for row in candidates}


def test_manual_trash_sets_thirty_day_purge(db_session) -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    report = _archived_report(db_session)
    result = DailyReportRepository(db_session, utcnow=lambda: now).move_to_trash(
        report.id, automatic=False
    )
    assert result.outcome == "trashed"
    assert report.deleted_at == now
    assert report.purge_after == now + timedelta(days=30)


def test_active_audio_blocks_trash(db_session) -> None:
    report = _report_with_running_audio(db_session)
    result = DailyReportRepository(db_session).move_to_trash(report.id, automatic=False)
    assert result.outcome == "blocked"
    assert result.diagnostic_zh == "日报语音仍在处理中，完成或取消后才能删除。"
```

- [ ] **Step 2: Run and observe missing methods fail**

Run: `uv run --extra dev pytest tests/daily_reports/test_retention.py -q`

Expected: FAIL because retention methods are absent.

- [ ] **Step 3: Implement exact eligibility and state transitions**

```python
@dataclass(frozen=True, slots=True)
class RetentionActionResult:
    report_id: int
    outcome: Literal["pinned", "unpinned", "trashed", "restored", "blocked", "unchanged"]
    diagnostic_zh: str


RETENTION_DAYS = 90
TRASH_DAYS = 30
TRASH_BATCH_LIMIT = 50
```

Lock the report with `FOR UPDATE`. Block trash when a linked autopilot run is queued/running, a linked audio operation is queued/running, or a purge operation already owns the report. Automatic trash excludes pinned reports; manual trash allows pinned reports after the explicit POST. Restore clears `deleted_at` and `purge_after` but leaves `pinned_at` unchanged.

- [ ] **Step 4: Filter ordinary report queries and expose retention metadata**

`list_reports()` adds `DailyReportRecord.deleted_at.is_(None)` and supports `period=all|7|30|pinned`. `detail()` returns no normal detail for trashed reports. Add `trash_reports(page, page_size)` and `trash_state(report_id)` for the dedicated page/redirect behavior.

- [ ] **Step 5: Run repository and query tests**

Run: `uv run --extra dev pytest tests/daily_reports/test_retention.py tests/daily_reports/test_repository.py tests/web/test_daily_report_pages.py -q`

Expected: PASS; current non-deleted report behavior remains unchanged.

- [ ] **Step 6: Commit retention state transitions**

```powershell
git add src/newsradar/daily_reports/retention.py src/newsradar/daily_reports/repository.py src/newsradar/web/daily_report_queries.py tests/daily_reports/test_retention.py tests/daily_reports/test_repository.py tests/web/test_daily_report_pages.py
git commit -m "feat: add report retention states"
```

### Task 7: Add Archive Controls, Bulk Actions, and the Trash Page

**Files:**
- Create: `src/newsradar/web/templates/daily_report_trash.html`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/daily_reports.html`
- Modify: `src/newsradar/web/templates/daily_report_detail.html`
- Modify: `src/newsradar/web/static/app.js`
- Modify: `src/newsradar/web/static/styles.css`
- Modify: `tests/web/test_daily_report_pages.py`
- Modify: `tests/web/test_daily_automation_pages.py`

**Interfaces:**
- Consumes: retention repository/query APIs from Task 6.
- Produces: exact routes for pin, unpin, trash, restore, purge request, and bulk trash/restore.

- [ ] **Step 1: Write failing page and action-security tests**

```python
def test_archive_page_shows_pin_and_trash_controls(safe_client, archived_report) -> None:
    response = safe_client.get("/daily-reports")
    assert "置顶保护" in response.text
    assert "移入回收站" in response.text
    assert 'href="/daily-reports/trash"' in response.text


def test_trash_page_hides_report_body(safe_client, trashed_report) -> None:
    response = safe_client.get(f"/daily-reports/{trashed_report.id}")
    assert response.status_code == 303
    assert response.headers["location"] == "/daily-reports/trash"
    trash = safe_client.get("/daily-reports/trash")
    assert "恢复" in trash.text
    assert trashed_report.generation_summary["private_marker"] not in trash.text


def test_bulk_trash_limits_fifty_ids(safe_client) -> None:
    response = safe_client.post(
        "/daily-reports/bulk/trash",
        data={**_token(safe_client), "report_ids": [str(i) for i in range(51)]},
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run and observe missing routes/UI fail**

Run: `uv run --extra dev pytest tests/web/test_daily_report_pages.py tests/web/test_daily_automation_pages.py -k "trash or pin or bulk" -q`

Expected: FAIL with missing controls and routes.

- [ ] **Step 3: Add exact safe routes**

Implement `/pin`, `/unpin`, `/trash`, `/restore`, `/bulk/trash`, `/bulk/restore`, and `GET /daily-reports/trash`. Each POST calls `require_safe_action`; bulk IDs are parsed as positive integers, deduplicated, and limited to 50. Return per-item flash-safe summary counts through query parameters containing counts only, never report content. Do not add `/purge` until Task 8 supplies the durable operation.

- [ ] **Step 4: Render archive and trash controls**

Add current-page checkboxes, pin state, retention days, disabled reasons, period filter, and the trash link. The trash page shows deletion/purge dates and restore forms only in this milestone; Task 8 adds the permanent-delete form after the durable purge command exists. Never place report body or model audit content on the trash page.

- [ ] **Step 5: Run all retention Web tests**

Run: `uv run --extra dev pytest tests/web/test_daily_report_pages.py tests/web/test_daily_automation_pages.py -q`

Expected: PASS, including CSRF/same-origin rejection and HTML escaping.

- [ ] **Step 6: Commit Milestone B UI**

```powershell
git add src/newsradar/web/app.py src/newsradar/web/templates/daily_reports.html src/newsradar/web/templates/daily_report_detail.html src/newsradar/web/templates/daily_report_trash.html src/newsradar/web/static/app.js src/newsradar/web/static/styles.css tests/web/test_daily_report_pages.py tests/web/test_daily_automation_pages.py
git commit -m "feat: add daily report recycle bin"
```

- [ ] **Step 7: Run the Milestone B gate**

Run: `uv run --extra dev pytest tests/daily_reports/test_retention.py tests/daily_reports/test_repository.py tests/web/test_daily_report_pages.py tests/web/test_daily_automation_pages.py -q`

Expected: PASS. Verify no seeded real report is modified during page GET tests.

---

## Milestone C — Durable Purge, Partial Audio Recovery, and Production Gate

### Task 8: Implement a Bounded Durable Purge Operation

**Files:**
- Create: `src/newsradar/daily_reports/purge_runtime.py`
- Create: `tests/daily_reports/test_purge_runtime.py`
- Modify: `src/newsradar/operations/schema.py`
- Modify: `src/newsradar/operations/commands.py`
- Modify: `src/newsradar/cli.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/daily_report_trash.html`
- Modify: `tests/operations/test_commands.py`
- Modify: `tests/web/test_daily_report_pages.py`

**Interfaces:**
- Produces: `OperationType.DAILY_REPORT_PURGE`.
- Produces: `OperationCommandService.enqueue_daily_report_purge(report_ids, trigger) -> int`.
- Produces: `DailyReportPurgeHandler(session_factory, audio_root)`.
- Consumes: Task 6 trash state and existing audio-path containment rules.

- [ ] **Step 1: Write failing enqueue, safety, and partial-batch tests**

```python
def test_enqueue_purge_rejects_more_than_twenty(db_session) -> None:
    with pytest.raises(ValueError, match="daily_report_purge_batch_too_large"):
        OperationCommandService(db_session).enqueue_daily_report_purge(
            tuple(range(1, 22)), trigger="retention"
        )


def test_purge_removes_report_but_preserves_event_and_operation(
    db_session, tmp_path
) -> None:
    seeded = _trashed_report_with_audio(db_session, tmp_path)
    result = _handler(db_session, tmp_path)(_lease(seeded.report.id), lambda _: None)
    assert result.status is OperationStatus.SUCCEEDED
    assert db_session.get(DailyReportRecord, seeded.report.id) is None
    assert db_session.get(EventRecord, seeded.event.id) is not None
    assert db_session.get(OperationRunRecord, seeded.source_operation.id) is not None


def test_file_failure_keeps_database_report(db_session, tmp_path, monkeypatch) -> None:
    seeded = _trashed_report_with_audio(db_session, tmp_path)
    monkeypatch.setattr(Path, "unlink", Mock(side_effect=OSError("locked")))
    result = _handler(db_session, tmp_path)(_lease(seeded.report.id), lambda _: None)
    assert result.status is OperationStatus.FAILED
    assert result.retryable is True
    assert db_session.get(DailyReportRecord, seeded.report.id) is not None


def test_purge_reparents_newer_revision_and_detaches_copied_reviews(
    db_session, tmp_path
) -> None:
    chain = _three_revision_chain_with_copied_reviews(db_session, tmp_path)
    result = _handler(db_session, tmp_path)(
        _lease(chain.middle.id), lambda _: None
    )
    assert result.status is OperationStatus.SUCCEEDED
    assert chain.newest.supersedes_report_id == chain.oldest.id
    assert chain.newest_review.copied_from_editorial_review_id is None


def test_permanent_delete_route_enqueues_purge(
    safe_client, db_session, trashed_report
) -> None:
    response = safe_client.post(
        f"/daily-reports/{trashed_report.id}/purge",
        data=_token(safe_client),
        follow_redirects=False,
    )
    assert response.status_code == 303
    operation = db_session.scalar(
        select(OperationRunRecord)
        .where(OperationRunRecord.operation_type == OperationType.DAILY_REPORT_PURGE)
        .order_by(OperationRunRecord.id.desc())
    )
    assert operation is not None
    assert operation.requested_scope["daily_report_ids"] == [trashed_report.id]
```

- [ ] **Step 2: Run and observe missing operation failures**

Run: `uv run --extra dev pytest tests/daily_reports/test_purge_runtime.py tests/operations/test_commands.py -k "purge" -q`

Expected: FAIL because the operation type, command, and handler are absent.

- [ ] **Step 3: Add the bounded operation command**

Normalize positive unique IDs, require 1–20 IDs, verify each report is in trash and not active, then enqueue scope:

```python
{
    "schema_version": 1,
    "daily_report_ids": list(report_ids),
}
```

Do not store audio paths in operation scope. Paths are resolved from current trusted database records inside the handler.

- [ ] **Step 4: Implement safe idempotent file and row cleanup**

For each report independently: checkpoint; lock report; recheck eligibility; resolve each `relative_audio_path` under the configured audio root; reject any path outside root; unlink existing files; set matching autopilot `daily_report_id=None` and safe `result_summary["report_retention"]="purged"`. Before deleting, reparent any newer `DailyReportRecord.supersedes_report_id` to the deleted report’s own predecessor; set external decision/overview `copied_from_editorial_review_id` references to null; set external `duplicate_of_overview_item_id` references to null. Then delete the report and commit. Missing report/file is idempotent success. A failed report is recorded in structured per-member results and does not block the other IDs. Return `PARTIAL` when at least one succeeds and one fails.

- [ ] **Step 5: Register the handler and add permanent-delete Web control**

Register `DailyReportPurgeHandler` in the Worker router. Add `POST /daily-reports/{id}/purge`; it requires `require_safe_action`, validates the report is in trash and inactive, enqueues one bounded purge operation, and redirects to the trash page. Add a confirmation-protected form to the trash template. The POST returns before any file or database deletion runs.

- [ ] **Step 6: Run purge and Web tests**

Run: `uv run --extra dev pytest tests/daily_reports/test_purge_runtime.py tests/operations/test_commands.py tests/web/test_cli.py tests/web/test_daily_report_pages.py -k "purge or permanent_delete" -q`

Expected: PASS; router recognizes `daily_report_purge`.

- [ ] **Step 7: Commit durable purge**

```powershell
git add src/newsradar/daily_reports/purge_runtime.py src/newsradar/operations/schema.py src/newsradar/operations/commands.py src/newsradar/cli.py src/newsradar/web/app.py src/newsradar/web/templates/daily_report_trash.html tests/daily_reports/test_purge_runtime.py tests/operations/test_commands.py tests/web/test_cli.py tests/web/test_daily_report_pages.py
git commit -m "feat: purge expired daily reports safely"
```

### Task 9: Add Daily Retention Sweep Without Extra CPU Load

**Files:**
- Modify: `src/newsradar/daily_reports/automation_service.py`
- Modify: `src/newsradar/daily_reports/automation_repository.py`
- Modify: `src/newsradar/db/models.py`
- Modify: `migrations/versions/20260718_0029_daily_automation_retention.py`
- Modify: `tests/daily_reports/test_automation_service.py`
- Modify: `tests/daily_reports/test_automation_migration.py`

**Interfaces:**
- Produces: once-per-Shanghai-date retention sweep state `last_retention_date` on the singleton config.
- Consumes: Tasks 6 and 8.

- [ ] **Step 1: Extend failing tests for 90/30-day boundaries and batch limits**

```python
def test_retention_sweep_runs_once_and_enqueues_twenty(db_session) -> None:
    _seed_old_reports(db_session, count=25, age_days=91)
    service = _enabled_service(db_session, now=_shanghai_noon())
    first = service.tick()
    second = service.tick()
    assert first.trashed_count == 25
    purge_scope = _latest_purge_operation(db_session).requested_scope
    assert len(purge_scope["daily_report_ids"]) <= 20
    assert second.retention_outcome == "already_checked"


def test_pinned_and_eighty_nine_day_reports_are_preserved(db_session) -> None:
    pinned = _seed_report(db_session, age_days=200, pinned=True)
    recent = _seed_report(db_session, age_days=89, pinned=False)
    _enabled_service(db_session, now=_shanghai_noon()).tick()
    assert pinned.deleted_at is None
    assert recent.deleted_at is None
```

- [ ] **Step 2: Run and observe missing sweep state failure**

Run: `uv run --extra dev pytest tests/daily_reports/test_automation_service.py tests/daily_reports/test_automation_migration.py -k "retention" -q`

Expected: FAIL because `last_retention_date` and the sweep are absent.

- [ ] **Step 3: Add `last_retention_date` and one indexed daily sweep**

Add nullable `last_retention_date` to the config migration/model. Inside the same 60-second tick, acquire a distinct retention advisory lock. If today was not checked: move at most 50 oldest eligible reports to trash without deleting; select at most 20 `purge_after <= now` reports; enqueue one purge operation; set `last_retention_date=today`; commit. Do not loop another trash or purge batch in the same tick; any backlog waits for the next daily sweep.

- [ ] **Step 4: Run scheduling, retention, and migration tests**

Run: `uv run --extra dev pytest tests/daily_reports/test_automation_service.py tests/daily_reports/test_automation_repository.py tests/daily_reports/test_retention.py tests/daily_reports/test_automation_migration.py -q`

Expected: PASS; fake clock proves no extra polling loop.

- [ ] **Step 5: Commit automatic retention**

```powershell
git add src/newsradar/daily_reports/automation_service.py src/newsradar/daily_reports/automation_repository.py src/newsradar/db/models.py migrations/versions/20260718_0029_daily_automation_retention.py tests/daily_reports/test_automation_service.py tests/daily_reports/test_automation_migration.py
git commit -m "feat: sweep daily report retention once per day"
```

### Task 10: Preserve a Completed Report When One Audio Rendition Fails

**Files:**
- Modify: `src/newsradar/daily_reports/autopilot_runtime.py`
- Modify: `src/newsradar/web/daily_autopilot_queries.py`
- Modify: `src/newsradar/web/templates/daily_autopilot_detail.html`
- Modify: `tests/daily_reports/test_autopilot_runtime.py`
- Modify: `tests/web/test_daily_autopilot_pages.py`

**Interfaces:**
- Produces: terminal autopilot outcome `audio_partial` in `result_summary` while keeping `status="succeeded"` and the report link.
- Consumes: existing independent decision/overview audio operation IDs.

- [ ] **Step 1: Write failing partial-audio tests**

```python
def test_one_failed_audio_keeps_report_succeeded(runtime, seeded_run) -> None:
    _finish_audio(seeded_run.decision_audio_operation_id, status="succeeded")
    _finish_audio(seeded_run.overview_audio_operation_id, status="failed")
    runtime.handle(_wait_audio_lease(seeded_run.id), lambda _: None)
    run = _reload_run(seeded_run.id)
    assert run.status == "succeeded"
    assert run.result_summary["outcome"] == "audio_partial"
    assert run.daily_report_id is not None


def test_partial_audio_page_offers_only_failed_rendition_retry(client, seeded_run) -> None:
    response = client.get(f"/daily-autopilot/{seeded_run.id}")
    assert "日报内容已完成，情报全览语音失败" in response.text
    assert "重新生成全览版语音" in response.text
    assert "重新抓取" not in response.text
```

- [ ] **Step 2: Run and observe current whole-run failure**

Run: `uv run --extra dev pytest tests/daily_reports/test_autopilot_runtime.py tests/web/test_daily_autopilot_pages.py -k "audio_partial or failed_audio" -q`

Expected: FAIL because current wait logic marks the autopilot failed.

- [ ] **Step 3: Implement the terminal partial-audio summary**

When both audio operations are terminal and at least one succeeds, finish the autopilot with `status="succeeded"` and:

```python
{
    "outcome": "audio_partial",
    "daily_report_id": run.daily_report_id,
    "decision_audio_status": decision.status,
    "overview_audio_status": overview.status,
}
```

When both fail, keep a failed autopilot with the existing bounded Chinese error. Existing per-rendition audio POST routes perform retry without regenerating the report.

- [ ] **Step 4: Run runtime and Web tests**

Run: `uv run --extra dev pytest tests/daily_reports/test_autopilot_runtime.py tests/web/test_daily_autopilot_pages.py tests/web/test_daily_report_pages.py -q`

Expected: PASS.

- [ ] **Step 5: Commit partial-audio recovery**

```powershell
git add src/newsradar/daily_reports/autopilot_runtime.py src/newsradar/web/daily_autopilot_queries.py src/newsradar/web/templates/daily_autopilot_detail.html tests/daily_reports/test_autopilot_runtime.py tests/web/test_daily_autopilot_pages.py
git commit -m "fix: preserve reports across partial audio failure"
```

### Task 11: Full Verification and Real Web Acceptance

**Files:**
- Modify only if a verification failure requires a scoped fix.

**Interfaces:**
- Consumes every previous task.
- Produces a merge-ready branch with automation still paused by default.

- [ ] **Step 1: Run focused milestone suites**

Run:

```powershell
uv run --extra dev pytest tests/daily_reports/test_automation.py tests/daily_reports/test_automation_repository.py tests/daily_reports/test_automation_service.py tests/daily_reports/test_retention.py tests/daily_reports/test_purge_runtime.py tests/daily_reports/test_autopilot_runtime.py tests/operations/test_commands.py tests/web/test_daily_automation_pages.py tests/web/test_daily_report_pages.py tests/web/test_daily_autopilot_pages.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the complete project gate**

Run:

```powershell
uv run --extra dev --extra research pytest -q
uv run --extra dev ruff check .
git diff --check
```

Expected: all commands exit 0; only existing dependency deprecation warnings and environment skips remain.

- [ ] **Step 3: Perform migration acceptance on a disposable database**

Run Alembic upgrade to `head`, inspect `daily_automation_config` and retention indexes, then downgrade one revision and upgrade again. Confirm a fresh config is absent until first read and is created with `enabled=false`. Never point this acceptance at the user’s production database.

- [ ] **Step 4: Perform real Web acceptance with synthetic records**

Start the feature branch Web service on a separate local port and use a disposable database. Verify: paused console; enable/pause; next 07:30 time; run-now enqueues but does not execute network work without a Worker; pin; trash; restore; bulk limit; trash body isolation; permanent purge removes only synthetic MP3/report rows.

- [ ] **Step 5: Observe idle Worker performance**

Run a Worker against the disposable empty queue for five minutes. Record schedule-query timestamps and process CPU time before/after. Acceptance requires no more than six schedule checks in five minutes, no additional network threads, and no sustained full-core CPU use. Stop the disposable Worker after observation.

- [ ] **Step 6: Verify production-safe defaults and repository scope**

Confirm `DailyAutomationConfigRecord.enabled` defaults false, no real report has changed, `.env` and `reports/` are absent from `git diff --name-only`, and no service was pushed or merged.

- [ ] **Step 7: Handle any verification failure through its owning task**

If verification exposes a defect, return to the task that owns the affected interface, add one reproducing failing test, apply the minimal fix, rerun that task’s exact gate, and use that task’s exact `git add` list with commit message `test: close daily automation acceptance`. If no fix is needed, do not create an empty commit.
