# Task 3 report — Wave fetch runtime and RawItem idempotency evidence

## Scope delivered

- Added `HighValueWaveHandler` with durable member claim fencing, six-wide global and two-wide provider concurrency, session-free network execution, stale-snapshot checks, blocked-member completion, and per-member terminal persistence.
- Reused the existing ingestion execution path by publishing `execute_production_fetch`; `FetchOperationHandler.production()` and `HighValueWaveHandler.production()` use that same function.
- Registered `high_value_news_wave` in the production Worker router. The Wave runtime does not add any HTTP client, credential, cookie/login, HTML fallback, EventPipeline, or web-page logic.
- The reused `IngestionService` remains the only RawItem/FetchRun writer, preserving its existing idempotency evidence.

## TDD evidence

RED: `uv run pytest tests/waves/test_runtime.py -q` failed with three expected `ModuleNotFoundError: newsradar.waves.runtime` failures before the runtime existed.

GREEN: after the minimal runtime implementation, the same test file passed (`3 passed`).

## Verification

- `uv run pytest tests/waves/test_runtime.py tests/operations/test_fetch_runtime.py tests/operations/test_router.py tests/operations/test_worker.py -q` — `34 passed`
- `uv run pytest tests/test_cli.py -q` — `42 passed`
- `uv run ruff check src/newsradar/waves/runtime.py src/newsradar/operations/fetch_runtime.py src/newsradar/cli.py tests/waves/test_runtime.py tests/operations/test_fetch_runtime.py tests/operations/test_router.py` — passed
- `git diff --check` — passed

## Risk notes

- Network calls run through `asyncio.to_thread` so the synchronous, established production ingestion executor can be reused without nested event loops or a database session retained during I/O.
- A lost member finish claim rolls back and reports `claim_lost`; it never overwrites a newer attempt. Interrupted/cancelled checkpoints propagate to Worker, which records the operation cancellation.
- A member-level fetch error becomes that member's terminal `failed` state; other members continue.

## Commit

Task-local commit: `feat: ingest high-value wave members` (the final SHA is reported in handoff).

## Review remediation

RED → GREEN fixes after independent review:

- A newer operation attempt now atomically reclaims an older `running` member; the previous attempt remains fenced from finish and only the winning finish advances progress.
- `OperationCancelled` is the Worker checkpoint signal. It is re-raised by shared ingestion and the Wave runtime at every broad exception boundary, so Worker persists cancellation instead of an ordinary fetch failure. Tests cover `before_network`, a fetch checkpoint, and `after_item`.
- Expired deadlines terminally finish every scheduled fetchable member as fenced `timeout` without starting new network calls; completed tasks are contained and no `running` member remains.
- Added deterministic thread-barrier concurrency evidence for global <=6 and same-provider <=2, plus 429/member-error isolation and actual CLI Worker mapping coverage.

Remediation verification:

- `uv run pytest tests/waves/test_runtime.py tests/waves/test_repository.py tests/operations/test_fetch_runtime.py tests/operations/test_router.py tests/operations/test_worker.py tests/test_cli.py -q` — `92 passed`
- Task-specific Ruff and `git diff --check` — passed.
