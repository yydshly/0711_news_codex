# Task 5 follow-up report

## RED / GREEN

- Added the candidate-only factory and lifecycle regression first. It failed with
  `TypeError: research_probe_for() missing 1 required positional argument: 'candidate'`.
- Added selector schema, extraction, no-selector, redaction, and JavaScript-text tests first.
  They initially failed because `selector` was forbidden and selector text included script text.
- The factory now supports `research_probe_for(candidate)` and the existing
  source-aware form; owned clients are released by `aclose()` or `async with`.
- The research schema accepts only one auditable selector token: a tag, `#id`, or
  `.class`. The static parser extracts text only for that explicit selector,
  excludes script/style content, applies existing recursive redaction, and bounds
  extracted text to 4000 characters. Without a selector it reports generic static
  metadata without selector output.

## YAML

- No source YAML was changed: the existing reviewed sources do not contain a
  verified selector value, so no selector was invented.

## Verification

- `uv run pytest tests/research/probes tests/test_cli.py tests/web/test_cli.py tests/test_source_schema.py tests/test_source_repository.py tests/test_research_schema.py tests/test_research_repository.py tests/test_migrations.py -q`
  — 124 passed (only existing Alembic configuration deprecation warnings).
- `uv run ruff check src tests` — passed.
- `git diff --check` — passed.

## Notes

- Candidate-only construction cannot select a source-specific YouTube probe by
  design; the existing source-aware CLI path continues to provide that routing.
- This remains static, non-production research inspection: no browser, JavaScript
  execution, cookie/login state, proxy, or unaudited headers are introduced.

## Prior Task 5 record

### Original implementation

- Added distinct RSS/Atom/WebSub, public/API capability, sitemap, static HTML/JSON-LD/OpenGraph, and library/aggregator paths.
- Every CLI HTTP client is `trust_env=False`; generic probes pass no cookies, authorization, or candidate headers. Existing `HttpPolicy` enforces the 2 MB response cap.
- Sitemap checks `robots.txt`; a 5xx or explicit access denial stops content probing. Results retain `terms_review_required`.
- HTML has no fetcher: it parses supplied static markup only and has no JavaScript or browser capability.
- API-key/OAuth candidates return `blocked` before any request. Library probes are metadata-only and do not network.
- CLI now dispatches non-YouTube candidates, supports `--no-persist`, and degrades to an in-memory result if persistence is unavailable. It does not mutate YAML, source status, ingestion configuration, events, or model state.

### Prior verification and security remediation

- `uv run ruff check src/newsradar/research/probes src/newsradar/cli.py tests/research/probes` passed.
- `uv run pytest tests/research/probes tests/acceptance/test_nonblocking_web.py tests/test_cli.py -q` passed: 45 tests. The run emitted only the pre-existing FastAPI/Starlette httpx deprecation warning.
- `safe_http.py` owns probe network preflight. It rejects non-HTTPS/userinfo/local and non-global DNS targets, rejects polluted clients, disables implicit redirects, validates every redirect hop, enforces the 2 MB limit, and always closes streamed responses. Mock transports are exempted from DNS only so unit tests do not depend on external resolution.
- Feed and sitemap use this path; all non-`none` authentication candidates block before any request. Sitemap additionally checks wildcard robots disallow rules and treats robots 5xx as a hard stop.
- Factory selection uses `source.provider_id == "youtube"`, rather than a candidate-key prefix.
- Follow-up verification: `uv run pytest tests/research/probes/test_security.py tests/research/probes/test_feed.py tests/research/probes/test_sitemap.py -q` passed (4 tests).

### Prior evidence closeout

- HTML/JSON-LD/embedded-JSON candidates use the same bounded `safe_get` path for reviewed static pages and `robots.txt`; no JavaScript, browser, cookies, credentials, or production fetcher was added.
- The probe result exposes HTTP status/final URL/latency/cache/rate-limit/latest timestamp/fields/completeness/schema/pagination/block condition evidence. CLI maps persisted columns directly while retaining sanitized details.
- No migration was required: the existing acquisition probe-run table already has HTTP, latency, fields, latest-date, fingerprint, error, and sanitized-details columns. Existing migration preservation tests pass.
- Generic probe targets deliberately use the candidate's reviewed evidence URL, because the schema has no separate unreviewed endpoint. The optional one-argument factory creates a `trust_env=False` client for direct programmatic use; CLI supplies and closes its own client.
- Local audited YAML hostnames are allowed after bounded HTTPS request handling; explicit unsafe IP literals and malformed/credentialed URLs remain blocked.
- Controlled checks recorded successful bounded `trust_env=False` responses from hnRSS and Python.org without proxy use.
- Static metadata recursively redacts sensitive nested JSON keys and strips all URL query/fragment values while retaining safe path evidence.
- `AcquisitionProbeSample` strips canonical URL query/fragment at construction and rejects URL userinfo; probe targets reject credential-bearing query keys before `safe_get`.

## Final security hardening

- `safe_http` now rejects caller-owned `httpx.AsyncClient` instances with a non-empty CookieJar before `build_request` can merge cookies.
- Sensitive query keys are parsed with `parse_qsl`, so percent-encoded names such as `access%5Ftoken` and `%74oken` are rejected. The same validator runs for every redirect hop before it is followed.
- Response-derived ETag, Last-Modified, Cache-Control, and feed Content-Type values use a shared bounded header-value sanitizer. URLs, credential-like values, and sensitive `key=value` pairs become `None`; numeric rate-limit remaining is retained.
- Regression coverage confirms no Cookie request is sent, unsafe redirects stop at the first hop, malicious headers do not survive `model_dump`, and probe-run persistence cannot reintroduce them.
- Verification: targeted security/repository tests passed; complete research, CLI, schema, repository, and migration test selection passed; `ruff check` and `git diff --check` passed.

## Final boundary corrections

- `has_sensitive_query` now calls `parse_qsl(..., keep_blank_values=True)`, so bare `?token`, `?token=`, and percent-encoded sensitive parameter names are blocked before the initial request and before every redirect hop.
- Live probe traffic is limited to a fixed User-Agent and Accept allowlist by constructing a standalone `httpx.Request`; caller defaults (including arbitrary `X-Context` and `X-Foo` values) are never merged into probe requests.
- Research factory-owned probes use a registered, closable `trust_env=False` / no-redirect client. Caller clients and transports are rejected for live network work unless they use `MockTransport` for isolated tests; this closes the `AsyncHTTPTransport(proxy=...)` bypass without relying on HTTPX private mount inspection.
- The non-YouTube research CLI path now enters the factory-owned probe context, so it uses and closes that safe client rather than supplying its command-level client.
- Regression tests cover blank/encoded sensitive parameters, redirect locations, default-header non-inheritance, and a caller-supplied proxy transport.
