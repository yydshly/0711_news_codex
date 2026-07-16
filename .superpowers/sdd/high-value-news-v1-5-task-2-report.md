# High-value news v1.5 — Task 2 report

## Changes

- Added Alembic `20260716_0020` for `high_value_wave_members`, with immutable member snapshot columns, foreign keys, unique `(operation_run_id, source_id)` constraint, and operation/state index.
- Added `HighValueWaveMemberRecord`, `OperationType.HIGH_VALUE_NEWS_WAVE`, and `WaveRepository` for snapshot creation, ordered reads, row-locked claim, attempt-fenced finish, and exactly-once progress advancement.
- Added `OperationCommandService.enqueue_high_value_wave`. It freezes `window_end`, event algorithm versions, deadline, profile digest, and member snapshots inside one transaction. PostgreSQL uses a transaction advisory lock and active waves reject a second enqueue.
- Added coverage for migration history preservation, schema enum, atomic freeze/rollback, active-batch protection, uniqueness, blocked member snapshots, and stale claim fencing.

## TDD evidence

- RED: `uv run pytest tests/test_migrations.py tests/waves/test_repository.py tests/operations/test_commands.py tests/operations/test_schema.py -q` failed during collection because `HighValueWaveMemberRecord` and `newsradar.waves.repository` did not exist.
- GREEN: the same command passed with `33 passed` (Alembic emitted 18 pre-existing configuration deprecation warnings).

## Verification

- `uv run ruff check ...` passed.
- `git diff --check` passed.
- PostgreSQL advisory lock follows the existing catalog-refresh guarded implementation. No live PostgreSQL fixture was configured in this worktree, so acceptance-level contention was not run.

## Scope and risks

- No network calls, credential reads, RawItem changes, EventPipeline changes, or Task 3+ changes were made.
- Correction: the prior description of `blocked` members as terminal snapshots is obsolete. Non-fetchable members are persisted as `pending` snapshots with `fetchable=false` and the frozen planner reason; Task 3 claims them, performs no network I/O, and finishes them as `blocked` exactly once.

## Commit

- Task-only commit: `feat: persist frozen high-value waves`.

## Review fix

- Review found that non-fetchable members were stored as `blocked` before a Worker could claim or complete them, leaving operation progress permanently below `progress_total`.
- Member creation now persists every snapshot as `pending`; non-fetchable members retain `fetchable=false` and the frozen blocked reason in `conclusion`. Task 3 can claim them and finish them as `blocked` without network I/O, advancing progress exactly once.
- Claims and finishes now require a positive `claim_attempt_id`; finish also requires that the persisted claimant matches, so a caller cannot bypass the operation-attempt fence.
- TDD RED: the new blocked-member tests failed because records started as `blocked` and invalid/missing attempt ids were accepted. GREEN: `tests/waves/test_repository.py tests/operations/test_commands.py` passed after the minimal repository change.
- Recheck: `uv run pytest tests/waves/test_repository.py tests/operations/test_commands.py -q` passed: `28 passed`.
