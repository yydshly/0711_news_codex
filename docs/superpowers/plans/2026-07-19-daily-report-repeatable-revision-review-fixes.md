# Daily Report Repeatable Revision Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four lifecycle gaps found in final review without weakening archived-report immutability or snapshot safety.

**Architecture:** Persist a per-date/window revision high-water mark in its own Alembic table and advance it in the report-creation transaction. Permit permanent deletion of valid trashed leaf drafts, reparent direct draft successors when an archived parent is purged, and align the PostgreSQL/SQLite delete guards with that lifecycle. Reuse a concurrently-created active draft after the locked chain recheck, and translate only recognized SQLite restore uniqueness races into the existing blocked outcome.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, PostgreSQL, SQLite, pytest, Ruff.

## Global Constraints

- Work only in the existing isolated worktree.
- Do not read `.env`, touch retained report artifacts, access the network, merge, or push.
- Preserve archived report and audio immutability outside the existing retention/purge protocol.
- Use test-first RED/GREEN cycles for every production behavior.

---

### Task 1: Permanently purge abandoned revision drafts

**Files:**
- Modify: `tests/daily_reports/test_purge_runtime.py`
- Modify: `src/newsradar/daily_reports/purge_runtime.py`
- Modify: `migrations/versions/20260719_0032_daily_report_revision_counters.py`
- Modify: `tests/daily_reports/test_revision_counter_migration.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/acceptance/test_daily_report_repeatable_revision_postgres.py`

**Interfaces:**
- Consumes: existing trashed-report and active-work preflight.
- Produces: safe purge of a trashed draft only when it has no successors.
- Produces: branch-safe reparenting of a direct draft successor when its archived parent is purged.
- Preserves: database-level rejection of active report deletion on PostgreSQL and SQLite.

- [ ] Change the existing trashed-draft regression to expect deletion and audio cleanup; add a revision-draft sibling-preservation case.
- [ ] Run the two focused tests and observe RED from `daily_report_must_be_archived_for_purge`.
- [ ] Allow `draft` purge targets and return a read-only preflight failure if a draft has descendants.
- [ ] Reparent draft successors directly while retaining durable transitions for archived successors.
- [ ] Replace the 0030 delete guard in 0032 so only trashed archived/draft rows can be deleted; restore the old guard on downgrade.
- [ ] Run focused purge, SQLite migration, static PostgreSQL SQL, and isolated PostgreSQL acceptance tests GREEN or with the established environment skip.

### Task 2: Persist the revision high-water mark

**Files:**
- Create: `migrations/versions/20260719_0032_daily_report_revision_counters.py`
- Modify: `src/newsradar/db/models.py`
- Modify: `src/newsradar/daily_reports/repository.py`
- Create: `tests/daily_reports/test_revision_counter_migration.py`
- Modify: `tests/daily_reports/test_purge_runtime.py`

**Interfaces:**
- Produces: `DailyReportRevisionCounterRecord(report_date, window_hours, highest_revision)`.
- Preserves: next revision equals `max(persisted high-water, extant max) + 1`.

- [ ] Add migration/model contract and existing-data backfill tests, plus purge-highest-then-revise regression.
- [ ] Run those tests and observe missing table/model and reused revision RED results.
- [ ] Add Alembic revision `20260719_0032` with cross-dialect backfill and downgrade protection when dropping the table would lose a watermark.
- [ ] Lock PostgreSQL report writes around both backfill and downgrade watermark checks.
- [ ] Advance the counter after the new report row flush and within the same transaction; never delete it during purge.
- [ ] Run migration, repository, and purge tests GREEN.

### Task 3: Reuse the concurrent service winner

**Files:**
- Modify: `tests/daily_reports/test_service.py`
- Modify: `src/newsradar/daily_reports/repository.py`
- Modify: `src/newsradar/daily_reports/service.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/daily_report_detail.html`
- Modify: `tests/web/test_daily_report_pages.py`

**Interfaces:**
- Preserves: `daily_report_revision_chain_changed` for a newly archived head.
- Produces: active draft reuse when the locked head changed only because another request won creation.
- Produces: an allowlisted detail notice when the revise route opens an existing active draft.
- Produces: an explicit persisted Chinese diagnostic for legacy archived-snapshot fallback.

- [ ] Add a deterministic service race test that creates but does not archive the winning draft during materialization.
- [ ] Run it and observe `daily_report_revision_chain_changed` RED.
- [ ] Return the locked active draft before applying the stale archived-source check.
- [ ] Add an allowlisted `current_revision_draft` redirect notice without reflecting arbitrary query text.
- [ ] Persist the legacy overview fallback diagnostic in `generation_summary`.
- [ ] Run winner-reuse, stale-archived-chain, fallback-diagnostic, and web notice tests GREEN.

### Task 4: Recover recognized SQLite restore uniqueness races

**Files:**
- Modify: `tests/daily_reports/test_retention.py`
- Modify: `src/newsradar/daily_reports/repository.py`

**Interfaces:**
- Produces: existing `RetentionActionResult(..., "blocked", ...)` after a recognized restore winner race.
- Preserves: unrelated integrity failures propagate.

- [ ] Add a deterministic commit-race regression around the real restore path and recognized SQLite constraint metadata.
- [ ] Run it and observe the leaked `IntegrityError` RED.
- [ ] Extract conflict lookup, catch only `_is_revision_conflict`, rollback/reload/requery, and return blocked only when a winner exists.
- [ ] Run focused retention and PostgreSQL acceptance tests GREEN or with established environment skip.

### Task 5: Verify and commit

- [ ] Run all focused daily-report migration/repository/service/retention/purge/web tests.
- [ ] Verify Alembic reports the single head `20260719_0032`.
- [ ] Run Ruff on changed Python files and `git diff --check`.
- [ ] Inspect the diff and commit the exact repair files in one focused commit.
