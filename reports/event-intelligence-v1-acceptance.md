# Event Intelligence v1 — Final Acceptance

Date: 2026-07-12

Verified code head: `e6ab5a871a968f2b602cb0510dd5cf22aac23604`

Report snapshot commit: `REPORT_SNAPSHOT_COMMIT` (report-only child of the verified code head).
A metadata-only successor records that snapshot hash because a Git commit cannot embed its own
object ID in its contents.

Database revision: `20260712_0008 (head)`

## Current result

Event Intelligence v1 is accepted at the verified code head. The deterministic pipeline, optional
MiniMax enrichment, durable Worker operations, immutable publication, audited evidence projection,
manual event actions, and Chinese event views are covered by the automated and recorded evidence
below.

The final closure review is resolved:

- weak clustering cannot merge two same-organization, same-action, same-day stories unless they
  also share a compatible object entity; immutable URL/repository/paper identity, exact title
  fingerprint, or a shared audited upstream root remains a strong match;
- `event_recluster` reconstructs active RawItems, reruns current clustering, persists candidate
  memberships, publishes changed membership versions, creates split-off events, and creates no
  version when membership is unchanged;
- `event_enrich` builds bounded current context, closes the read session, invokes MiniMax with no
  Event lease or SQLAlchemy session open, then claims a short publication lease, persists bounded
  provenance best-effort, and publishes a model or deterministic fallback enrichment;
- `duplicate_root_suppressed_count` is calculated from independent-eligible
  `EvidenceAssessment.root_evidence_key` duplicates instead of a constant.

## Final automated gate

The project `.env` was moved to a same-directory backup inside `try/finally` and restored
immediately after the suite, preventing optional local credentials from changing credential-absence
tests.

```text
uv run pytest
476 passed, 3 skipped, 8 warnings in 21.07s

uv run ruff check .
All checks passed!

uv run alembic current
20260712_0008 (head)

uv run alembic check
No new upgrade operations detected.

git diff --check
exit 0
```

The eight warnings are third-party FastAPI/Starlette and Alembic deprecation warnings; the gate has
no test failures or project lint violations.

Focused semantic coverage includes false-cluster protection, strong title/root identity,
anchor-stable candidate identity, real recluster split and no-change behavior, model-free
transaction boundaries, enrichment success/fallback provenance, merge dual-lease cleanup, and
actual duplicate-root counting. The Worker/web/acceptance regression command also completed with
no failures:

```powershell
uv run pytest tests/events tests/operations `
  tests/web/test_event_routes.py tests/web/test_event_queries.py `
  tests/acceptance/test_event_web_worker_flow.py `
  tests/acceptance/test_event_postgres_contention.py `
  tests/acceptance/test_event_model_degradation.py -q
```

## Recorded live operations

These are the latest recorded live PostgreSQL Worker runs. They predate the verified code head and
are retained as operational evidence, not represented as a new live run of `e6ab5a8`.

| Operation | Window | Relevant / candidates | Event IDs / new versions | Duration | Retry | Duplicate root | Model fallback |
| ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 112 | 24h | 2 / 2 | 10, 11 / 2 | 625 ms | 0 | 0 | 2 |
| 113 | 24h | 2 / 2 | 10, 11 / 0 | 375 ms | 0 | 0 | 0 |
| 114 | 24h | 2 / 2 | 10, 11 / 0 | 562 ms | 0 | 0 | 0 |

All three operations succeeded. Operations 113 and 114 demonstrate replay without duplicate
versions. Operation 108 remains the recorded no-key run: it succeeded with IDs 1 and 2, created no
new version, and recorded no model run. Current automated coverage separately proves no-key and
model-failure fallback publication.

The earlier acceptance-only seven-day operation 107 processed 9 relevant items/candidates,
published IDs 1 through 9 with 7 new versions, and produced 2 confirmed plus 7 emerging events. It
did not establish all four product categories from live inputs.

## Reader and recovery evidence

Recorded loopback checks returned HTTP 200 for `/`, `/events`, `/emerging`, `/events/1`, and
`/operations/104`; event detail retained original-link traceability. Current automated route tests
cover the same reader projections and audited enqueue-only web action boundary.

The PostgreSQL contention acceptance test covers expired Event lease recovery. Runtime tests cover
ascending dual-lease acquisition, reverse release, partial-claim cleanup, and timeout cleanup.
Pipeline and manual-enrich instrumentation prove MiniMax invocation occurs with no pipeline-created
SQLAlchemy session and no Event publication lease held.

## Current limitations

- The recorded live corpus did not prove all four target categories; deterministic fixtures cover
  product/model, research, developer-tool, and company classification.
- No new external-source or paid MiniMax live run was executed at `e6ab5a8`; final closure evidence
  for those paths is deterministic automated coverage plus the earlier recorded operations above.
- The suite emits the eight third-party deprecation warnings listed in the final gate.

There are no current known gaps for detached CLI rendering, operation counters, migration-head
expectations, recluster semantics, enrich semantics, model provenance, or duplicate-root counting.
