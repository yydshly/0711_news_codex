# 每日全自动日报 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以一次网页操作创建可恢复的自动日报任务，完成新来源刷新、事件构建、自动中文审核、归档以及决策版和全览版音频。

**Architecture:** 使用 `DailyAutopilotRunRecord` 作为用户可见的总任务。每个 `daily_autopilot` 操作只推进一个阶段，然后创建既有子操作和一个 15 秒后可领取的续跑操作；因此单 Worker 也不会被“等待子任务”阻塞。

**Tech Stack:** Python 3.12、SQLAlchemy、Alembic、FastAPI/Jinja、现有 OperationRepository/Worker、pytest、ruff。

## Global Constraints

- 不扩充来源、不绕过登录、反爬或验证码；只对现有合规来源执行刷新。
- 网页只入队；网络抓取、模型调用和音频合成只由 Worker 执行。
- 单来源失败允许来源刷新以 `partial` 继续；缺少完整事件快照、归档或音频失败才使总任务失败。
- 规则审核必须独立完成；MiniMax 只增强文案，不能决定来源合法性或启用状态。
- 自动审核内容沿用现有 schema 与文本完整性校验；疑似编码损坏禁止归档和音频。
- 不读取、输出、暂存或提交 `.env` 与用户报告。
- 每个任务先写失败测试，再写最小实现并提交。

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `src/newsradar/db/models.py` | `DailyAutopilotRunRecord`。 |
| `migrations/versions/20260718_0028_daily_autopilot.py` | 自动日报任务表与约束。 |
| `src/newsradar/daily_reports/autopilot.py` | 阶段枚举、规则中文审核草稿。 |
| `src/newsradar/daily_reports/autopilot_repository.py` | 任务加锁、阶段转换、子操作关联。 |
| `src/newsradar/daily_reports/autopilot_runtime.py` | 单 Worker 安全的短续跑处理器。 |
| `src/newsradar/operations/{schema,repository,commands}.py` | 新操作类型、延迟入队、创建/取消命令。 |
| `src/newsradar/web/daily_autopilot_queries.py` | 任务列表/详情中文视图。 |
| `src/newsradar/web/app.py` 与模板 | 入队、详情、取消和任务页面。 |

## 阶段与接口

```python
class DailyAutopilotStage(StrEnum):
    ENQUEUE_SOURCE_REFRESH = "enqueue_source_refresh"
    WAIT_SOURCE_REFRESH = "wait_source_refresh"
    ENQUEUE_EVENT_PIPELINE = "enqueue_event_pipeline"
    WAIT_EVENT_PIPELINE = "wait_event_pipeline"
    GENERATE_REPORT = "generate_report"
    WRITE_REVIEWS = "write_reviews"
    ARCHIVE_AND_ENQUEUE_AUDIO = "archive_and_enqueue_audio"
    WAIT_AUDIO = "wait_audio"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

所有续跑操作 scope 固定为：

```python
{"daily_autopilot_run_id": run_id, "stage": stage.value}
```

等待阶段发现子操作仍为 `queued` 或 `running` 时，创建一个 15 秒后才可领取的新续跑操作并成功结束自己；绝不使用操作重试来轮询，避免耗尽三次重试预算。

### Task 1: 持久化总任务与迁移

**Files:**
- Modify: `src/newsradar/db/models.py:437-465`
- Create: `migrations/versions/20260718_0028_daily_autopilot.py`
- Create: `src/newsradar/daily_reports/autopilot_repository.py`
- Test: `tests/daily_reports/test_autopilot_repository.py`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Produces `DailyAutopilotRepository.create_run(window_hours: int, trigger: str) -> DailyAutopilotRunRecord`.
- Produces `DailyAutopilotRepository.transition(run_id: int, *, stage: DailyAutopilotStage, status: str | None = None, **ids: int | None) -> DailyAutopilotRunRecord`.

- [ ] **Step 1: 写失败测试**

```python
def test_autopilot_run_persists_stage_and_linked_operation(db_session: Session) -> None:
    run = DailyAutopilotRepository(db_session).create_run(window_hours=24, trigger="web")
    saved = DailyAutopilotRepository(db_session).transition(
        run.id,
        stage=DailyAutopilotStage.WAIT_SOURCE_REFRESH,
        source_operation_id=41,
    )
    assert saved.status == "running"
    assert saved.stage == "wait_source_refresh"
    assert saved.source_operation_id == 41
```

Run: `pytest tests/daily_reports/test_autopilot_repository.py -q`

Expected: FAIL because the model and repository do not exist.

- [ ] **Step 2: 添加模型与 Alembic 迁移**

```python
class DailyAutopilotRunRecord(Base):
    __tablename__ = "daily_autopilot_runs"
    __table_args__ = (
        CheckConstraint("window_hours IN (24, 48, 72)", name="ck_daily_autopilot_window"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_daily_autopilot_status",
        ),
        Index("ix_daily_autopilot_runs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(48), nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    source_operation_id: Mapped[int | None] = mapped_column(ForeignKey("operation_runs.id"))
    event_operation_id: Mapped[int | None] = mapped_column(ForeignKey("operation_runs.id"))
    decision_audio_operation_id: Mapped[int | None] = mapped_column(ForeignKey("operation_runs.id"))
    overview_audio_operation_id: Mapped[int | None] = mapped_column(ForeignKey("operation_runs.id"))
    daily_report_id: Mapped[int | None] = mapped_column(ForeignKey("daily_reports.id"))
    result_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(96))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

The migration creates this table, all five foreign-key indexes, and only these two check constraints; downgrade drops only this table.

- [ ] **Step 3: 实现加锁仓储与活跃任务约束**

```python
def get_for_update(self, run_id: int) -> DailyAutopilotRunRecord:
    run = self.session.get(DailyAutopilotRunRecord, run_id, with_for_update=True)
    if run is None:
        raise LookupError("daily_autopilot_not_found")
    return run

def fail(self, run_id: int, code: str, message: str) -> DailyAutopilotRunRecord:
    run = self.get_for_update(run_id)
    run.status, run.stage = "failed", DailyAutopilotStage.FAILED.value
    run.error_code, run.error_message, run.finished_at = code, message, self._utcnow()
    self.session.flush()
    return run
```

`create_run` rejects a second queued/running run with `ValueError("active_daily_autopilot_exists")`; PostgreSQL uses an advisory transaction lock, matching catalog refresh.

- [ ] **Step 4: 验证并提交**

Run: `pytest tests/daily_reports/test_autopilot_repository.py tests/test_migrations.py -q`

Expected: PASS.

```bash
git add src/newsradar/db/models.py migrations/versions/20260718_0028_daily_autopilot.py src/newsradar/daily_reports/autopilot_repository.py tests/daily_reports/test_autopilot_repository.py tests/test_migrations.py
git commit -m "feat: persist daily autopilot runs"
```

### Task 2: 规则审核、延迟续跑与入队命令

**Files:**
- Create: `src/newsradar/daily_reports/autopilot.py`
- Modify: `src/newsradar/operations/schema.py`
- Modify: `src/newsradar/operations/repository.py:50-70`
- Modify: `src/newsradar/operations/commands.py`
- Test: `tests/daily_reports/test_autopilot.py`
- Test: `tests/operations/test_commands.py`

**Interfaces:**
- Produces `build_decision_review(snapshot: dict[str, object]) -> DailyReportEditorialReviewDraft`.
- Produces `build_overview_review(snapshot: dict[str, object]) -> DailyReportOverviewEditorialReviewDraft`.
- Produces `OperationCommandService.enqueue_daily_autopilot(plan: CatalogRefreshPlan, *, window_hours: int, trigger: str) -> int`.
- Produces `OperationCommandService.enqueue_daily_autopilot_continuation(run_id: int, stage: DailyAutopilotStage, *, not_before: datetime) -> int`.

- [ ] **Step 1: 写失败测试**

```python
def test_rule_review_marks_single_root_signal_as_needing_evidence() -> None:
    review = build_overview_review({
        "zh_title": "新信号",
        "zh_summary": "公开材料尚不足以确认。",
        "independent_root_count": 1,
        "status": "emerging",
    })
    assert review.decision == "needs_evidence"
    assert "仍需" in review.evidence_assessment

def test_continuation_is_not_leasable_before_not_before(db_session: Session) -> None:
    commands.enqueue_daily_autopilot_continuation(
        run_id=7,
        stage=DailyAutopilotStage.WAIT_SOURCE_REFRESH,
        not_before=NOW + timedelta(seconds=15),
    )
    assert OperationRepository(db_session).lease_next("worker") is None
```

Run: `pytest tests/daily_reports/test_autopilot.py tests/operations/test_commands.py -q`

Expected: FAIL because the APIs are absent.

- [ ] **Step 2: 实现规则草稿与操作类型**

```python
def _review_values(snapshot: dict[str, object]) -> tuple[str, str, str, str]:
    title = _text(snapshot, "zh_title", "未命名事件")
    summary = _text(snapshot, "zh_summary", "当前公开材料不足以形成完整中文概述。")
    roots = _integer(snapshot, "independent_root_count")
    if _text(snapshot, "status", "emerging") == "confirmed" or roots >= 2:
        return title, summary, "建议持续跟踪后续影响与执行细节。", "现有公开证据可支持当前判断。"
    return title, summary, "建议保留为待补证信号，关注新增独立公开来源。", "当前独立证据根不足，仍需补充确认。"
```

`build_decision_review` 和 `build_overview_review` 均用现有 draft 的 `.create(...)` 校验。自动规则不把 `emerging` 改成已确认，也不生成重复关联。

Add `OperationType.DAILY_AUTOPILOT = "daily_autopilot"`. Add `not_before: datetime | None = None` to `OperationRepository.enqueue` and persist `record.next_attempt_at = not_before or func.now()`.

- [ ] **Step 3: 实现命令边界**

```python
def enqueue_daily_autopilot(
    self, plan: CatalogRefreshPlan, *, window_hours: int, trigger: str
) -> int:
    run = DailyAutopilotRepository(self.session, utcnow=self._utcnow).create_run(
        window_hours=window_hours, trigger=trigger
    )
    operation = OperationRepository(self.session).enqueue(
        OperationType.DAILY_AUTOPILOT,
        {"daily_autopilot_run_id": run.id,
         "stage": DailyAutopilotStage.ENQUEUE_SOURCE_REFRESH.value,
         "catalog_plan": serialize_catalog_plan(plan)},
        trigger=trigger,
        in_transaction=True,
    )
    self.session.commit()
    return operation.id
```

Continuation operations carry no plan and have a future `next_attempt_at`; every stage creates at most one child ID and at most one next continuation after locking the run.

- [ ] **Step 4: 验证并提交**

Run: `pytest tests/daily_reports/test_autopilot.py tests/operations/test_commands.py tests/operations/test_repository.py -q`

Expected: PASS.

```bash
git add src/newsradar/daily_reports/autopilot.py src/newsradar/operations/schema.py src/newsradar/operations/repository.py src/newsradar/operations/commands.py tests/daily_reports/test_autopilot.py tests/operations/test_commands.py
git commit -m "feat: queue daily autopilot continuations"
```

### Task 3: 单 Worker 安全的阶段运行时

**Files:**
- Create: `src/newsradar/daily_reports/autopilot_runtime.py`
- Modify: `src/newsradar/cli.py:637-655`
- Test: `tests/daily_reports/test_autopilot_runtime.py`

**Interfaces:**
- Produces `DailyAutopilotHandler.production(sources, providers, create_session) -> DailyAutopilotHandler`.
- Consumes a `daily_autopilot` lease and produces `OperationResult`.

- [ ] **Step 1: 写失败的顺序测试**

```python
def test_source_stage_enqueues_refresh_and_delayed_wait(db_session: Session) -> None:
    result = handler(autopilot_lease(run.id, "enqueue_source_refresh"), checkpoint)
    saved = DailyAutopilotRepository(db_session).get(run.id)
    assert result.status is OperationStatus.SUCCEEDED
    assert saved.source_operation_id is not None
    assert saved.stage == "wait_source_refresh"

def test_wait_stage_accepts_partial_sources_then_enqueues_events(db_session: Session) -> None:
    finish_operation(run.source_operation_id, status="partial")
    handler(autopilot_lease(run.id, "wait_source_refresh"), checkpoint)
    assert DailyAutopilotRepository(db_session).get(run.id).event_operation_id is not None
```

Run: `pytest tests/daily_reports/test_autopilot_runtime.py -q`

Expected: FAIL because the handler is absent.

- [ ] **Step 2: 分派、幂等与等待阶段**

```python
def __call__(self, lease: OperationLease, checkpoint: Callable[[str], None]) -> OperationResult:
    if lease.operation_type != OperationType.DAILY_AUTOPILOT.value:
        return self._failed("unsupported_operation_type", "不支持的自动日报任务类型。")
    run_id = lease.requested_scope.get("daily_autopilot_run_id")
    stage = DailyAutopilotStage(lease.requested_scope.get("stage", ""))
    if not isinstance(run_id, int) or run_id <= 0:
        return self._failed("invalid_daily_autopilot_scope", "自动日报任务参数无效。")
    checkpoint(f"daily_autopilot:{stage.value}")
    return self._advance(run_id, stage, checkpoint)
```

A terminal run returns immediately. A leased stage older than the persisted stage returns `{"idempotent": True}`. A running child queues exactly one later continuation; no handler waits or sleeps.

- [ ] **Step 3: 实现来源、事件、日报与审核阶段**

```python
def _write_reviews(self, run: DailyAutopilotRunRecord) -> OperationResult:
    repository = DailyReportRepository(self._session)
    for item in repository.items(run.daily_report_id):
        repository.save_editorial_review(
            run.daily_report_id, item.id, build_decision_review(item.snapshot)
        )
    for item in repository.overview_items(run.daily_report_id):
        repository.save_overview_editorial_review(
            run.daily_report_id, item.id, build_overview_review(item.snapshot)
        )
    self._runs.transition(run.id, stage=DailyAutopilotStage.ARCHIVE_AND_ENQUEUE_AUDIO)
    return OperationResult(result_summary={"reviewed": True}, retryable=False)
```

The source stage calls existing `enqueue_source_catalog_refresh`; its wait accepts `succeeded` and `partial`. The event stage calls existing `enqueue_event_pipeline`; its wait requires `succeeded`. The report stage calls `DailyReportService.generate(run.window_hours)`. All terminal child failures call repository `.fail(...)` with the stored Chinese message or a fixed Chinese fallback.

- [ ] **Step 4: 实现归档与双音频阶段**

Use existing `archive_and_enqueue_daily_report_audio` for decision audio, then `enqueue_daily_report_audio(..., rendition="overview")`. Store both IDs and queue `WAIT_AUDIO`. Succeed only when both children succeed; any failed audio fails the total task with its error. Catch the existing text-integrity and overview-readiness `ValueError` values and return non-retryable Chinese diagnostics.

- [ ] **Step 5: 注册、验证并提交**

```python
"daily_autopilot": DailyAutopilotHandler.production(sources, providers, create_session),
```

Add tests for cancellation, recovery after an older duplicated lease, MiniMax-independent review, corrupted text blocking audio, and a failed audio child.

Run: `pytest tests/daily_reports/test_autopilot_runtime.py tests/daily_reports/test_audio_runtime.py tests/operations/test_worker.py -q`

Expected: PASS.

```bash
git add src/newsradar/daily_reports/autopilot_runtime.py src/newsradar/cli.py tests/daily_reports/test_autopilot_runtime.py
git commit -m "feat: orchestrate daily autopilot stages"
```

### Task 4: 自动日报网页与中文诊断

**Files:**
- Create: `src/newsradar/web/daily_autopilot_queries.py`
- Modify: `src/newsradar/web/app.py:590-633`
- Modify: `src/newsradar/web/templates/daily_reports.html`
- Create: `src/newsradar/web/templates/daily_autopilot_detail.html`
- Modify: `src/newsradar/web/static/styles.css`
- Test: `tests/web/test_daily_autopilot_pages.py`

**Interfaces:**
- Produces `DailyAutopilotQueryService.list_recent(limit: int = 10) -> tuple[DailyAutopilotSummaryView, ...]`.
- Adds `POST /daily-reports/autopilot`, `GET /daily-autopilot/{run_id}`, `POST /daily-autopilot/{run_id}/cancel`.

- [ ] **Step 1: 写失败页面测试**

```python
def test_autopilot_post_queues_then_redirects_to_task_page(client: TestClient) -> None:
    response = client.post("/daily-reports/autopilot", data={"action_token": token}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/daily-autopilot/")

def test_task_page_shows_child_links_and_chinese_partial_reason(client: TestClient) -> None:
    response = client.get(f"/daily-autopilot/{run_id}")
    assert "来源刷新" in response.text
    assert f"/operations/{source_operation_id}" in response.text
    assert "部分来源未成功" in response.text
```

Run: `pytest tests/web/test_daily_autopilot_pages.py -q`

Expected: FAIL with 404.

- [ ] **Step 2: 实现查询和路由**

```python
@app.post("/daily-reports/autopilot")
async def enqueue_daily_autopilot(request: Request) -> RedirectResponse:
    await require_safe_action(request)
    with create_session() as session:
        operation_id = OperationCommandService(session).enqueue_daily_autopilot(
            _daily_autopilot_catalog_plan(), window_hours=24, trigger="web"
        )
        run_id = DailyAutopilotRepository(session).run_id_for_initial_operation(operation_id)
    return RedirectResponse(f"/daily-autopilot/{run_id}", status_code=303)
```

`_daily_autopilot_catalog_plan()` calls existing `load_source_tree`, `load_provider_tree`, `SettingsCredentials().configured_names()` and `build_catalog_refresh_plan`; it must not read or display environment values. The cancel route cancels active linked operations and the run, then redirects to its detail page.

- [ ] **Step 3: 实现页面和响应式样式**

The list page adds an explicit “生成今日自动日报” panel. The task page renders fixed Chinese stage labels, child-operation links, source success/skip/fail metrics, fixed Chinese error, report link and two audio states. Reuse `.status-*`, `.metric-note`, `.table-wrap` and `overflow-wrap:anywhere`; do not redesign the daily report detail page.

- [ ] **Step 4: 验证并提交**

Run: `pytest tests/web/test_daily_autopilot_pages.py tests/web/test_daily_report_pages.py -q`

Expected: PASS.

```bash
git add src/newsradar/web/daily_autopilot_queries.py src/newsradar/web/app.py src/newsradar/web/templates/daily_reports.html src/newsradar/web/templates/daily_autopilot_detail.html src/newsradar/web/static/styles.css tests/web/test_daily_autopilot_pages.py
git commit -m "feat: show daily autopilot progress"
```

### Task 5: 端到端测试与真实验收

**Files:**
- Modify: `tests/daily_reports/test_autopilot_runtime.py`
- Modify: `tests/web/test_daily_autopilot_pages.py`

- [ ] **Step 1: 写端到端失败测试**

```python
def test_autopilot_moves_from_partial_sources_to_archived_report_with_two_audios(
    db_session: Session,
) -> None:
    run_id = enqueue_autopilot_with_fake_catalog(db_session)
    drain_worker_until_terminal(db_session, run_id, source_status="partial")
    run = DailyAutopilotRepository(db_session).get(run_id)
    assert run.status == "succeeded"
    assert run.daily_report_id is not None
    assert run.decision_audio_operation_id is not None
    assert run.overview_audio_operation_id is not None
```

Run: `pytest tests/daily_reports/test_autopilot_runtime.py -k terminal -q`

Expected: FAIL until the complete chain is present.

- [ ] **Step 2: 使用无网络、无密钥夹具完成链路**

Use fake catalog and speech handlers through `OperationRouter`. Mark one catalog member failed and the remainder succeeded; the run must still produce an archived report. Assert both audio artifacts are non-empty and neither fixture nor result contains credentials.

- [ ] **Step 3: 完整验证**

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
..\\..\\.venv\\Scripts\\python.exe -m pytest -q
..\\..\\.venv\\Scripts\\python.exe -m ruff check .
git diff --check
```

Expected: all tests pass, ruff prints `All checks passed!`, and `git diff --check` has no output.

- [ ] **Step 4: 真实网页验收与提交**

Start the local service with this worktree’s `src` on `PYTHONPATH`. Submit the automatic action and verify immediate task-page redirect, Chinese stage diagnostics, final report anchors, two `<audio>` elements, and no desktop or 375px horizontal overflow.

```bash
git add tests/daily_reports/test_autopilot_runtime.py tests/web/test_daily_autopilot_pages.py
git commit -m "test: cover daily autopilot end to end"
```

## Plan Self-Review

- Spec coverage: Tasks 1-3 cover durable state, single-Worker-safe progression, compliant refresh, event/report/review/archive/audio chain, cancellation and recovery. Task 4 covers the entry, progress and Chinese diagnostics. Task 5 covers partial-source completion, full regression and real-page acceptance.
- 占位检查：没有未定义接口或延后内容。
- Type consistency: all continuations use `daily_autopilot_run_id` and `DailyAutopilotStage`; child IDs are stored on `DailyAutopilotRunRecord`; templates use query views rather than raw operation scope.
