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

## Closure audit after `f37329e`

Pipeline instrumentation now observes the production MiniMax adapter boundary directly. During
adapter invocation, the pipeline-created SQLAlchemy session set is empty and the existing Event has
no processing lease. The same test observes `EventRepository.claim_event` only after the adapter
returns, and verifies the lease is released after publication.

Dedicated pipeline-level provenance tests cover successful and fallback `ModelUsageRecord` writes,
their linked `EventModelRunRecord` rows, event-detail `model_versions` projection, and a forced
database sink exception that still publishes a complete reader-visible event. These are production
pipeline/repository/query paths; only the external model result is controlled.

The `f37329e` deadline test initially failed with `NameError: scope is not defined`; its scope had
been placed inside another test. After correcting that test, a new RED case showed that a deadline
crossed after both merge leases were claimed released the leases but re-raised `OperationTimedOut`.
The handler now returns terminal `operation_timeout` after rolling back and releasing in that case.
Targeted tests also prove sorted dual-lease acquisition, reverse release, and release of the first
lease when the second claim fails. `tests/events/test_runtime.py` reported 10 passed.

### Full-suite diagnosis

A verbose redirected run with the local `.env` present did not hang. Process 37196 advanced through
the suite and exited after 24.00 seconds with 467 passed and one failure:
`test_reddit_probe_blocks_without_oauth_credentials`. The local `.env` provides the optional Reddit
OAuth configuration, contradicting that test's credential-absence premise. No pytest process was
left running. A PostgreSQL activity snapshot then showed 14 idle client backends, all with null
`xact_start`; no ungranted locks existed. PostgreSQL was not blocking the run.

The clean verification moved `.env` to a same-directory backup inside `try/finally`, restored it
immediately, and ran `uv run pytest`: 468 passed, 3 skipped in 23.13 seconds (471 collected).
No timeout was added. Fresh gates also reported:

```text
uv run ruff check .       -> All checks passed!
uv run alembic current    -> 20260712_0008 (head)
uv run alembic check      -> No new upgrade operations detected.
git diff --check          -> exit 0
```

## Final closure review

Verified code head: `e6ab5a871a968f2b602cb0510dd5cf22aac23604`.

RED tests demonstrated four remaining defects: same-organization/action/time merged distinct model
objects; a shared upstream root did not form a strong match; recluster/enrich returned success for
snapshot no-ops; and the duplicate-root summary remained zero for two independent-eligible items
with one root.

The final implementation now:

- requires a shared product/model/paper/dataset/project entity for weak entity/action matches,
  while retaining immutable identity, exact title fingerprint, and common upstream-root matches;
- anchors candidate identity to the earliest durable member's immutable content identity, so later
  coverage does not rename an existing event;
- runs recluster against reconstructed active RawItems, persists recomputed candidate membership,
  versions only changed target membership, and publishes deterministic split-off events;
- runs manual enrichment outside every SQLAlchemy session and Event lease, then claims a short
  publication lease, versions changed enrichment, persists `ModelUsageRecord` and
  `EventModelRunRecord` rows best-effort, and releases safely on deadline/error;
- derives duplicate-root suppression from the actual independent `EvidenceAssessment` roots.

Fresh verification at that code head:

```text
focused Worker/web/acceptance regression -> exit 0
uv run pytest                            -> 476 passed, 3 skipped in 21.07s
uv run ruff check .                      -> All checks passed!
uv run alembic current                   -> 20260712_0008 (head)
uv run alembic check                     -> No new upgrade operations detected.
git diff --check                         -> exit 0
```
