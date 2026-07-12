# Event Intelligence v1 final fixes report

Verified implementation commit: `475ee616f41468bda049027563135e1ee5120f07`.

## RED evidence

With `.env` isolated and restored through `try/finally`:

```text
uv run pytest tests/events/test_pipeline.py::test_pipeline_keeps_event_identity_and_source_publication_time_when_new_source_arrives tests/events/test_evidence.py::test_professional_media_citations_of_one_upstream_report_are_not_independent tests/test_cli.py::test_events_build_wait_prints_terminal_status_while_session_is_open -q
FFF
```

The failures proved the missing publication timestamp, member-id identity, attribution handling,
and `events build --wait` option. A second RED run proved that Worker actions were still returning
`unsupported_action` rather than applying their bounded mutation.

## GREEN evidence

```text
uv run pytest tests/events tests/acceptance/test_event_model_degradation.py tests/acceptance/test_event_web_worker_flow.py tests/test_cli.py tests/web/test_event_queries.py tests/web/test_event_routes.py -q
121 passed

uv run pytest -q
459 passed, 3 skipped

uv run ruff check src/newsradar tests
All checks passed!
```

`.env` was absent only for test discovery/execution and was restored immediately afterwards.
No schema migration changed, so a migration roundtrip was not required.

## Delivered

- Event occurrence time uses the earliest source publication time; the deterministic legacy
  fallback is the Unix epoch.
- Event identity uses entity/action/source-date semantics instead of member IDs, so A then A+B
  preserves an Event and versions its memberships.
- The Worker pipeline invokes optional MiniMax enrichment only when configured and always falls
  back to non-null original-title title/summary fields.
- CLI terminal output captures scalar terminal state before session close; `events build --wait`
  is available.
- Attribution-aware evidence avoids treating professional-media citations of one upstream report
  as independent evidence.
- Event operations execute in the Worker with a short event lease and safe release; their target
  and membership constraints remain validated before mutation.
- Pipeline results expose duration, retry, duplicate-root, and model-fallback counters; the
  acceptance note retains the live-data category limitation while documenting deterministic coverage.

## Re-review follow-up

- The pipeline now commits the candidate read/write phase before invoking optional MiniMax HTTP,
  then opens a new short publication session for the event lease and atomic version switch.
- Manual exclude, merge, split, recluster, and enrich routes publish immutable event snapshots
  through `EventRepository.publish_complete_event`; membership removals use the new version number,
  never a sentinel value.
- Deterministic category assignment is applied before candidate persistence.

Fresh isolated verification after the follow-up: `uv run pytest -q` reported `459 passed, 3 skipped`;
`uv run ruff check .` reported `All checks passed!`.

## Provenance and migration follow-up

Production MiniMax calls now capture bounded `ModelUsageRecord` plus linked `EventModelRunRecord`
rows after the model call and alongside the short publication session. Persistence uses savepoints and
is best-effort, so an audit sink error cannot block publishing. `uv run alembic current` reported
`20260712_0008 (head)` and `uv run alembic check` reported no new upgrade operations.
