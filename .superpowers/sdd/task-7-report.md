# Task 7 report — Chinese event intelligence web

## Delivered

- Replaced `/` with the recent, confirmed-event home and preserved the prior source dashboard at `/sources`.
- Added `/events`, `/events/{id}`, and `/emerging` read views backed by a read-only `EventQueryService`.
- Event pages show Chinese summaries, status separation, heat/score reasons, original evidence links, evidence roles, timeline timestamps, algorithm version, and a MiniMax fallback banner.
- Added safe POST entry points for building, reclustering, enriching, excluding, merging, and splitting events. They call the existing one-time-token/origin checks and only enqueue durable operations with `actor: web` in scope.
- Added event query and route tests; updated source-dashboard tests for its new `/sources` URL.

## Verification

- `uv run pytest tests/web/test_event_queries.py tests/web/test_event_routes.py tests/web/test_routes.py tests/web/test_security.py -q` — 53 passed.
- With `.env` hidden and restored: `uv run pytest -q` — passed (two existing skips).
- `uv run ruff check .` — passed.

## Note

No browser server was launched for this subtask; coverage is browser-ready template and route testing. The web process imports no HTTPX or MiniMax client and event writes stay in the durable operation boundary.
