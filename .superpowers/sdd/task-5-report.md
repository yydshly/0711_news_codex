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
