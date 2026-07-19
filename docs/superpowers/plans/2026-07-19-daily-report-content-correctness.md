# Daily Report Content Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every daily overview retain the complete same-day cumulative event set while keeping the decision brief as a ranked subset, preserving immutable revisions, and preventing automatic overview-audio cost growth.

**Architecture:** Materialize every operation event into immutable overview drafts, merge them with the latest archived report for the same Shanghai calendar date through a new pure accumulation module, then derive decision items from the accumulated drafts. Reuse the existing report/revision tables and JSON snapshots; no migration is required. Existing archived reports remain immutable, matching editorial reviews are copied by event/version identity, and only decision audio is automatically enqueued.

**Tech Stack:** Python 3.12, SQLAlchemy 2, FastAPI/Jinja2, pytest, Ruff, existing News Codex operation queue.

## Global Constraints

- Do not reinitialize the project or database.
- Do not read, stage, modify, or commit `.env` or user-retained files under `reports/`.
- Use the existing provider, event snapshot, report, revision, worker, cancellation, retry, logging, and web-page architecture.
- A single event failure must not block the report batch.
- MiniMax may improve Chinese wording only; it must not determine source legality, event confirmation, or enablement.
- Do not add a database migration for this milestone.
- Do not automatically enqueue overview audio; it remains available through the existing explicit web action.
- Development tests must not call real networks or MiniMax.
- Run targeted tests during implementation; run full pytest, Ruff, migration-head check, and one real web acceptance only at the milestone end.
- Stop and report the exact blocker if the milestone has no verifiable result after 90 minutes; do not stack speculative fixes.

---

## File Responsibility Map

- Create `src/newsradar/daily_reports/accumulation.py`: pure same-day overview merge, disposition metadata, deterministic statistics.
- Modify `src/newsradar/daily_reports/service.py`: materialize all snapshot events, derive decisions from accumulated overview drafts, integrate the prior report and revision-safe union.
- Modify `src/newsradar/daily_reports/repository.py`: select the latest archived same-day baseline, expose prior review decisions and applied event-merge identities, create one successor draft, copy matching reviews safely.
- Modify `src/newsradar/daily_reports/autopilot_runtime.py`: archive and enqueue only decision audio, wait only for that task.
- Modify `src/newsradar/web/daily_report_queries.py`: expose cumulative counters and per-item decision omission diagnostics.
- Modify `src/newsradar/web/templates/daily_report_detail.html`: show total/decision/omitted counts and Chinese omission reasons.
- Create `tests/daily_reports/test_accumulation.py`: pure merge and non-shrink regression tests.
- Modify `tests/daily_reports/test_service.py`: exact `8 -> 2/8`, same-day `+4 with 1 duplicate -> 11`, revision, review-copy, and failure tests.
- Modify `tests/daily_reports/test_autopilot_runtime.py`: decision-only automatic audio tests.
- Modify `tests/web/test_daily_report_pages.py`: visible cumulative counters and reasons.

---

### Task 1: Persist Every Snapshot Event in the Overview

**Files:**
- Modify: `src/newsradar/daily_reports/service.py:117-128,414-486`
- Test: `tests/daily_reports/test_service.py:30-230,359-399`

**Interfaces:**
- Consumes: `EventQueryService._operation_rows(snapshot)` in its existing stable score/time/event order.
- Produces: `_overview_drafts(snapshot, checked_at)` containing every materializable operation event, including `audit_only` and degraded items.

- [ ] **Step 1: Write the failing eight-event acceptance test**

Extend the snapshot seeder with an `audit_only` tuple and create an exact test:

```python
def test_generate_keeps_all_eight_events_in_overview_but_only_two_in_decision(
    db_session: Session,
) -> None:
    operation_id = seed_complete_snapshot(
        db_session,
        confirmed=(),
        emerging=(201, 202),
        audit_only=(301, 302, 303, 304, 305, 306),
    )

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate_from_operation(
        operation_id, 24, now=NOW
    )
    repository = DailyReportRepository(db_session)

    assert len(repository.items(report.id)) == 2
    assert len(repository.overview_items(report.id)) == 8
    assert report.generation_summary["decision_count"] == 2
    assert report.generation_summary["overview_count"] == 8
    assert report.generation_summary["omitted_from_decision_count"] == 6
```

Ensure all eight seeded events have valid `occurred_at` values inside the 24-hour window so the test isolates display-tier filtering.

- [ ] **Step 2: Run the focused test and verify the current regression**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_service.py::test_generate_keeps_all_eight_events_in_overview_but_only_two_in_decision -q
```

Expected: FAIL because only the two `signal` events are persisted in the overview.

- [ ] **Step 3: Remove only the overview admission filter and add counters**

Delete this condition from `_overview_drafts`:

```python
if row.status != "confirmed" and row.display_tier not in {"hotspot", "signal"}:
    continue
```

Keep `_selected_rows` unchanged for now, and add these deterministic summary fields when creating `DailyReportDraft`:

```python
"decision_count": len(drafts),
"overview_count": len(overview_drafts),
"omitted_from_decision_count": len(overview_drafts) - len(decision_event_ids),
```

Do not remove degraded overview items when detail materialization fails.

- [ ] **Step 4: Run the focused overview tests**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_service.py -k "eight_events or persists_every or keeps_invalid" -q
```

Expected: PASS; update existing exact event-ID expectations so `audit_only` events are now present.

- [ ] **Step 5: Commit the complete-overview invariant**

```powershell
git add src/newsradar/daily_reports/service.py tests/daily_reports/test_service.py
git commit -m "fix: retain every event in daily overview"
```

---

### Task 2: Add a Pure Same-Day Accumulation Engine

**Files:**
- Create: `src/newsradar/daily_reports/accumulation.py`
- Create: `tests/daily_reports/test_accumulation.py`

**Interfaces:**
- Consumes: previous and current `tuple[DailyReportOverviewItemDraft, ...]`, `canonical_event_ids: Mapping[int, int]`, and prior `EditorialDecision` values keyed by `(event_id, event_version_number)`.
- Produces: `DailyOverviewAccumulation` with ordered drafts and exact inherited/new/updated/deduplicated/invalidated counts.

- [ ] **Step 1: Write pure failing tests for union, update, duplicate, and invalidation**

Create helpers that build minimal valid snapshots and assert the core examples:

```python
def test_accumulate_adds_three_unique_events_from_four_current_candidates() -> None:
    previous = tuple(_draft(event_id) for event_id in range(1, 9))
    current = tuple(_draft(event_id) for event_id in (8, 9, 10, 11))

    result = accumulate_daily_overview(
        previous,
        current,
        canonical_event_ids={8: 8, 9: 9, 10: 10, 11: 11},
        previous_decisions={},
    )

    assert [item.event_id for item in result.items] == list(range(1, 12))
    assert result.stats.inherited_count == 8
    assert result.stats.new_count == 3
    assert result.stats.updated_count == 1


def test_accumulate_does_not_add_a_new_applied_duplicate() -> None:
    previous = (_draft(1),)
    current = (_draft(1), _draft(12))

    result = accumulate_daily_overview(
        previous,
        current,
        canonical_event_ids={1: 1, 12: 1},
        previous_decisions={},
    )

    assert [item.event_id for item in result.items] == [1]
    assert result.stats.deduplicated_count == 1


def test_accumulate_preserves_previously_visible_duplicate_as_audit_record() -> None:
    previous = (_draft(1), _draft(12))

    result = accumulate_daily_overview(
        previous,
        (_draft(1, version=2),),
        canonical_event_ids={1: 1, 12: 1},
        previous_decisions={(12, 1): EditorialDecision.DUPLICATE},
    )

    assert len(result.items) == 2
    duplicate = next(item for item in result.items if item.event_id == 12)
    assert duplicate.snapshot["daily_disposition"]["reason_code"] == "duplicate_confirmed"
```

- [ ] **Step 2: Run the new test module and verify import failure**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_accumulation.py -q
```

Expected: FAIL because `newsradar.daily_reports.accumulation` does not exist.

- [ ] **Step 3: Implement the pure accumulation types and function**

Create these public types and function:

```python
@dataclass(frozen=True, slots=True)
class DailyOverviewAccumulationStats:
    inherited_count: int
    new_count: int
    updated_count: int
    deduplicated_count: int
    invalidated_count: int


@dataclass(frozen=True, slots=True)
class DailyOverviewAccumulation:
    items: tuple[DailyReportOverviewItemDraft, ...]
    stats: DailyOverviewAccumulationStats


def accumulate_daily_overview(
    previous: tuple[DailyReportOverviewItemDraft, ...],
    current: tuple[DailyReportOverviewItemDraft, ...],
    *,
    canonical_event_ids: Mapping[int, int],
    previous_decisions: Mapping[tuple[int, int], EditorialDecision],
) -> DailyOverviewAccumulation:
    previous_rows = [
        replace(item, snapshot=deepcopy(item.snapshot)) for item in previous
    ]
    rows = list(previous_rows)
    index_by_event = {item.event_id: index for index, item in enumerate(rows)}
    index_by_canonical = {
        canonical_event_ids.get(item.event_id, item.event_id): index
        for index, item in enumerate(rows)
    }
    updated_count = 0
    new_count = 0
    deduplicated_count = 0
    invalidated_count = 0

    for index, item in enumerate(tuple(rows)):
        decision = previous_decisions.get(
            (item.event_id, item.event_version_number)
        )
        canonical_id = canonical_event_ids.get(item.event_id, item.event_id)
        if decision is EditorialDecision.EXCLUDE:
            rows[index] = _with_disposition(
                item,
                status="invalidated",
                reason_code="invalidated_by_new_evidence",
                reason_zh="该条目已被后续审核排除，保留用于审计，不进入决策版或语音。",
                canonical_event_id=canonical_id,
            )
            invalidated_count += 1
        elif decision is EditorialDecision.DUPLICATE:
            rows[index] = _with_disposition(
                item,
                status="excluded",
                reason_code="duplicate_confirmed",
                reason_zh="该条目已确认与另一事件重复，保留用于审计，不进入决策版或语音。",
                canonical_event_id=canonical_id,
            )

    for item in current:
        canonical_id = canonical_event_ids.get(item.event_id, item.event_id)
        exact_index = index_by_event.get(item.event_id)
        if exact_index is not None:
            previous_item = rows[exact_index]
            current_is_degraded = "display_degradation_reason" in item.snapshot
            previous_is_degraded = "display_degradation_reason" in previous_item.snapshot
            if item.event_version_number >= previous_item.event_version_number and (
                not current_is_degraded or previous_is_degraded
            ):
                rows[exact_index] = replace(item, snapshot=deepcopy(item.snapshot))
            updated_count += 1
            continue
        canonical_index = index_by_canonical.get(canonical_id)
        if canonical_index is not None:
            rows[canonical_index] = _merge_item_evidence(rows[canonical_index], item)
            deduplicated_count += 1
            continue
        rows.append(replace(item, snapshot=deepcopy(item.snapshot)))
        index_by_event[item.event_id] = len(rows) - 1
        index_by_canonical[canonical_id] = len(rows) - 1
        new_count += 1

    represented = set(index_by_canonical)
    for index, item in enumerate(tuple(rows)):
        canonical_id = canonical_event_ids.get(item.event_id, item.event_id)
        if canonical_id != item.event_id and canonical_id in represented:
            rows[index] = _with_disposition(
                rows[index],
                status="excluded",
                reason_code="duplicate_confirmed",
                reason_zh="该条目已确认与另一事件重复，保留用于审计，不进入决策版或语音。",
                canonical_event_id=canonical_id,
            )

    positioned = tuple(
        replace(item, position=position)
        for position, item in enumerate(rows, start=1)
    )
    return DailyOverviewAccumulation(
        items=positioned,
        stats=DailyOverviewAccumulationStats(
            inherited_count=len(previous),
            new_count=new_count,
            updated_count=updated_count,
            deduplicated_count=deduplicated_count,
            invalidated_count=invalidated_count,
        ),
    )
```

Define `_with_disposition` with `dataclasses.replace` and a deep-copied snapshot. Define `_merge_item_evidence` to append only evidence dictionaries whose `(url, title, published_at)` tuple is not already present, while retaining the survivor item’s identity and snapshot fields.

Implement the body with these exact rules:

1. Preserve previous order and audit records.
2. Replace an existing event only when the current version number is greater or equal; never replace a complete snapshot with one containing `display_degradation_reason`.
3. Append a genuinely new canonical event.
4. Do not append a newly observed event whose applied canonical survivor is already represented.
5. Preserve a previously represented duplicate, but attach:

```python
{
    "status": "excluded",
    "reason_code": "duplicate_confirmed",
    "reason_zh": "该条目已确认与另一事件重复，保留用于审计，不进入决策版或语音。",
    "canonical_event_id": survivor_event_id,
}
```

6. Convert prior `EXCLUDE` reviews to `invalidated_by_new_evidence` disposition and prior `DUPLICATE` reviews to `duplicate_confirmed` disposition.
7. Reassign positions consecutively after merging.
8. Copy snapshot dictionaries before adding metadata; never mutate archived input snapshots.

- [ ] **Step 4: Run accumulation tests and Ruff for the new module**

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_accumulation.py -q
D:\codex_project_work\news_codex\.venv\Scripts\ruff.exe check src/newsradar/daily_reports/accumulation.py tests/daily_reports/test_accumulation.py
```

Expected: both commands pass.

- [ ] **Step 5: Commit the pure merge engine**

```powershell
git add src/newsradar/daily_reports/accumulation.py tests/daily_reports/test_accumulation.py
git commit -m "feat: add daily overview accumulation engine"
```

---

### Task 3: Persist One Safe Same-Day Successor and Matching Reviews

**Files:**
- Modify: `src/newsradar/daily_reports/repository.py:72-180,667-814`
- Test: `tests/daily_reports/test_service.py`

**Interfaces:**
- Produces: `latest_archived_for_day(report_date, excluding_operation_id)`, `applied_event_survivors(event_ids)`, `overview_decisions(report_id)`, and `create_cumulative_draft(draft)`.
- Consumes: the existing `_create_draft`, revision advisory lock, uniqueness constraints, and editorial-review tables.

- [ ] **Step 1: Write repository-facing failing tests**

Add a local `_archived_report` test helper that inserts a report, optional overview items, and then calls `DailyReportRepository.archive`. Use it to add tests proving:

```python
def test_latest_archived_for_day_returns_only_latest_eligible_report(db_session):
    older = _archived_report(db_session, report_date=date(2026, 7, 19), revision=1)
    latest = _archived_report(db_session, report_date=date(2026, 7, 19), revision=2)
    deleted = _archived_report(db_session, report_date=date(2026, 7, 19), revision=3)
    deleted.deleted_at = NOW
    other_day = _archived_report(db_session, report_date=date(2026, 7, 18), revision=1)
    db_session.commit()

    selected = DailyReportRepository(db_session).latest_archived_for_day(
        date(2026, 7, 19), excluding_operation_id=9999
    )

    assert selected is not None
    assert selected.id == latest.id
    assert selected.id not in {older.id, deleted.id, other_day.id}


def test_create_cumulative_draft_links_predecessor_and_copies_matching_review(
    db_session,
):
    predecessor = _archived_report_with_review(db_session, event_id=101, version=1)
    draft = _daily_report_draft(
        source_operation_id=2402,
        supersedes_report_id=predecessor.id,
        overview_event_versions=((101, 1), (102, 1)),
    )

    successor = DailyReportRepository(db_session).create_cumulative_draft(draft)
    copied = DailyReportRepository(db_session).overview_items(successor.id)

    assert successor.supersedes_report_id == predecessor.id
    assert successor.revision == predecessor.revision + 1
    assert len(DailyReportRepository(db_session).overview_editorial_reviews(copied[0].id)) == 1
    assert DailyReportRepository(db_session).overview_editorial_reviews(copied[1].id) == ()


def test_create_cumulative_draft_does_not_copy_review_to_new_event_version(db_session):
    predecessor = _archived_report_with_review(db_session, event_id=101, version=1)
    draft = _daily_report_draft(
        source_operation_id=2402,
        supersedes_report_id=predecessor.id,
        overview_event_versions=((101, 2),),
    )

    successor = DailyReportRepository(db_session).create_cumulative_draft(draft)
    item = DailyReportRepository(db_session).overview_items(successor.id)[0]

    assert DailyReportRepository(db_session).overview_editorial_reviews(item.id) == ()
```

For `test_applied_event_survivors_maps_legacy_to_survivor`, insert one `EventMergeCandidateRecord` with status `applied` and `result_summary=MergeApplyResult(status="applied", candidate_id=1, survivor_event_id=101, survivor_version_number=2, legacy_event_id=102, legacy_version_number=1).model_dump(mode="json")`; assert the method returns `{102: 101, 101: 101}`.

The successor assertion must be exact:

```python
assert successor.supersedes_report_id == predecessor.id
assert successor.revision == predecessor.revision + 1
```

- [ ] **Step 2: Run only the new repository tests**

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_service.py -k "latest_archived_for_day or cumulative_draft or applied_event_survivors" -q
```

Expected: FAIL because the repository methods do not exist.

- [ ] **Step 3: Add same-day baseline and applied-merge queries**

Implement:

```python
def latest_archived_for_day(
    self,
    report_date: date,
    *,
    excluding_operation_id: int,
) -> DailyReportRecord | None:
    return self.session.scalar(
        select(DailyReportRecord)
        .where(
            DailyReportRecord.report_date == report_date,
            DailyReportRecord.status == ReportStatus.ARCHIVED.value,
            DailyReportRecord.deleted_at.is_(None),
            DailyReportRecord.source_operation_id != excluding_operation_id,
        )
        .order_by(DailyReportRecord.revision.desc(), DailyReportRecord.id.desc())
        .limit(1)
    )
```

Query `EventMergeCandidateRecord` rows with status `applied`, read their validated `MergeApplyResult`, and return only mappings whose legacy and survivor IDs are in the requested set. Invalid or incomplete result summaries must be ignored with a structured warning, not guessed.

The baseline query intentionally ignores `window_hours`: a 72-hour fallback report followed by a 24-hour successful run on the same Shanghai date must remain one cumulative chain. Add a PostgreSQL date-level advisory lock key `newsradar:daily-report-day:{YYYY-MM-DD}` around cumulative successor validation; retain the existing date/window lock for revision-number allocation.

- [ ] **Step 4: Generalize review copying by identity**

Replace the positional strict-zip decision-review assumption with maps keyed by `(event_id, event_version_number)`, matching the existing overview-copy strategy. Expose prior overview decisions as:

```python
def overview_decisions(
    self, report_id: int
) -> dict[tuple[int, int], EditorialDecision]:
    return {
        (item.event_id, item.event_version_number): EditorialDecision(review.decision)
        for item in self.overview_items(report_id)
        if (review := self._latest_overview_editorial_review(item.id)) is not None
    }
```

Implement `create_cumulative_draft` by calling `_create_draft(draft, commit=False)`, copying only matching reviews from `draft.supersedes_report_id`, then committing once. Preserve duplicate targets by mapping the target event/version into the successor overview.

- [ ] **Step 5: Run the repository and existing revision tests**

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_service.py -k "cumulative or latest_archived or applied_event or revise" -q
```

Expected: PASS with no migration.

- [ ] **Step 6: Commit safe successor persistence**

```powershell
git add src/newsradar/daily_reports/repository.py tests/daily_reports/test_service.py
git commit -m "feat: persist cumulative daily report successors"
```

---

### Task 4: Integrate Accumulation, Re-rank Decisions, and Prevent Revision Shrinkage

**Files:**
- Modify: `src/newsradar/daily_reports/service.py:230-486`
- Modify: `src/newsradar/daily_reports/repository.py`
- Test: `tests/daily_reports/test_service.py`

**Interfaces:**
- Consumes: Task 2 `accumulate_daily_overview` and Task 3 repository queries.
- Produces: same-day successor reports whose decision items are derived from the cumulative overview and revisions whose overview is a non-shrinking union.

- [ ] **Step 1: Write the end-to-end same-day failing tests**

Add a `_seed_operation_with_ids(session, operation_id, event_specs, window_end)` helper that uses `_seed_snapshot_event` for each `(event_id, status, tier, score, version)` specification and stores those exact event/version references in `OperationRunRecord.result_summary`. Use it for these exact scenarios:

```python
def test_second_same_day_report_accumulates_eleven_and_reranks_decisions(db_session):
    first_operation = _seed_operation_with_ids(db_session, 2401, tuple(range(1, 9)), NOW)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    first = service.generate_from_operation(first_operation, 24, now=NOW)
    repository.archive(first.id)
    second_operation = _seed_operation_with_ids(
        db_session, 2402, (8, 9, 10, 11), NOW + timedelta(hours=1)
    )

    second = service.generate_from_operation(
        second_operation, 24, now=NOW + timedelta(hours=1)
    )

    assert second.supersedes_report_id == first.id
    assert [row.event_id for row in repository.overview_items(second.id)] == list(range(1, 12))
    assert set(row.event_id for row in repository.items(second.id)).issubset(set(range(1, 12)))
    assert second.generation_summary["overview_count"] == 11


def test_second_same_day_report_with_only_old_events_does_not_shrink(db_session):
    first_operation = _seed_operation_with_ids(db_session, 2401, tuple(range(1, 12)), NOW)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    first = service.generate_from_operation(first_operation, 24, now=NOW)
    repository.archive(first.id)
    second_operation = _seed_operation_with_ids(
        db_session, 2402, (10, 11), NOW + timedelta(hours=1)
    )

    second = service.generate_from_operation(
        second_operation, 24, now=NOW + timedelta(hours=1)
    )

    assert [row.event_id for row in repository.overview_items(second.id)] == list(range(1, 12))


def test_second_same_day_generation_failure_leaves_archived_head_unchanged(
    db_session, monkeypatch
):
    first_operation = _seed_operation_with_ids(db_session, 2401, tuple(range(1, 9)), NOW)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    first = service.generate_from_operation(first_operation, 24, now=NOW)
    repository.archive(first.id)
    second_operation = _seed_operation_with_ids(db_session, 2402, (9,), NOW)
    monkeypatch.setattr(service, "_overview_drafts", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("materialization failed")))

    with pytest.raises(RuntimeError, match="materialization failed"):
        service.generate_from_operation(second_operation, 24, now=NOW)

    assert repository.latest_archived_for_day(
        NOW.astimezone(ZoneInfo(REPORT_TIMEZONE)).date(),
        excluding_operation_id=second_operation,
    ).id == first.id


def test_revision_unions_archived_overview_with_full_operation_snapshot(db_session):
    operation_id = _seed_operation_with_ids(db_session, 2401, tuple(range(1, 9)), NOW)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = service.generate_from_operation(operation_id, 24, now=NOW)
    db_session.execute(
        delete(DailyReportOverviewItemRecord).where(
            DailyReportOverviewItemRecord.daily_report_id == original.id,
            DailyReportOverviewItemRecord.event_id > 4,
        )
    )
    db_session.commit()
    repository.archive(original.id)

    revision = service.revise(original.id)

    assert [row.event_id for row in repository.overview_items(revision.id)] == list(range(1, 9))
```

- [ ] **Step 2: Run the four tests and verify they fail**

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_service.py -k "second_same_day or revision_unions" -q
```

Expected: FAIL because reports are independent and decisions come only from the current page rows.

- [ ] **Step 3: Derive decisions from accumulated overview drafts**

Replace page-row-only decision construction with a helper:

```python
def _decision_drafts(
    overview_items: tuple[DailyReportOverviewItemDraft, ...],
) -> tuple[DailyReportItemDraft, ...]:
    drafts: list[DailyReportItemDraft] = []
    for section in (ReportSection.CONFIRMED, ReportSection.EMERGING):
        candidates = [
            item
            for item in overview_items
            if item.snapshot.get("status") == section.value
            and (
                section is ReportSection.CONFIRMED
                or item.snapshot.get("display_tier") in {"hotspot", "signal"}
            )
            and "display_degradation_reason" not in item.snapshot
            and item.snapshot.get("daily_disposition", {}).get("status")
            not in {"excluded", "invalidated"}
        ]
        candidates.sort(key=_overview_rank_key)
        for position, item in enumerate(candidates[:MAX_ITEMS_PER_SECTION], start=1):
            drafts.append(
                DailyReportItemDraft(
                    event_id=item.event_id,
                    event_version_number=item.event_version_number,
                    section=section,
                    position=position,
                    snapshot=dict(item.snapshot),
                )
            )
    return tuple(drafts)
```

`_overview_rank_key` must sort by descending numeric rank score, descending parsed `occurred_at`, then event ID; malformed values sort last without blocking the report.

- [ ] **Step 4: Integrate the same-day baseline in `_generate`**

After computing `report_date` and current overview drafts:

1. Query `latest_archived_for_day`.
2. Load predecessor overview items and convert them to drafts.
3. Load predecessor overview decisions.
4. Load applied survivor identities for all involved event IDs.
5. Call `accumulate_daily_overview`.
6. Derive decision drafts from the accumulated items.
7. Attach `decision_event_id` and per-item `daily_disposition`:
   - selected: `selected_for_decision`;
   - valid but not selected: `low_decision_priority`;
   - degraded: `display_data_degraded`;
   - copied prior duplicate/exclude: preserve its existing reason.
8. Set `supersedes_report_id` to the predecessor ID.
9. Persist through `create_cumulative_draft`.

Write these summary fields:

```python
"decision_count": len(decision_drafts),
"overview_count": len(accumulated.items),
"omitted_from_decision_count": len(accumulated.items) - len(decision_drafts),
"inherited_count": accumulated.stats.inherited_count,
"new_count": accumulated.stats.new_count,
"updated_count": accumulated.stats.updated_count,
"deduplicated_count": accumulated.stats.deduplicated_count,
"invalidated_count": accumulated.stats.invalidated_count,
"cumulative_base_report_id": predecessor.id if predecessor else None,
```

- [ ] **Step 5: Make revision use the same non-shrinking union**

When the original operation snapshot exists, materialize it without overview filtering and call `accumulate_daily_overview(previous=archived_overview, current=materialized, canonical_event_ids=survivors, previous_decisions=review_decisions)`. When the operation snapshot is absent, copy the archived overview exactly. Preserve the original decision items and their fixed snapshots; a revision expands or corrects the overview but does not silently introduce newly ranked decision items.

Before repository mutation, assert:

```python
if len(rebuilt_overview_items) < len(original_overview_items):
    raise RuntimeError("daily_report_overview_would_shrink")
```

- [ ] **Step 6: Run all service and accumulation tests**

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_accumulation.py tests/daily_reports/test_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit integrated cumulative generation**

```powershell
git add src/newsradar/daily_reports/service.py src/newsradar/daily_reports/repository.py tests/daily_reports/test_service.py
git commit -m "fix: accumulate same-day daily report content"
```

---

### Task 5: Show the Full/Decision Difference and Chinese Reasons

**Files:**
- Modify: `src/newsradar/web/daily_report_queries.py`
- Modify: `src/newsradar/web/templates/daily_report_detail.html:235-340`
- Test: `tests/web/test_daily_report_pages.py`

**Interfaces:**
- Consumes: `generation_summary` counters and per-item `snapshot["daily_disposition"]`.
- Produces: visible report-level `累计事件 / 决策版 / 全览版 / 未进入决策版` counts and item-level Chinese reasons.

- [ ] **Step 1: Write a failing page test**

Seed a report with eight overview items and two decision links, then assert:

```python
response = client.get(f"/daily-reports/{report.id}")
assert response.status_code == 200
assert "累计事件 8" in response.text
assert "决策版 2" in response.text
assert "全览版 8" in response.text
assert "未进入决策版 6" in response.text
assert "当前决策优先级较低，仍保留在情报全览中。" in response.text
```

- [ ] **Step 2: Run the focused web test**

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/web/test_daily_report_pages.py -k "cumulative_counts" -q
```

Expected: FAIL because the counters and structured reason are not rendered.

- [ ] **Step 3: Add query fallbacks and template rendering**

For legacy reports, calculate missing counters from persisted rows rather than displaying zero. Render the disposition reason for every non-decision item, with this safe fallback:

```jinja2
{% set disposition = item.snapshot.get('daily_disposition', {}) %}
<p class="metric-note">
  中文原因：{{ disposition.get('reason_zh', '该条目未进入当前决策简报，但仍保留在情报全览中。') }}
</p>
```

Do not alter the later milestone’s archive-list layout.

- [ ] **Step 4: Run daily-report page tests**

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/web/test_daily_report_pages.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit visible completeness diagnostics**

```powershell
git add src/newsradar/web/daily_report_queries.py src/newsradar/web/templates/daily_report_detail.html tests/web/test_daily_report_pages.py
git commit -m "feat: explain daily overview coverage"
```

---

### Task 6: Stop Automatic Overview Audio Before Expanding the Overview

**Files:**
- Modify: `src/newsradar/daily_reports/autopilot_runtime.py:440-525`
- Test: `tests/daily_reports/test_autopilot_runtime.py:480-640`

**Interfaces:**
- Consumes: existing `OperationCommandService.archive_and_enqueue_daily_report_audio`, which archives and idempotently enqueues the decision rendition.
- Produces: an autopilot run that waits for one decision-audio operation and leaves `overview_audio_operation_id` unset; the existing web POST `/daily-reports/{id}/audio/overview` remains the explicit on-demand path.

- [ ] **Step 1: Replace pair-audio expectations with decision-only failing tests**

Add or rename tests to assert:

```python
def test_archive_stage_enqueues_only_decision_audio(monkeypatch) -> None:
    calls: list[tuple[int, str]] = []

    class Commands:
        def __init__(self, _session, **_kwargs) -> None:
            pass

        def archive_and_enqueue_daily_report_audio(
            self, *, report_id: int, trigger: str
        ) -> int:
            calls.append((report_id, trigger))
            return 51

    monkeypatch.setattr(autopilot_runtime, "OperationCommandService", Commands)
    handler = DailyAutopilotHandler(lambda: _SessionContext(object()))
    transitions = []
    monkeypatch.setattr(
        handler,
        "_transition_and_continue",
        lambda run_id, stage, **ids: transitions.append((run_id, stage, ids)),
    )

    handler._archive_and_enqueue_audio(
        SimpleNamespace(
            id=9,
            daily_report_id=41,
            decision_audio_operation_id=None,
            overview_audio_operation_id=None,
        ),
        lambda _boundary: None,
    )

    assert calls == [(41, "autopilot")]
    assert transitions[0][2] == {
        "decision_audio_operation_id": 51,
        "delayed": True,
    }


def test_wait_audio_completes_after_decision_audio_succeeds_without_overview() -> None:
    factory = _session_factory()
    run = _seed_autopilot_report(factory)
    with factory() as db:
        decision = OperationRunRecord(
            operation_type=OperationType.DAILY_REPORT_AUDIO.value,
            trigger="autopilot",
            status=OperationStatus.SUCCEEDED.value,
            requested_scope={"daily_report_id": run.daily_report_id, "rendition": "decision"},
            result_summary={},
        )
        db.add(decision)
        db.flush()
        DailyAutopilotRepository(db).transition(
            run.id,
            stage=DailyAutopilotStage.WAIT_AUDIO,
            daily_report_id=run.daily_report_id,
            decision_audio_operation_id=decision.id,
        )
        db.commit()

    DailyAutopilotHandler(factory)(
        _lease(run.id, DailyAutopilotStage.WAIT_AUDIO), lambda _boundary: None
    )
    with factory() as db:
        saved = DailyAutopilotRepository(db).get(run.id)

    assert saved.status == "succeeded"
    assert saved.result_summary == {
        "daily_report_id": run.daily_report_id,
        "audio_count": 1,
        "overview_audio": "on_demand",
    }
```

- [ ] **Step 2: Run autopilot audio tests and verify failure**

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_autopilot_runtime.py -k "audio" -q
```

Expected: FAIL because the runtime still requires and waits for two audio operations.

- [ ] **Step 3: Change only the automatic orchestration**

In `_archive_and_enqueue_audio`, call:

```python
decision_id = OperationCommandService(
    session, utcnow=self._utcnow
).archive_and_enqueue_daily_report_audio(
    report_id=run.daily_report_id,
    trigger="autopilot",
)
```

Transition to `WAIT_AUDIO` with only `decision_audio_operation_id`. In `_wait_for_audio`, validate and wait for that one child, then finish with `audio_count=1` and `overview_audio="on_demand"`. Do not remove `overview_audio_operation_id` from the database model or migration; old runs with two IDs must remain readable and cancellable.

- [ ] **Step 4: Prove the manual overview endpoint still works**

Run the existing web/command tests covering:

```text
POST /daily-reports/{report_id}/audio/overview
OperationCommandService.enqueue_daily_report_audio(rendition="overview")
```

The command must remain idempotent for queued/running/completed overview operations.

- [ ] **Step 5: Run autopilot and operation-command tests**

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_autopilot_runtime.py tests/operations/test_commands.py tests/web/test_daily_report_pages.py -q
```

Expected: PASS; the existing two-audio package command remains backward compatible, while autopilot no longer calls it.

- [ ] **Step 6: Commit decision-only automatic audio**

```powershell
git add src/newsradar/daily_reports/autopilot_runtime.py tests/daily_reports/test_autopilot_runtime.py
git commit -m "fix: generate overview audio only on demand"
```

---

### Task 7: Milestone Verification and Real Web Acceptance

**Files:**
- Modify only if verification exposes a directly related defect in files already listed above.
- Do not modify `reports/` or `.env`.

**Interfaces:**
- Consumes: all prior milestone tasks.
- Produces: evidence that the milestone meets the approved invariants without network-heavy repeated validation.

- [ ] **Step 1: Run the milestone target suite once**

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_accumulation.py tests/daily_reports/test_service.py tests/daily_reports/test_autopilot_runtime.py tests/web/test_daily_report_pages.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Ruff and migration-head check**

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\ruff.exe check src tests
D:\codex_project_work\news_codex\.venv\Scripts\alembic.exe heads
```

Expected: Ruff exits 0; Alembic reports the existing single head with no new revision.

- [ ] **Step 3: Run the complete pytest suite exactly once**

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest -q
```

Expected: PASS; normal runtime is approximately 4–5 minutes on this workspace.

- [ ] **Step 4: Start one isolated local acceptance service**

Use a free port different from the user’s current 8767 service, start the web app and one worker from this worktree, and wait by polling the health page with a bounded timeout. Do not stop or replace the user’s existing service.

- [ ] **Step 5: Perform one real page acceptance without real audio generation**

Generate or use a deterministic local test report representing eight events and verify in the browser:

- top counters show `累计事件 8 / 决策版 2 / 全览版 8 / 未进入决策版 6`;
- all eight overview items are visible;
- six items show a Chinese omission reason;
- no overview-audio task appears until the button is clicked;
- do not click the overview-audio button during this milestone acceptance;
- report #4 remains unchanged and still shows its historical 49 candidates.

- [ ] **Step 6: Review scope and commit only direct verification fixes**

```powershell
git status --short
git diff --check
```

If no verification fix was needed, do not create an empty commit. If a direct fix was required, rerun its focused failing test, commit only the relevant files, then repeat Steps 1–3 once.

---

## Plan Self-Review Result

- Spec coverage: milestone-one generation, accumulation, prior decisions, applied duplicates, revision non-shrink, visible Chinese reasons, and on-demand overview-audio safety are covered.
- Explicitly deferred: archive-list pagination/grouping and 90/30-day retention UX remain milestones two and three.
- Database impact: no new table, column, index, or migration is planned.
- Network impact: no real MiniMax request is required for development or milestone verification.
- Type consistency: accumulation interfaces use `DailyReportOverviewItemDraft`, `EditorialDecision`, and event/version tuple keys throughout.
- Regression guard: report #4 is read-only during acceptance; revision behavior is covered with synthetic snapshots before any historical revision is attempted.
