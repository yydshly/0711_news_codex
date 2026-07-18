# Daily Automation Final Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the final review blockers around archived-report purge safety, scheduled/manual autopilot conflicts, and recycle-bin ordering.

**Architecture:** Keep archived content immutable while allowing only the deterministic retention transitions needed to splice a trashed revision out of a chain and delete its parent row. Purge will complete and flush all guarded database mutations, verify the report was actually deleted, and only then unlink validated synthetic audio paths before committing. A scheduled tick encountering an incompatible active manual run will leave the schedule due and return a nonfatal deferred result so the Worker continues consuming operations.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, SQLite migration/runtime tests, generated PostgreSQL PL/pgSQL assertions, pytest, Ruff.

## Global Constraints

- Strict TDD: every behavior change must first fail for the expected reason.
- Tests use only disposable SQLite databases, synthetic records, and synthetic audio files.
- PostgreSQL coverage inspects generated migration SQL without connecting to a real database.
- Do not access `.env`, user reports, external sources, or MiniMax.
- Commit only the focused fixes, tests, plan, and final report; do not stage review diff packages.

---

### Task 1: Archived purge trigger and side-effect safety

**Files:**
- Modify: `migrations/versions/20260718_0029_daily_automation_retention.py`
- Modify: `src/newsradar/daily_reports/purge_runtime.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/daily_reports/test_automation_migration.py`
- Modify: `tests/daily_reports/test_purge_runtime.py`

**Interfaces:**
- Consumes: existing `DailyReportPurgeHandler` operation lease contract and 0023 archive guards.
- Produces: deterministic archived revision reparenting and verified DB-first purge with delayed audio unlink.

- [ ] Add a migrated-SQLite regression that archives a populated report, trashes it, adds synthetic audio, runs the real purge handler, and asserts report/items/audio rows and file are removed together.
- [ ] Add regressions proving failed guarded DB deletion leaves synthetic audio intact, a trashed draft is rejected before side effects, forbidden archived item/content mutations remain blocked, and a populated archived revision chain is reparented successfully.
- [ ] Add PostgreSQL SQL-capture assertions for `RETURN OLD` on DELETE and the narrow archived reparent allowance.
- [ ] Run the focused tests and record the expected RED failures.
- [ ] Change 0029 guards so ordinary archived mutation remains blocked, report DELETE is allowed only when archived and trashed, and the sole archived reparent exception replaces a trashed predecessor with that predecessor's own parent.
- [ ] Reorder purge SQL to detach references, delete and verify the report, remove residual owned rows for non-FK-cascade SQLite connections, flush all guarded work, then unlink audio and commit.
- [ ] Run focused migration/purge tests to GREEN.

### Task 2: Nonfatal scheduled/manual autopilot conflict

**Files:**
- Modify: `src/newsradar/daily_reports/automation_service.py`
- Modify: `tests/daily_reports/test_automation_service.py`
- Modify: `tests/web/test_cli.py`

**Interfaces:**
- Consumes: `active_daily_autopilot_exists` from `DailyAutopilotRepository.create_run`.
- Produces: `DailyAutomationTickResult(outcome="deferred")` with the schedule date left unmarked.

- [ ] Add a service regression with an active manual 48-hour run at the 24-hour scheduled tick; assert no scheduled run is created, `last_scheduled_date` remains unset, and the result is deferred.
- [ ] Add a Worker regression proving operation consumption still occurs after that scheduled conflict.
- [ ] Run both tests and record RED.
- [ ] Narrowly catch only `active_daily_autopilot_exists`, commit any retention sweep, return deferred, and leave the due schedule unmarked for a later retry.
- [ ] Run service/CLI tests to GREEN.

### Task 3: Recycle-bin ordering

**Files:**
- Modify: `src/newsradar/web/daily_report_queries.py`
- Modify: `tests/daily_reports/test_retention.py`

**Interfaces:**
- Produces: recycle-bin rows ordered by `purge_after ASC`, with stable ID ordering and null deadlines last.

- [ ] Add reports whose deletion order differs from their purge deadlines and assert ascending purge order.
- [ ] Run the test and record RED.
- [ ] Change the query ordering to ascending purge deadline with a stable tie-breaker.
- [ ] Run the retention tests to GREEN.

### Task 4: Verification, report, and scoped commit

**Files:**
- Create: `.superpowers/sdd/daily-automation-final-fixes-report.md`

**Interfaces:**
- Produces: reproducible RED/GREEN evidence, full focused verification, lint evidence, and one scoped commit.

- [ ] Run all affected migration, purge, automation, CLI, and retention suites.
- [ ] Run the full relevant daily-automation/operations/web suite.
- [ ] Run Ruff on every changed Python file and `git diff --check`.
- [ ] Review the final diff for trigger safety, filesystem ordering, no real data, and untracked review-package exclusion.
- [ ] Write the final fixes report with requirement-by-requirement evidence.
- [ ] Stage only scoped files and create one commit.
