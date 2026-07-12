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

## Review-fix evidence (2026-07-11)

### Root cause and correction

Review correctly identified that `Session.begin_nested()` creates only a savepoint. The outer implicit SQLAlchemy transaction remained active after `lease_next()` returned, so a worker handler could run with the claim lock transaction still open. The repository now completes any implicit transaction and uses `Session.begin()` around every queue operation; each scope commits before its method returns. The handler regression asserts `Session.in_transaction()` is false from inside the injected handler.

### Added regression coverage

- Claim transaction is closed before the handler executes.
- Injected monotonic clock controls heartbeat timing deterministically.
- Key/value `api_key`, `token`, `password`, `Authorization`, and `Cookie` values are redacted without environment setup.
- Sensitive structured-extra field values are redacted by field name.
- A worker execution JSONL record contains operation, attempt, worker, source, request, and operation-attempt correlation identifiers.

### Review-fix verification

```text
Focused operations: 15 passed in 0.56s
Full suite: 207 passed, 4 warnings in 5.38s
Ruff: All checks passed!
git diff --check: clean
```

The four warnings remain dependency/configuration deprecations from FastAPI/Starlette and Alembic; no test failures or lint findings remain.
