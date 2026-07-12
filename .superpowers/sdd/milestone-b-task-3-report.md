# Milestone B Task 3 Report

Implemented attributed discovery ingestion for GDELT and Google News.

- `OriginResolver` uses redirect-only streaming GET requests, never consumes article bodies,
  caps chains at five hops, and rejects loops, HTTP redirects, local/private addresses, and
  unresolved publisher destinations.
- `GdeltFetcher` produces URL-stable discovery records, preserves language and observation time,
  and leaves ambiguous or missing publisher attribution unresolved.
- `GoogleNewsFetcher` parses configured RSS topic/query feeds, retains the Google discovery URL,
  and uses a resolved publisher URL only when redirect resolution succeeds.
- `FetcherFactory` selects both adapters for their registered endpoints.

Verification completed on 2026-07-11:

```text
uv run pytest tests/ingestion/test_origin_resolver.py tests/ingestion/fetchers/test_gdelt.py tests/ingestion/fetchers/test_google_news.py -q
11 passed

uv run ruff check .
All checks passed!

uv run pytest
252 passed, 4 warnings in 9.88s
```

The full-suite warnings originate in third-party FastAPI/Starlette and Alembic deprecations.
