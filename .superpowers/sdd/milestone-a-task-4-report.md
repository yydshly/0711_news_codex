# Milestone A, Task 4 — Operations Runtime Report

## RED

Added repository, worker, and logging tests before implementation. The first focused run failed during collection because the new operations modules did not exist. A subsequent focused run exposed queue readiness comparing application time with database `now()`; enqueue/retry scheduling was changed to database time.

## GREEN

Focused verification:

```text
10 passed in 0.46s
```

Coverage includes FIFO-ready selection, PostgreSQL `SKIP LOCKED` compilation, lease heartbeat renewal, expired-lease reclaim, three-attempt cap, cancellation and terminal immutability, handler checkpoints, uncaught-exception event scrubbing, JSONL output, and rotation/redaction.

## Full verification

```text
202 passed, 4 warnings in 5.74s
ruff check .: All checks passed!
git diff --check: clean
```

The four warnings are pre-existing dependency/configuration deprecations from FastAPI/Starlette and Alembic.

## Changed files

- `src/newsradar/operations/repository.py`
- `src/newsradar/operations/service.py`
- `src/newsradar/operations/worker.py`
- `src/newsradar/operations/logging.py`
- `tests/operations/test_repository.py`
- `tests/operations/test_worker.py`
- `tests/operations/test_logging.py`

## Self-review

Leasing selects and mutates the queue inside a short nested transaction and uses `FOR UPDATE SKIP LOCKED`; handlers run only after that transaction closes. PostgreSQL lease expiry expressions are anchored to `now()`. Every attempt is represented by a durable attempt row. Failure events and JSON logs run through the same redaction function.

## Concerns

The focused concurrency test validates generated PostgreSQL SQL rather than running two live PostgreSQL workers, because this task's local focused suite uses SQLite. A deployment integration test against the provisioned PostgreSQL service remains worthwhile.
