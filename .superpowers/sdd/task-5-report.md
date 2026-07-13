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

## Final evidence and static HTML follow-up

- HTML/JSON-LD/embedded-JSON candidates now use the same bounded `safe_get` path for reviewed static pages and `robots.txt`; no JavaScript, browser, cookies, credentials, or production fetcher was added.
- The probe result now exposes HTTP status/final URL/latency/cache/rate-limit/latest timestamp/fields/completeness/schema/pagination/block condition evidence. CLI maps the persisted columns directly while retaining sanitized details.
- No migration was required: the existing acquisition probe-run table already has HTTP, latency, fields, latest-date, fingerprint, error, and sanitized-details columns. Existing migration preservation tests pass.

Final verification: `uv run pytest tests/research/probes tests/test_cli.py tests/test_research_repository.py tests/test_migrations.py -q` passed (56 tests).

## Local audited-hostname scope adjustment

The prior hostname fail-closed policy was removed. For this single-user, manually audited YAML catalogue, HTTPS hostnames are allowed after DNS resolution confirms every answer is globally routable; HTTPS, userinfo, localhost/private/link-local/reserved addresses, proxies, sensitive client headers, cookies, credentials, redirects and bounded streaming protections remain enforced. A live arXiv RSS attempt was safely blocked in this environment because its resolver returned a non-global address; no request was sent.

This was further aligned with the confirmed local YAML scope: hostname DNS is no longer pre-gated. Explicit unsafe IP literals and malformed/credentialed URLs remain blocked, while actual hostname DNS/network errors are returned by the bounded HTTP request as readable probe failures.

Real controlled network verification (2026-07-12): `https://hnrss.org/frontpage` returned HTTP 200 / 15,751 bytes and `https://www.python.org/` returned HTTP 200 / 52,637 bytes through `safe_get` with `trust_env=False`, explicit redirect handling, and the 2 MB cap.

## Evidence consistency and recursive static-metadata sanitization follow-up

- Added RED/GREEN coverage for API HTTP evidence, result/API sample-count consistency, robots early-return evidence, recursive JSON-LD/embedded JSON/OpenGraph URL sanitization, and gzip-encoded static HTML.
- `AcquisitionProbeResult` now carries `sample_count`, ETag, Last-Modified, and measured bounded-request latency. HTTP-backed success and access/robots blocked results carry sanitized final URL, response status, cache/rate-limit evidence, field summary, latest timestamp, pagination, fingerprint, and Chinese reason. CLI persists the result's own `sample_count` rather than recomputing an independent value.
- Static HTML metadata decodes JSON before recursive sanitization, removes sensitive nested keys, and strips every URL query and fragment while retaining scheme/host/path. Repository detail persistence also strips URL query/fragment; credential-bearing URLs continue to use the existing full-redaction marker.
- Fixed a real controlled HTML regression: `safe_get` consumes decoded streaming bytes, so reconstructed responses now remove stale `Content-Encoding`/`Content-Length` headers and cannot be decoded twice.

Verification (2026-07-12): `uv run ruff check src/newsradar/research/probes src/newsradar/cli.py src/newsradar/sources/repository.py tests/research/probes` passed. `uv run pytest tests/research/probes tests/test_cli.py tests/test_research_repository.py tests/test_migrations.py -q` passed. Real `trust_env=False` probe checks: hnRSS succeeded (HTTP 200, one bounded sample); Python.org static HTML completed partial (HTTP 200) with no JavaScript/browser/credentials.

## Final security closeout

- `AcquisitionProbeSample` now strips every canonical URL query/fragment at model construction and rejects URL userinfo, covering feed/API/Sitemap sample persistence and model dumps.
- Probe targets reject credential-bearing query keys before `safe_get`; HTTP/parse failure paths preserve already-received response evidence through `with_http_evidence`.
- Robots user-agent matching now follows token-prefix semantics, and HTML robots early blocks retain `terms_review_required` like Sitemap.

Verification (2026-07-12): `python -m ruff check src/newsradar/research/probes tests/research/probes` and `python -m pytest tests/research/probes tests/test_cli.py tests/test_research_repository.py tests/test_migrations.py -q` passed (71 tests). A real `trust_env=False` Django RSS probe (`https://www.djangoproject.com/rss/weblog/`) succeeded with HTTP 200 and one bounded sample.
