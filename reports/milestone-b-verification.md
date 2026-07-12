# Milestone B verification

## Catalog and test evidence

`uv run pytest tests/ingestion/test_open_source_matrix.py tests/test_source_universe_catalog.py -q`
ran on 2026-07-11 and passed: 4 tests. The matrix test enforces identity evidence, endpoint
evidence, roles, attribution handling, risk, review date, and ingestion approval for every enabled
open target.

Final quality gates on 2026-07-11: `uv run ruff check .` reported `All checks passed!`; `uv run
pytest` reported `253 passed, 4 warnings in 10.08s`. The four warnings are existing FastAPI/httpx
and Alembic deprecations; no test failed.

## Explicit dry-run evidence

Each command used `--dry-run --max-items 1`; no non-dry-run ingestion command was used.
All six attempts stopped before any adapter request because `DATABASE_URL` was absent. The CLI
requires it while creating its operation record, so these are environment failures, not live-source
successes, and they do not establish endpoint availability.

| Time (America/Los_Angeles) | Adapter / approved target | Outcome | Failure |
| --- | --- | --- | --- |
| 2026-07-11T23:40:14.5977464-08:00 | RSS / `universe-bbc-1` | blocked, exit 1 | `RuntimeError: DATABASE_URL is required for database operations` |
| 2026-07-11T23:40:16.7089426-08:00 | GDELT / `gdelt-ai` | blocked, exit 1 | same database configuration error |
| 2026-07-11T23:40:17.8065473-08:00 | Google News / `google-news-ai` | blocked, exit 1 | same database configuration error |
| 2026-07-11T23:40:18.8155230-08:00 | Hacker News / `hackernews-top` | blocked, exit 1 | same database configuration error |
| 2026-07-11T23:40:19.8140017-08:00 | Bluesky / `bluesky-bsky` | blocked, exit 1 | same database configuration error |
| 2026-07-11T23:40:20.9355953-08:00 | Mastodon / `mastodon-mastodon` | blocked, exit 1 | same database configuration error |

The local PostgreSQL bootstrap was also attempted, but `newsradar db status` reported that
PostgreSQL command-line tools were unavailable and `POSTGRES_HOME` must be configured. Re-run the
same dry-run commands after providing a project database; record the returned outcome without
reclassifying a failed endpoint as success.

## Logging safety

`tests/operations/test_logging.py` exercises correlation-ID binding and credential redaction. The
logging contract records a correlation ID and excludes credential fields and full response payloads;
the dry-run attempts above emitted only the local configuration exception, not response content.
