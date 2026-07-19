# Daily Report Repeatable Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing daily-report revision entry safe for repeated, concurrent, post-trash, and long-lived use without mutating archived reports.

**Architecture:** Keep archived reports immutable and keep `supersedes_report_id` as the audit relationship, but enforce uniqueness only for non-deleted active successors. Resolve the latest active revision before materialization, rebuild from the original immutable event snapshot when available, fall back only for legacy operations that never recorded snapshot manifests, and make restore/purge explicitly aware of abandoned branches.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, FastAPI/Jinja, PostgreSQL, SQLite, pytest, Ruff.

## Global Constraints

- Work only in `D:\codex_project_work\news_codex\.worktrees\daily-report-trashed-revision` on `codex/daily-report-trashed-revision`.
- Do not read or print `.env`; do not touch user-retained files under `reports/`.
- Do not refetch sources or rerun the 41-target wave.
- Archived reports and existing audio artifacts remain immutable.
- MiniMax does not decide inclusion, legality, evidence status, or source enablement.
- Every production behavior starts with a failing automated test and an observed RED result.
- Network operations are not added by this feature.
- Do not merge or push without explicit user confirmation.

---

## File Map

- `migrations/versions/20260719_0031_active_daily_report_revision_indexes.py`: replace unconditional report identity/successor indexes with active-row partial unique indexes.
- `src/newsradar/db/models.py`: declare the two partial indexes in SQLAlchemy metadata.
- `src/newsradar/daily_reports/repository.py`: active successor lookup, latest revision resolution, restore conflict detection, and idempotent creation.
- `src/newsradar/daily_reports/service.py`: resolve the materialization source and select immutable-snapshot or legacy-copy behavior.
- `src/newsradar/daily_reports/purge_runtime.py`: make temporary reparent traversal deterministic when a historical parent has multiple abandoned children.
- `src/newsradar/web/app.py`: preserve the existing routes and expose stable Chinese diagnostics/notices.
- `src/newsradar/web/templates/daily_report_detail.html`: show revision provenance/degradation information already stored in `generation_summary`.
- `src/newsradar/web/templates/daily_report_trash.html`: explain restore conflicts without exposing report contents.
- `tests/daily_reports/test_repeatable_revision_migration.py`: migration and metadata contract.
- `tests/daily_reports/test_repository.py`: repository version-chain and concurrency-adjacent idempotency behavior.
- `tests/daily_reports/test_retention.py`: restore conflicts.
- `tests/daily_reports/test_service.py`: latest-head and snapshot fallback behavior.
- `tests/daily_reports/test_purge_runtime.py`: abandoned-branch purge behavior.
- `tests/web/test_daily_report_pages.py`: route and visible Chinese behavior.
- `tests/acceptance/test_daily_report_repeatable_revision_postgres.py`: PostgreSQL partial-unique and concurrent request acceptance.

---

### Task 1: Active-row uniqueness migration

**Files:**
- Create: `migrations/versions/20260719_0031_active_daily_report_revision_indexes.py`
- Create: `tests/daily_reports/test_repeatable_revision_migration.py`
- Modify: `src/newsradar/db/models.py:898-910`

**Interfaces:**
- Produces: `uq_daily_report_identity` with predicate `supersedes_report_id IS NULL AND deleted_at IS NULL`.
- Produces: `uq_daily_report_supersedes` with predicate `supersedes_report_id IS NOT NULL AND deleted_at IS NULL`.
- Preserves: `uq_daily_report_revision` for monotonically increasing revision numbers.

- [ ] **Step 1: Add failing metadata and migration tests**

```python
def test_model_declares_active_daily_report_identity_indexes() -> None:
    indexes = {index.name: index for index in DailyReportRecord.__table__.indexes}
    identity = indexes["uq_daily_report_identity"]
    successor = indexes["uq_daily_report_supersedes"]
    assert identity.unique is True
    assert successor.unique is True
    assert str(identity.dialect_options["sqlite"]["where"]) == (
        "supersedes_report_id IS NULL AND deleted_at IS NULL"
    )
    assert str(successor.dialect_options["sqlite"]["where"]) == (
        "supersedes_report_id IS NOT NULL AND deleted_at IS NULL"
    )


def test_migration_creates_active_partial_indexes() -> None:
    migration_path = (
        Path(__file__).parents[2]
        / "migrations/versions/20260719_0031_active_daily_report_revision_indexes.py"
    )
    spec = spec_from_file_location("active_daily_report_indexes", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    created: dict[str, dict[str, object]] = {}
    migration.op = SimpleNamespace(
        drop_index=lambda *args, **kwargs: None,
        create_index=lambda name, table, columns, **kwargs: created.__setitem__(
            name, {"table": table, "columns": columns, **kwargs}
        ),
    )

    migration.upgrade()

    assert str(created["uq_daily_report_identity"]["sqlite_where"]) == (
        "supersedes_report_id IS NULL AND deleted_at IS NULL"
    )
    assert str(created["uq_daily_report_supersedes"]["sqlite_where"]) == (
        "supersedes_report_id IS NOT NULL AND deleted_at IS NULL"
    )
```

- [ ] **Step 2: Run the focused tests and observe RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_repeatable_revision_migration.py -q`

Expected: FAIL because revision `20260719_0031` and the metadata indexes do not exist.

- [ ] **Step 3: Declare the partial indexes in the model**

Add these entries to `DailyReportRecord.__table_args__`:

```python
Index(
    "uq_daily_report_identity",
    "report_date",
    "window_hours",
    "source_operation_id",
    unique=True,
    postgresql_where=text("supersedes_report_id IS NULL AND deleted_at IS NULL"),
    sqlite_where=text("supersedes_report_id IS NULL AND deleted_at IS NULL"),
),
Index(
    "uq_daily_report_supersedes",
    "supersedes_report_id",
    unique=True,
    postgresql_where=text("supersedes_report_id IS NOT NULL AND deleted_at IS NULL"),
    sqlite_where=text("supersedes_report_id IS NOT NULL AND deleted_at IS NULL"),
),
```

- [ ] **Step 4: Add migration `20260719_0031`**

```python
"""Allow abandoned daily-report drafts to be replaced safely."""

from alembic import op
import sqlalchemy as sa

revision = "20260719_0031"
down_revision = "20260718_0030"
branch_labels = None
depends_on = None

IDENTITY_ACTIVE = sa.text("supersedes_report_id IS NULL AND deleted_at IS NULL")
SUCCESSOR_ACTIVE = sa.text(
    "supersedes_report_id IS NOT NULL AND deleted_at IS NULL"
)


def upgrade() -> None:
    op.drop_index("uq_daily_report_supersedes", table_name="daily_reports")
    op.drop_index("uq_daily_report_identity", table_name="daily_reports")
    op.create_index(
        "uq_daily_report_identity",
        "daily_reports",
        ["report_date", "window_hours", "source_operation_id"],
        unique=True,
        postgresql_where=IDENTITY_ACTIVE,
        sqlite_where=IDENTITY_ACTIVE,
    )
    op.create_index(
        "uq_daily_report_supersedes",
        "daily_reports",
        ["supersedes_report_id"],
        unique=True,
        postgresql_where=SUCCESSOR_ACTIVE,
        sqlite_where=SUCCESSOR_ACTIVE,
    )


def downgrade() -> None:
    bind = op.get_bind()
    successor_duplicate = bind.execute(sa.text(
        "SELECT supersedes_report_id FROM daily_reports "
        "WHERE supersedes_report_id IS NOT NULL "
        "GROUP BY supersedes_report_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    root_duplicate = bind.execute(sa.text(
        "SELECT report_date, window_hours, source_operation_id FROM daily_reports "
        "WHERE supersedes_report_id IS NULL "
        "GROUP BY report_date, window_hours, source_operation_id "
        "HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if successor_duplicate is not None or root_duplicate is not None:
        raise RuntimeError(
            "cannot restore unconditional daily-report identity uniqueness"
        )
    op.drop_index("uq_daily_report_supersedes", table_name="daily_reports")
    op.drop_index("uq_daily_report_identity", table_name="daily_reports")
    op.create_index(
        "uq_daily_report_identity",
        "daily_reports",
        ["report_date", "window_hours", "source_operation_id"],
        unique=True,
        postgresql_where=sa.text("supersedes_report_id IS NULL"),
        sqlite_where=sa.text("supersedes_report_id IS NULL"),
    )
    op.create_index(
        "uq_daily_report_supersedes",
        "daily_reports",
        ["supersedes_report_id"],
        unique=True,
    )
```

- [ ] **Step 5: Verify GREEN and existing migration coverage**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_repeatable_revision_migration.py tests/test_migrations.py tests/daily_reports/test_automation_migration.py -q`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit the migration slice**

```powershell
git add migrations/versions/20260719_0031_active_daily_report_revision_indexes.py src/newsradar/db/models.py tests/daily_reports/test_repeatable_revision_migration.py tests/test_migrations.py
git commit -m "fix: allow active daily report revision replacement"
```

---

### Task 2: Active version-chain resolution and restore conflicts

**Files:**
- Modify: `src/newsradar/daily_reports/repository.py:81-214,634-752,903-943`
- Modify: `tests/daily_reports/test_repository.py:813-845`
- Modify: `tests/daily_reports/test_retention.py:86-115`

**Interfaces:**
- Produces: `DailyReportRepository.revision_target(report_id: int) -> DailyReportRecord`.
- Changes: `_matching_report(draft)` returns only `deleted_at IS NULL` rows.
- Changes: `restore(report_id)` returns `RetentionActionResult(..., "blocked", ...)` for an active identity/successor conflict.
- Consumes: active partial unique indexes from Task 1.

- [ ] **Step 1: Add failing chain tests**

```python
def test_revise_replaces_trashed_child_and_reuses_new_active_child(db_session: Session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    parent = repository.archive(repository.create_draft(_draft(db_session)).id)
    abandoned = repository.revise(parent.id)
    repository.move_to_trash(abandoned.id)

    replacement = repository.revise(parent.id)
    retried = repository.revise(parent.id)

    assert replacement.id != abandoned.id
    assert replacement.revision == abandoned.revision + 1
    assert replacement.supersedes_report_id == parent.id
    assert replacement.deleted_at is None
    assert retried.id == replacement.id


def test_revise_from_old_parent_continues_from_latest_archived_head(db_session: Session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    parent = repository.archive(repository.create_draft(_draft(db_session)).id)
    child = repository.archive(repository.revise(parent.id).id)

    latest = repository.revise(parent.id)

    assert latest.status == "draft"
    assert latest.supersedes_report_id == child.id
```

Add a retention test that trashes a child, creates its active replacement, calls `restore(abandoned.id)`, and asserts outcome `blocked`, `deleted_at` unchanged, and message `该日报已有新的有效修订版，不能直接恢复。`.

- [ ] **Step 2: Run focused repository tests and observe RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_repository.py tests/daily_reports/test_retention.py -q`

Expected: FAIL because the abandoned child is reused, the old parent stops at an archived child, and restore relies on a database error.

- [ ] **Step 3: Add active successor and target resolution**

```python
def _active_successor(self, report_id: int) -> DailyReportRecord | None:
    return self.session.scalar(
        select(DailyReportRecord).where(
            DailyReportRecord.supersedes_report_id == report_id,
            DailyReportRecord.deleted_at.is_(None),
        )
    )


def revision_target(self, report_id: int) -> DailyReportRecord:
    report = self.session.get(DailyReportRecord, report_id)
    if report is None:
        raise LookupError("daily_report_not_found")
    if report.deleted_at is not None:
        raise ValueError("daily_report_is_trashed")
    if report.status != ReportStatus.ARCHIVED.value:
        raise ValueError("daily_report_must_be_archived")
    seen = {report.id}
    while successor := self._active_successor(report.id):
        if successor.id in seen:
            raise RuntimeError("daily_report_revision_chain_invalid")
        seen.add(successor.id)
        report = successor
        if report.status == ReportStatus.DRAFT.value:
            return report
    return report
```

Update `revise()` to resolve the target first, return it when it is already a draft, and otherwise copy/create from that latest archived record. Update `_matching_report()` by adding `DailyReportRecord.deleted_at.is_(None)` to both successor and root queries.

- [ ] **Step 4: Add explicit restore conflict checks under the report lock**

Before clearing `deleted_at`, query for another undeleted row with the same `supersedes_report_id`; for roots query the same `(report_date, window_hours, source_operation_id)` identity. Return:

```python
RetentionActionResult(
    report_id,
    "blocked",
    "该日报已有新的有效修订版，不能直接恢复。",
)
```

Do not catch the partial unique violation as normal control flow.

- [ ] **Step 5: Verify GREEN**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_repository.py tests/daily_reports/test_retention.py -q`

Expected: all selected tests PASS, including existing direct-child idempotency tests updated to the new latest-head contract.

- [ ] **Step 6: Commit repository behavior**

```powershell
git add src/newsradar/daily_reports/repository.py tests/daily_reports/test_repository.py tests/daily_reports/test_retention.py
git commit -m "fix: resolve active daily report revision heads"
```

---

### Task 3: Immutable snapshot rebuild with legacy-copy fallback

**Files:**
- Modify: `src/newsradar/daily_reports/service.py:353-384`
- Modify: `src/newsradar/daily_reports/repository.py:634-684`
- Modify: `tests/daily_reports/test_service.py:700-740`
- Modify: `tests/web/test_daily_report_pages.py:1997-2055`

**Interfaces:**
- Consumes: `DailyReportRepository.revision_target(report_id)` from Task 2.
- Changes: `DailyReportRepository.revise(..., generation_summary: dict[str, object] | None = None)`.
- Records: `generation_summary["revision_overview_source"]` equal to `"event_snapshot"` or `"archived_report_snapshot"`.

- [ ] **Step 1: Add failing service tests**

```python
def test_revise_legacy_report_without_manifest_copies_frozen_overview(
    db_session: Session,
) -> None:
    seed_complete_snapshot(db_session)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    report = repository.archive(service.generate(24, now=NOW).id)
    frozen = [row.snapshot for row in repository.overview_items(report.id)]
    operation = db_session.get(OperationRunRecord, report.source_operation_id)
    assert operation is not None
    operation.result_summary = {
        key: value
        for key, value in operation.result_summary.items()
        if key != "event_version_snapshots"
    }
    db_session.commit()

    revision = service.revise(report.id)

    assert [row.snapshot for row in repository.overview_items(revision.id)] == frozen
    assert revision.generation_summary["revision_overview_source"] == (
        "archived_report_snapshot"
    )


def test_revise_rejects_manifest_that_exists_but_fails_validation(
    db_session: Session,
) -> None:
    seed_complete_snapshot(db_session)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    report = repository.archive(service.generate(24, now=NOW).id)
    operation = db_session.get(OperationRunRecord, report.source_operation_id)
    assert operation is not None
    operation.result_summary = {
        **operation.result_summary,
        "event_version_snapshots": [{"event_id": report.id}],
    }
    db_session.commit()
    with pytest.raises(ValueError, match="complete_event_snapshot_required"):
        service.revise(report.id)
```

Update both currently failing route tests so their seeded legacy operation exercises the fallback and expects HTTP 303.

- [ ] **Step 2: Run tests and observe RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_service.py tests/web/test_daily_report_pages.py -q`

Expected: the two existing route tests and the new legacy fallback test FAIL with `complete_event_snapshot_required`.

- [ ] **Step 3: Implement explicit legacy detection**

```python
def _operation_has_snapshot_manifest(self, operation_id: int) -> bool:
    operation = self.session.get(OperationRunRecord, operation_id)
    return bool(
        operation is not None
        and isinstance(operation.result_summary, dict)
        and "event_version_snapshots" in operation.result_summary
    )
```

In `DailyReportService.revise()`:

```python
target = self._reports.revision_target(report_id)
if target.status == ReportStatus.DRAFT.value:
    return target
snapshot = event_snapshot_by_id(
    self.session,
    target.source_operation_id,
    now=target.generated_at,
)
if snapshot is None and self._operation_has_snapshot_manifest(target.source_operation_id):
    raise ValueError("complete_event_snapshot_required")
if snapshot is None:
    return self._reports.revise(
        target.id,
        generation_summary={
            **target.generation_summary,
            "revision_overview_source": "archived_report_snapshot",
        },
    )
```

For a valid snapshot, retain the existing `_overview_drafts()` rebuild and pass `revision_overview_source="event_snapshot"` through the generation summary. Repository copying remains the fallback when `rebuilt_overview_items` is empty.

- [ ] **Step 4: Verify GREEN and the original 409 regression**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_service.py tests/web/test_daily_report_pages.py -q`

Expected: all selected tests PASS; specifically `test_move_and_revise_routes_redirect_to_expected_report` and `test_revise_route_from_older_parent_reuses_archived_direct_child` no longer return 409 and the latter is renamed for the latest-head behavior.

- [ ] **Step 5: Commit service materialization**

```powershell
git add src/newsradar/daily_reports/service.py src/newsradar/daily_reports/repository.py tests/daily_reports/test_service.py tests/web/test_daily_report_pages.py
git commit -m "fix: rebuild or safely copy daily report revisions"
```

---

### Task 4: Branch-safe permanent cleanup

**Files:**
- Modify: `src/newsradar/daily_reports/purge_runtime.py:370-430`
- Modify: `tests/daily_reports/test_purge_runtime.py:569-730`

**Interfaces:**
- Consumes: historical parents may have multiple children, but at most one child has `deleted_at IS NULL`.
- Produces: deterministic descendant selection for every child transition; `_finish_revision_reparent()` remains per-child.

- [ ] **Step 1: Add a failing multi-child purge test**

Create an archived parent with a trashed abandoned child and an active replacement child. Give the abandoned child its own descendant, purge the parent through `DailyReportPurgeRuntime`, then assert:

```python
assert session.get(DailyReportRecord, parent_id) is None
assert session.get(DailyReportRecord, abandoned_id).supersedes_report_id is None
assert session.get(DailyReportRecord, active_id).supersedes_report_id is None
assert session.get(DailyReportRecord, abandoned_descendant_id).supersedes_report_id == abandoned_id
assert session.scalars(select(DailyReportPurgeTransitionRecord)).all() == []
```

Add a second test purging only the abandoned child and assert the active sibling remains attached to the original parent.

- [ ] **Step 2: Run tests and observe RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_purge_runtime.py -q`

Expected: FAIL because descendant traversal uses `scalar()` without deterministic handling of multiple historical children or a uniqueness violation occurs during reparent.

- [ ] **Step 3: Make terminal descendant selection explicit**

Extract:

```python
@staticmethod
def _temporary_revision_parent(session: Session, child_id: int) -> int:
    current_id = child_id
    seen = {child_id}
    while True:
        descendants = tuple(
            session.scalars(
                select(DailyReportRecord.id)
                .where(DailyReportRecord.supersedes_report_id == current_id)
                .order_by(
                    DailyReportRecord.deleted_at.is_(None).desc(),
                    DailyReportRecord.id.desc(),
                )
            )
        )
        if not descendants:
            return current_id
        current_id = descendants[0]
        if current_id in seen:
            raise PurgeMemberError("daily_report_purge_persistence_failed", True)
        seen.add(current_id)
```

Use this helper independently for every direct child transition. Do not update sibling rows in bulk; `_finish_revision_reparent()` must continue verifying each transition row and exact predecessor.

- [ ] **Step 4: Verify GREEN and retention guard compatibility**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/daily_reports/test_purge_runtime.py tests/daily_reports/test_automation_migration.py tests/acceptance/test_daily_report_retention_postgres.py -q`

Expected: all selected tests PASS when PostgreSQL acceptance is available; otherwise pytest reports only the repository's established environment skip.

- [ ] **Step 5: Commit purge safety**

```powershell
git add src/newsradar/daily_reports/purge_runtime.py tests/daily_reports/test_purge_runtime.py
git commit -m "fix: preserve daily report branches during purge"
```

---

### Task 5: Chinese web diagnostics and PostgreSQL concurrency acceptance

**Files:**
- Modify: `src/newsradar/web/app.py:430-470,878-946,1120-1137`
- Modify: `src/newsradar/web/templates/daily_report_detail.html:330-365`
- Modify: `src/newsradar/web/templates/daily_report_trash.html:5-35`
- Modify: `tests/web/test_daily_report_pages.py`
- Create: `tests/acceptance/test_daily_report_repeatable_revision_postgres.py`

**Interfaces:**
- Consumes: repository outcomes `blocked`, `unchanged`, and `restored`.
- Displays: legacy provenance message based on `revision_overview_source`.
- Preserves: POST action token validation and HTTP 303 redirects.

- [ ] **Step 1: Add failing route/page tests**

```python
def test_archived_report_revision_entry_reuses_latest_active_draft(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    parent = seed_daily_report(db_session)
    repository.archive(parent.id)
    active_draft = repository.revise(parent.id)
    client, token = safe_client_with_token(db_session, monkeypatch)
    response = client.post(
        f"/daily-reports/{parent.id}/revise",
        data={"action_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/daily-reports/{active_draft.id}"


def test_legacy_revision_page_explains_archived_snapshot_fallback(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = seed_daily_report(db_session)
    revision.generation_summary = {
        **revision.generation_summary,
        "revision_overview_source": "archived_report_snapshot",
    }
    db_session.commit()
    client, _token = safe_client_with_token(db_session, monkeypatch)
    page = client.get(f"/daily-reports/{revision.id}")
    assert "历史操作快照缺失，本修订版沿用归档版固定条目" in page.text


def test_restore_conflict_is_visible_in_trash_page(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    parent = seed_daily_report(db_session)
    repository.archive(parent.id)
    abandoned = repository.revise(parent.id)
    repository.move_to_trash(abandoned.id)
    repository.revise(parent.id)
    client, token = safe_client_with_token(db_session, monkeypatch)
    response = client.post(
        f"/daily-reports/{abandoned.id}/restore",
        data={"action_token": token},
        follow_redirects=True,
    )
    assert "受阻 1 份" in response.text
    assert "已有新的有效修订版" in response.text
```

- [ ] **Step 2: Run web tests and observe RED**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/web/test_daily_report_pages.py -q`

Expected: FAIL because provenance and conflict-specific notices are not rendered.

- [ ] **Step 3: Render stable Chinese diagnostics**

Add a `reason` query parameter generated from a closed allowlist, never from arbitrary exception text. Render these exact messages:

```python
RETENTION_REASON_LABELS = {
    "active_revision_exists": "该日报已有新的有效修订版，不能直接恢复。请打开当前有效版本继续处理。",
}
```

In `daily_report_detail.html`, render the legacy provenance only when:

```jinja2
{% if daily_report.generation_summary.get('revision_overview_source') == 'archived_report_snapshot' %}
<p class="diagnostic-warning">历史操作快照缺失，本修订版沿用归档版固定条目；系统没有重新抓取或混入当前事件。</p>
{% endif %}
```

- [ ] **Step 4: Add PostgreSQL concurrent creation acceptance**

Use two independent sessions and a barrier. Both call `DailyReportRepository.revise(parent_id)` after the abandoned child is trashed. Assert both calls return the same active replacement ID and this query returns one row:

```python
select(DailyReportRecord).where(
    DailyReportRecord.supersedes_report_id == parent_id,
    DailyReportRecord.deleted_at.is_(None),
)
```

- [ ] **Step 5: Verify focused web and PostgreSQL tests**

Run: `..\..\.venv\Scripts\python.exe -m pytest tests/web/test_daily_report_pages.py tests/acceptance/test_daily_report_repeatable_revision_postgres.py -q`

Expected: web tests PASS; PostgreSQL acceptance PASS when configured or uses the established explicit skip.

- [ ] **Step 6: Commit UI and acceptance behavior**

```powershell
git add src/newsradar/web/app.py src/newsradar/web/templates/daily_report_detail.html src/newsradar/web/templates/daily_report_trash.html tests/web/test_daily_report_pages.py tests/acceptance/test_daily_report_repeatable_revision_postgres.py
git commit -m "fix: explain repeatable daily report revisions"
```

---

### Task 6: Full verification and real-data acceptance

**Files:**
- Modify only if verification exposes a defect in the requirements above.

**Interfaces:**
- Validates all earlier tasks together.
- Does not merge, push, or mutate archived production reports automatically.

- [ ] **Step 1: Upgrade a disposable SQLite database through Alembic**

Run: `..\..\.venv\Scripts\python.exe -m alembic upgrade head`

Expected: exit 0 with head `20260719_0032` in the disposable/test configuration. Do not point this command at the user's live database without first confirming the configured URL is disposable.

- [ ] **Step 2: Run the complete test suite**

Run: `..\..\.venv\Scripts\python.exe -m pytest -q`

Expected: exit 0, no failures. Environment-dependent acceptance tests may use only their existing explicit skips.

- [ ] **Step 3: Run Ruff**

Run: `..\..\.venv\Scripts\python.exe -m ruff check .`

Expected: `All checks passed!`

- [ ] **Step 4: Verify migration and working-tree integrity**

Run: `..\..\.venv\Scripts\python.exe -m alembic heads; git diff --check; git status --short`

Expected: one Alembic head `20260719_0032`, no whitespace errors, and only intentional branch changes.

- [ ] **Step 5: Perform local web acceptance without altering #17/#18 first**

Start the isolated worktree on an unused port with a disposable database. Verify: archived page shows the entry; two clicks open one draft; trashing that draft permits a new higher revision; restoring the abandoned draft reports a conflict; archiving the new draft permits another revision; legacy fallback notice appears only on legacy reports.

- [ ] **Step 6: Perform user-approved live-data acceptance**

After separately confirming live migration and data mutation, keep #17 archived and #18 in trash, create the new active revision from #17, verify the fixed operation snapshot produces all expected overview candidates, then click again and confirm the same report ID is returned. Do not archive, merge, or push until the user reviews the page.

- [ ] **Step 7: Record verification status**

Run: `git status --short --branch`

Expected: no uncommitted implementation changes. If verification exposed a defect, return to the task that owns that behavior, repeat its RED/GREEN cycle, and commit that task's exact files before rerunning this complete verification task.
