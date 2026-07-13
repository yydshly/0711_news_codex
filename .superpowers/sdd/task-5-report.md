# Task 5 report — generic acquisition research probes

## RED / GREEN

- RED: added protocol-boundary tests for feed, API auth, sitemap robots failure, static HTML, and library metadata. The first run failed during collection because the five generic probe modules did not exist.
- GREEN: implemented bounded read-only probes and a factory. The targeted five tests then passed.

## Implementation

- Added distinct RSS/Atom/WebSub, public/API capability, sitemap, static HTML/JSON-LD/OpenGraph, and library/aggregator paths.
- Every CLI HTTP client is `trust_env=False`; generic probes pass no cookies, authorization, or candidate headers. Existing `HttpPolicy` enforces the 2 MB response cap.
- Sitemap checks `robots.txt`; a 5xx or explicit access denial stops content probing. Results retain `terms_review_required`.
- HTML has no fetcher: it parses supplied static markup only and has no JavaScript or browser capability.
- API-key/OAuth candidates return `blocked` before any request. Library probes are metadata-only and do not network.
- CLI now dispatches non-YouTube candidates, supports `--no-persist`, and degrades to an in-memory result if persistence is unavailable. It does not mutate YAML, source status, ingestion configuration, events, or model state.

## Verification

`uv run ruff check src/newsradar/research/probes src/newsradar/cli.py tests/research/probes` passed.

`uv run pytest tests/research/probes tests/acceptance/test_nonblocking_web.py tests/test_cli.py -q` passed: 45 tests. The run emitted only the pre-existing FastAPI/Starlette httpx deprecation warning.

## Self-review / remaining concern

The generic probe target is deliberately the candidate's reviewed evidence URL, because the schema does not expose a separate unreviewed endpoint. Static HTML probes require markup supplied by a caller and intentionally do not issue a production-style HTML request. The optional one-argument factory creates a `trust_env=False` client for direct programmatic use; CLI supplies and closes its own client.

## Follow-up security remediation

- RED: private-loopback and approval-auth feed tests failed because generic probes delegated to the broad ingestion policy and treated access errors as ordinary failures.
- GREEN: `safe_http.py` now owns probe network preflight. It rejects non-HTTPS/userinfo/local and non-global DNS targets, rejects polluted clients, disables implicit redirects, validates every redirect hop, enforces the 2 MB limit, and always closes streamed responses. Mock transports are exempted from DNS only so unit tests do not depend on external resolution.
- Feed and sitemap now use this path; all non-`none` authentication candidates block before any request. Sitemap additionally checks wildcard robots disallow rules and treats robots 5xx as a hard stop.
- Factory selection now uses `source.provider_id == "youtube"`, rather than a candidate-key prefix.

Follow-up verification: `uv run pytest tests/research/probes/test_security.py tests/research/probes/test_feed.py tests/research/probes/test_sitemap.py -q` passed (4 tests).
