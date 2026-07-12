# Milestone A, Task 3 — Raw-item persistence

## Result

Implemented `RawItemRepository` with immutable write results, content snapshots,
observation-only updates, source-local identity conflict handling, audit records,
and idempotent duplicate-candidate creation.

## RED / GREEN evidence

- RED: `uv run pytest tests/ingestion/test_repository.py -q` failed during collection
  with `ModuleNotFoundError: No module named 'newsradar.ingestion.repository'` after
  the repository tests were added.
- GREEN: `uv run pytest tests/ingestion/test_repository.py -q` passed: **9 passed**.

## Verification

- `uv run pytest` passed: **187 passed, 4 warnings** in 6.12s. The warnings are
  existing FastAPI/Starlette and Alembic deprecations.
- `uv run ruff check .` passed: **All checks passed**.
- `git diff --check` passed.

## Changed files

- `src/newsradar/ingestion/repository.py`
- `tests/ingestion/test_repository.py`

## Self-review

- `ItemWriteResult` is frozen and exposes only the required ID, action and error code.
- Content hashing intentionally excludes engagement, so engagement changes update the
  observation without producing a snapshot.
- Conflicting same-source external-ID and canonical-URL matches are skipped and never
  merged. The database external-ID uniqueness constraint remains the final insert
  concurrency guard; its collision is recovered as an observation.
- Savepoints isolate per-item writes and failures are audit-recorded, allowing later
  items to continue.
- Duplicate candidates are stored with deterministic pair ordering and checked before
  insert, making repeated canonical and title matches idempotent.
