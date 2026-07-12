# Milestone B / Task 2 Report

Implemented bounded public social fetchers without persistence, cookies, arbitrary URLs, or HTML page requests.

## Delivered

- `BlueskyFetcher` permits only the public AppView author-feed, feed, and search-post endpoints with a configured actor/feed/query. It preserves DID/handle, AT URI plus CID identity, thread root, metrics, cursors, and returns an explicit partial result when approved search is degraded.
- `MastodonFetcher` permits configured account timelines and explicitly local public timelines only. Status IDs are instance-qualified; pagination, metrics, content warnings, deleted statuses, per-instance rate limiting, and shared per-host policy limits are covered.
- `FetcherFactory` registers both fetchers.

## Verification

- `uv run pytest tests/ingestion/fetchers/test_bluesky.py tests/ingestion/fetchers/test_mastodon.py -q` — 9 passed.
- `uv run pytest -q` — passed (existing FastAPI and Alembic deprecation warnings only).
- `uv run ruff check .` — all checks passed.
- `git diff --check` — passed.

## Scope preservation

The pre-existing unstaged formatting change in `tests/ingestion/test_normalization.py` was not staged or modified.

## Review follow-up

- Bluesky pagination treats `FetchState.cursor` as the opaque AppView token it is: requests always return to the configured endpoint and add it as the `cursor` query parameter.
- Both public social adapters remove Cookie, Authorization, Proxy-Authorization, API-key, token, secret, credential, and `X-Auth-*` configured headers before making a request.
- Mastodon pagination URLs must retain the configured scheme, host, effective port, and timeline path. Alternate ports are rejected.
- Follow-up verification: 13 focused social-fetcher tests passed; full pytest, Ruff, and `git diff --check` passed (only existing dependency deprecation warnings).
