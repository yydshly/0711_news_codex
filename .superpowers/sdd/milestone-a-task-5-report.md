# Milestone A — Task 5 report

Implemented baseline, persistence-free fetchers for RSS/Atom, Hacker News, GitHub Releases, and arXiv, together with an ingestion orchestration service and CLI operation surface.

- HTTP requests share a bounded HTTPX policy (timeouts/pool, per-host limit, size guard, retry handling).
- RSS sends validators and handles 304 without parsing article pages. HN only calls the audited Firebase endpoints. GitHub only accepts audited `/repos/{owner}/{repo}/releases` endpoints. arXiv only calls the Atom API; no PDF fetches occur.
- Fixture coverage: RSS malformed entry and 304; HN dead-item filtering; GitHub release filtering and 304; arXiv authors/version extraction. All fixtures use `respx`; no live networking.
- Service evaluates eligibility before network, performs network before writes, persists item writes in bounded commits, and avoids all RawItem/cursor writes for dry runs.
- CLI supplies `fetch`, `operations list/show/retry`, and `worker`/`serve` help.

Verification (2026-07-11):

- `uv run pytest tests/ingestion/fetchers -q`: 6 passed.
- `uv run ruff check .`: passed.

## Advisory-lock and source-isolation follow-up (2026-07-11)

- PostgreSQL advisory locking now checks out a dedicated SQLAlchemy `Connection` for the entire source-fetch lifetime. `pg_try_advisory_lock` and `pg_advisory_unlock` execute on that same connection; each lock statement is rolled back before network work so no database transaction or row lock spans HTTP. The connection is released in `finally`, including persistence failures.
- Bounded CLI fan-out now converts unexpected per-source processing failures into failed source summaries, allowing the remaining sources to complete.
- Focused regression evidence: lock connection affinity and persistence-exception release; batch isolation with one failing and one successful source.

Verification after follow-up:

- `uv run pytest tests/test_cli.py tests/ingestion/test_service.py -q`: 19 passed.
- `uv run pytest -q`: 221 passed (same FastAPI/Alembic deprecation warnings).
- `uv run ruff check .`: passed.
- `uv run pytest -q`: 213 passed (with pre-existing FastAPI/Alembic deprecation warnings).

Known limitation: this is the four baseline open-source integrations only; it does not claim coverage of the complete source universe.

## Review remediation (2026-07-11)

- State reads now roll back their implicit SQLAlchemy transaction before the fetcher is awaited; the regression test asserts the Session has no active transaction at the network boundary.
- CLI fetches are now approved-only by default. A non-approved explicit source needs `--one-off`, prints risk/impact, and requires interactive confirmation.
- GitHub consumes a stored pagination cursor, retains prereleases with a `release_state` marker, and still excludes drafts.
- HTTP response guarding now checks `Content-Length` before reading and bounds streamed chunks while reading.
- CLI source execution is bounded to four independent Session-owned tasks so one source cannot leave transaction state shared with another.
- PostgreSQL source advisory locks use session-level advisory lock calls, with transaction cleanup around lock operations.
- Added fixture/service/CLI regressions: transaction ordering, dry run persistence prohibition, prerelease/cursor, size guard, and one-off confirmation.

Verification after remediation:

- `uv run pytest tests/ingestion/test_service.py tests/ingestion/fetchers tests/test_cli.py -q`: 24 passed.
- `uv run pytest -q`: 219 passed (same FastAPI/Alembic deprecation warnings).
- `uv run ruff check .`: passed.
