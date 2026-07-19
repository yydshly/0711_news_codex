# Daily Report Final Review Remediation Plan

> Scope: resolve the verified blocking findings from the final branch review without
> expanding into archive pagination, retention UX, source probing, or real audio calls.

## Decisions

- Historical revision links continue to resolve to the latest valid report in that
  revision chain. This is an existing documented contract and must not fork an old report.
- Corrupt operation manifests continue to fail closed. A generic `None` snapshot result is
  not treated as safe archival fallback without a typed absence reason.
- No new source probes, MiniMax calls, or real audio generation are part of remediation.

## Task 8: Linearize Daily Publication and Recover Decision Audio Idempotently

Files:

- `src/newsradar/daily_reports/service.py`
- `src/newsradar/daily_reports/repository.py`
- `src/newsradar/operations/commands.py`
- `src/newsradar/daily_reports/autopilot_runtime.py`
- focused service/command/autopilot tests

Acceptance:

- publication acquires the Shanghai report-day transaction lock before selecting the
  predecessor;
- a different operation cannot create a second active root while the first report is draft;
- after the first report archives, the next operation accumulates from that head across
  24/48/72-hour windows;
- retry after archive+decision-audio commit returns the existing decision audio operation
  instead of failing or enqueueing a duplicate.

## Task 9: Resolve Canonical Merge Graphs and Preserve Audit Rows

Files:

- `src/newsradar/daily_reports/repository.py`
- `src/newsradar/daily_reports/accumulation.py`
- focused repository/accumulation/service tests

Acceptance:

- `3 -> 2 -> 1` resolves every requested identity to `1` independent of row order;
- conflicting edges and cycles fail closed with structured diagnostics;
- a legacy row already visible in a predecessor remains in the successor as a
  `duplicate_confirmed` audit row when the survivor first appears;
- duplicates introduced only within the current operation may still fold into the survivor;
- a newer legacy event version cannot clear an applied event-level merge disposition.

## Task 10: Correct Revision Coverage and Retain Update Degradation Diagnostics

Files:

- `src/newsradar/daily_reports/accumulation.py`
- `src/newsradar/daily_reports/service.py`
- `src/newsradar/web/daily_report_queries.py`
- `src/newsradar/web/templates/daily_report_detail.html`
- focused accumulation/service/page tests

Acceptance:

- revised reports persist counts derived from their final decision and overview rows;
- when persisted valid counts disagree with present rows, present rows win if overview rows
  exist; legacy reports without overview rows retain safe summary fallback;
- a degraded newer version preserves the last complete display item and stores a structured
  attempted-version diagnostic with a Chinese reason and next action;
- the detail page exposes that diagnostic without excluding the still-complete retained item.

## Task 11: Batch Revision Materialization and Bound Canonical Queries

Files:

- `src/newsradar/daily_reports/service.py`
- `src/newsradar/web/event_queries.py` or a lower-level event snapshot materializer
- `src/newsradar/daily_reports/repository.py`
- focused query-count and behavior tests

Acceptance:

- operation snapshot validation occurs once per revision operation, not once per event;
- fixed versions, scores, and evidence are batch-loaded before overview draft construction;
- query count grows by a small bounded constant or linear batch count, not 4-5 queries per
  event plus repeated whole-manifest validation;
- applied merge lookup starts from requested event IDs and expands only the reachable
  frontier rather than loading all historical applied candidates;
- output remains identical for confirmed, emerging, missing-detail, and degraded items.

## Task 12: Verification and Final Review

- focused suites after each task;
- Ruff and `git diff --check` after each task;
- one final milestone target suite, `ruff check src tests`, `alembic heads`, and full pytest;
- repeat isolated 8/2/8/6 web acceptance without real audio;
- final independent review of the remediation range and full branch.

