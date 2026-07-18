# Daily Automation Console Final Fixes Report

## Scope

Closed the final review blockers for archived report purge safety, PostgreSQL DELETE
semantics, revision-chain reparenting, scheduled/manual autopilot conflicts, and recycle-bin
ordering. All tests use disposable SQLite databases and synthetic audio bytes; no user
report, external source, `.env`, or MiniMax call was used.

## Root causes and fixes

1. The 0029 migration relaxed only the archived report-row DELETE guard. The 0023 item
   DELETE guard still rejected the handler's child-first purge order. The handler now
   deletes and verifies the trashed archived parent first, then removes any residual owned
   rows for SQLite connections where foreign-key cascades are disabled. Ordinary archived
   item INSERT/UPDATE/DELETE guards remain enforced. PostgreSQL's item function admits only
   a nested FK-cascade DELETE (`pg_trigger_depth() > 1`) caused by the already-authorized
   parent deletion; a direct item DELETE remains blocked.
2. Audio unlink previously happened before any guarded database delete. Purge now captures
   validated relative paths, performs all reference detachment, report deletion, residual
   child cleanup, revision reparenting, `flush()`, and a report-absence query first. Only
   then does it unlink audio before the surrounding transaction commits. A synthetic
   database DELETE trigger proves a guard failure leaves the file and database rows intact.
3. The PostgreSQL report trigger fell through to `RETURN NEW` for non-archived DELETE,
   silently suppressing the deletion. Its DELETE branch now raises for draft/non-archived
   and non-trashed archived rows, and returns `OLD` only for a trashed archived row. The
   handler independently rejects draft reports and verifies exactly one report row was
   deleted before filesystem side effects.
4. Directly reparenting a newer revision before deleting the middle revision collides with
   the unique `supersedes_report_id` constraint. A transaction-only transition row records
   the child, exact deleted parent, exact predecessor, and terminal descendant used as a
   temporary non-null parent. The archived child may move only to that recorded temporary
   parent while its current parent is archived and trashed; after that parent is deleted,
   it may move only to the recorded predecessor, after which the transition row is removed.
   This works for non-leaf children without colliding with either unique report index. Both
   phases run in one transaction. SQLite and PostgreSQL transition-table triggers validate
   that the temporary parent is the actual terminal descendant, block transition updates,
   and allow deletion only after the exact predecessor is restored and the deleted parent
   is absent. Unmarked, forged, or mismatched archived edits raise
   `daily_report_archived_immutable`.
5. An incompatible active manual 48/72-hour run was not reusable by the scheduled 24-hour
   enqueue and `active_daily_autopilot_exists` escaped into a CLI boundary that only caught
   SQLAlchemy errors. The tick now catches only that exact domain conflict, commits the
   independent retention sweep, returns `deferred` with the active run ID, and deliberately
   leaves `last_scheduled_date` unset so the schedule retries later. A Worker integration
   regression proves normal operation consumption continues after the deferred tick.
6. The recycle bin sorted by `deleted_at DESC`. It now sorts by `purge_after ASC` and
   `id ASC`, matching the retention design and giving stable ties.

## Strict TDD evidence

### RED

The eight new focused regressions were run together before implementation and all failed
for the intended reasons:

- migrated SQLite archived report with populated items and synthetic audio returned purge
  persistence failure;
- a synthetic database DELETE guard ran after the MP3 had already been removed;
- a trashed draft was incorrectly purged successfully;
- an archived newer revision could not be reparented around a trashed middle revision;
- generated PostgreSQL SQL lacked draft DELETE rejection and a controlled reparent path;
- a scheduled tick raised `active_daily_autopilot_exists` with an active manual 48-hour run;
- the Worker exited before `run_once()` under the same conflict;
- trash order was `(3, 4)` instead of purge-deadline order `(4, 3)`.

Command:

```text
uv run --extra dev pytest \
  tests/daily_reports/test_purge_runtime.py::test_migrated_archived_report_purge_removes_populated_items_and_audio_together \
  tests/daily_reports/test_purge_runtime.py::test_database_delete_guard_fails_before_irreversible_audio_unlink \
  tests/daily_reports/test_purge_runtime.py::test_purge_rejects_trashed_draft_before_audio_side_effects \
  tests/daily_reports/test_purge_runtime.py::test_purging_middle_revision_reparents_newer_and_detaches_external_refs \
  tests/daily_reports/test_automation_migration.py::test_postgresql_guard_sql_rejects_draft_delete_and_allows_only_purge_reparent \
  tests/daily_reports/test_automation_service.py::test_tick_defers_incompatible_active_manual_run_without_marking_schedule \
  tests/web/test_cli.py::test_worker_consumes_operation_after_scheduled_tick_defers_active_manual_48h_run \
  tests/daily_reports/test_retention.py::test_report_queries_isolate_trashed_reports_and_offer_trash_views -q
```

Result: `8 failed`.

A follow-up PostgreSQL migration assertion was then added to require the nested
FK-cascade exception in the item guard. It failed before the item function replacement and
passed afterward together with both migrated SQLite runtime purge regressions.

Pre-commit review then added further RED regressions: purging `B` from a four-revision
`A <- B <- C <- D` chain exposed the self-marker uniqueness collision, and a forged
transition could target an unrelated archived report. Both are GREEN with the guarded exact
transition-row protocol; `D` continues to supersede `C`, while `C` deterministically
supersedes `A`.

### GREEN

- Purge/trigger group: `5 passed`.
- Scheduled conflict, Worker continuation, and trash ordering group: `3 passed`.
- Complete affected set (purge runtime, 0029 migration SQL/model tests, full migration
  suite, automation service, Worker CLI, retention): `70 passed`.
- Full relevant gate: `493 tests collected`; all passed with exit code 0:

```text
uv run --extra dev pytest \
  tests/daily_reports \
  tests/operations/test_commands.py \
  tests/operations/test_schema.py \
  tests/web/test_cli.py \
  tests/web/test_daily_automation_pages.py \
  tests/web/test_daily_report_pages.py \
  tests/web/test_daily_autopilot_pages.py \
  tests/test_cli.py \
  tests/test_migrations.py -q
```

The only output warnings are the existing Starlette/httpx deprecation and Alembic
`path_separator` deprecation.

## Static verification

Ruff was run on every changed Python file and reported `All checks passed!`.
`git diff --check` passed. The final status review confirmed that review diff packages
remain untracked and excluded from the scoped commit.

## Files changed

- `migrations/versions/20260718_0029_daily_automation_retention.py`
- `src/newsradar/daily_reports/automation_service.py`
- `src/newsradar/daily_reports/purge_runtime.py`
- `src/newsradar/db/models.py`
- `src/newsradar/web/daily_report_queries.py`
- `tests/daily_reports/test_automation_migration.py`
- `tests/daily_reports/test_automation_service.py`
- `tests/daily_reports/test_purge_runtime.py`
- `tests/daily_reports/test_retention.py`
- `tests/web/test_cli.py`
- `docs/superpowers/plans/2026-07-18-daily-automation-final-fixes.md`
