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

## Review-fix follow-up

- Added regression coverage for meaningful identity changes, including later canonical
  fallback lookup against the refreshed URL and title identity fields.
- Candidate detection is now cross-source only, examines exact and near titles through
  `title_similarity()` at the 0.9 threshold, and runs after inserts and meaningful
  updates. Same-source duplicate-like records are explicitly rejected as candidates.
- Replaced the synthetic failure check with a SQLite trigger that raises a real
  `IntegrityError` inside the upsert savepoint; the failure is audited, an earlier
  committed item remains, and a later item persists.

### Review RED / GREEN evidence

- RED: focused repository tests failed in the new regressions before the fix (5
  failures): stale canonical identity, same-source candidate creation, missing
  near-title/updated-title candidates, and the forced-failure row being matched by the
  original canonical URL.
- GREEN: `uv run pytest tests/ingestion/test_repository.py -q` passed: **12 passed**.
- Full verification: `uv run pytest` passed: **190 passed, 4 warnings**; `uv run ruff
  check .` passed: **All checks passed**.

## Candidate-concurrency follow-up

- Candidate insertion now occurs in its own nested savepoint. A unique-key collision
  after the existence check is treated as an already-created immutable candidate, so
  the surrounding raw-item write can commit.
- RED: the forced SQLite duplicate-candidate trigger made the enclosing upsert return
  `failed/write_conflict` before this change.
- GREEN: `uv run pytest tests/ingestion/test_repository.py -q` passed: **13 passed**.
- Full verification: `uv run pytest` passed: **191 passed, 4 warnings**; `uv run ruff
  check .` passed: **All checks passed**.
