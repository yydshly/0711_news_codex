# Task 6 — Event pipeline on the durable Worker

## Outcome

The durable `Worker` now consumes a single `OperationRouter`. Existing fetch work is
registered under `fetch` without modifying `FetchOperationHandler`; event operation
types are registered with `EventOperationHandler`. Web/CLI command boundaries enqueue
event operations only, so event processing and any future model/network work remain in
the worker process.

`EventPipeline` processes deterministic relevance/entity/cluster/publish stages using
fresh sessions for each bounded database stage. It calls the worker checkpoint before
and after stages and before each publish, preserving cancellation and the worker's
existing heartbeat/lease monitor semantics. Replays compare active event membership and
do not create an additional version when nothing changed.

## RED evidence

Before implementation, ran:

```powershell
uv run pytest tests/events/test_pipeline.py tests/events/test_runtime.py tests/operations/test_router.py tests/operations/test_commands.py tests/test_cli.py -q
```

Result: collection failed as expected with `ModuleNotFoundError` for
`newsradar.events.pipeline`, `newsradar.events.runtime`, and
`newsradar.operations.router`.

## GREEN evidence

After implementation:

```powershell
uv run pytest tests/events/test_pipeline.py tests/events/test_runtime.py tests/operations/test_router.py tests/operations/test_commands.py tests/test_cli.py -q
# 30 passed

uv run pytest tests/events/test_pipeline.py tests/events/test_runtime.py tests/operations tests/acceptance/test_nonblocking_web.py tests/acceptance/test_worker_recovery.py tests/ingestion/test_service.py -q
# 52 passed

uv run pytest -q
# 440 passed, 2 skipped

uv run ruff check src/newsradar tests -q
# passed
```

The full suite ran with `.env` renamed for the duration and restored in a `finally`
block. The only emitted warnings are pre-existing third-party deprecation warnings.

## Delivered interfaces

- `OperationRouter.register()` and callable router dispatch.
- Event operation types: pipeline, recluster, enrich, merge, split, and exclude.
- Event enqueue commands include deadlines, algorithm versions, and deterministic
  idempotency keys.
- `newsradar events build --hours`, `events list`, and `events show`.
- Pipeline replay/idempotency, router dispatch, invalid runtime scope, command scope,
  and Worker CLI compatibility tests.

## Scope note

Event action operation types currently validate their target and return an auditable
worker result. Their editorial mutation semantics are intentionally deferred to the
subsequent event-management task; this task establishes their durable worker route.
