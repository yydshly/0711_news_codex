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
- `uv run pytest -q`: 213 passed (with pre-existing FastAPI/Alembic deprecation warnings).

Known limitation: this is the four baseline open-source integrations only; it does not claim coverage of the complete source universe.
