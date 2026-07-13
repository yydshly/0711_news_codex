# Task 3 Report — Chinese trial coverage and status pages

## Scope

- Added dashboard counts for explored, trial-eligible, discovery-only, and restricted targets.
- Added per-target trial label and reason to the target catalog.
- Reused `evaluate_trial_eligibility` for every decision and
  `SourceRepository.latest_probe_snapshot` for persisted probe state.
- Added the required Chinese trial explanation and ensured rendered dashboard and catalog pages
  do not expose `DATABASE_URL`, `Authorization`, or `Cookie`.

## TDD evidence

The inherited broad coverage test already passed before review. A focused regression test was
added to require calls through `SourceRepository.latest_probe_snapshot`; it failed with an empty
call set before the query implementation was changed, then passed after the change.

## Verification

- `pytest tests/web/test_trial_dashboard.py tests/web/test_routes.py tests/web/test_queries.py -q` — 58 passed.
- `ruff check src/newsradar/web/queries.py src/newsradar/web/viewmodels.py tests/web/test_trial_dashboard.py` — passed.
- `git diff --check` — passed.

## Note

`SourceRepository` currently exposes a single-source snapshot API. The web service invokes that
existing canonical API for each displayed source so its snapshot semantics stay centralized;
no policy or snapshot reconstruction logic was copied into the web layer.
