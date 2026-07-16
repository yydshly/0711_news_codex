# Safe Sitemap Discovery Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one credential-free platform-level Sitemap fetcher and use it to validate Ben’s Bites and TLDR AI as discovery-only RawItem sources without fetching article bodies.

**Architecture:** A focused `SitemapFetcher` will parse bounded standard `urlset` XML into existing `NormalizedRawItem` objects and will be selected by the existing `FetcherFactory` for `AccessKind.SITEMAP`. Source activation remains configuration-driven and is allowed only after controlled probes and real Worker FetchRuns prove that each official Sitemap produces usable records.

**Tech Stack:** Python 3.12, httpx, defusedxml, Pydantic, SQLAlchemy, pytest, respx, Ruff, existing News Codex durable operations/Worker stack.

## Global Constraints

- Only request reviewed Sitemap URLs; never fetch article bodies.
- Sitemap records are discovery leads and cannot independently confirm an event.
- Do not use Cookie, login state, CAPTCHA bypass, proxies, HTML scraping, or unofficial/private APIs.
- Reuse `HttpPolicy` for timeout, finite retry, concurrency, response-size and response-header controls.
- Do not send authentication or Cookie headers; trial construction must be explicitly credential-free.
- A malformed entry must not block other entries or another source.
- Do not add Ben’s Bites- or TLDR-specific branches to the fetcher.
- Keep total catalog targets at 187 and preserve the user-owned `sources/aggregators/gdelt-ai.yaml` line-ending-only change.
- Do not push or merge without user confirmation.

---

## File Structure

- Create `src/newsradar/ingestion/fetchers/sitemap.py`: bounded XML parsing and Sitemap-to-`NormalizedRawItem` conversion only.
- Create `tests/ingestion/fetchers/test_sitemap.py`: parser, normalization, isolation and HTTP behavior tests.
- Modify `src/newsradar/ingestion/fetchers/base.py`: route `AccessKind.SITEMAP` to the new fetcher and declare it credential-free.
- Modify `tests/ingestion/fetchers/test_http_policy.py` or add factory assertions to `test_sitemap.py`: verify factory and sensitive-header boundaries.
- Modify `sources/universe/universe-bens-bites-1.yaml` and `sources/universe/universe-tldr-ai-1.yaml` only after their real acceptance result is known.
- Modify `tests/ingestion/test_high_value_mixed_catalog.py`, `tests/research/test_placeholder_resolution_catalog.py`, `tests/web/test_capability_queries.py`, and `tests/test_source_universe_catalog.py`: lock accepted catalog facts and counts.
- Modify `src/newsradar/web/source_conclusions.py` and its tests only if the real failure mode lacks a current Chinese actionable conclusion.

---

### Task 1: Standard Sitemap `urlset` Parser and Normalizer

**Files:**
- Create: `src/newsradar/ingestion/fetchers/sitemap.py`
- Create: `tests/ingestion/fetchers/test_sitemap.py`

**Interfaces:**
- Consumes: `HttpPolicy.get(url, headers=..., params=...)`, `AccessMethod`, `SourceDefinition`, `FetchState`, and `limit: int`.
- Produces: `class SitemapFetcher` with `async fetch(source, method, state, limit) -> FetchResult`.
- Produces: `NormalizedRawItem.raw_payload["title_source"]` equal to `"news_sitemap"` or `"url_slug"`.

- [ ] **Step 1: Write failing tests for standard and News Sitemap records**

```python
@pytest.mark.asyncio
@respx.mock
async def test_sitemap_normalizes_news_title_and_slug_fallback() -> None:
    respx.get("https://site.test/sitemap.xml").mock(
        return_value=httpx.Response(200, content=SITEMAP_WITH_NEWS_AND_STANDARD_URLS)
    )
    async with httpx.AsyncClient() as client:
        result = await SitemapFetcher(HttpPolicy(client)).fetch(
            source(), source().access_methods[0], FetchState(), 10
        )
    assert result.outcome is FetchOutcome.SUCCEEDED
    assert [item.title for item in result.items] == [
        "Official News Title",
        "OpenAI Launches New Model",
    ]
    assert result.items[0].raw_payload["title_source"] == "news_sitemap"
    assert result.items[1].raw_payload["title_source"] == "url_slug"
    assert all(item.summary is None and item.content is None for item in result.items)
```

- [ ] **Step 2: Run the focused test and verify red**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/ingestion/fetchers/test_sitemap.py -x`  
Expected: FAIL because `newsradar.ingestion.fetchers.sitemap` does not exist.

- [ ] **Step 3: Implement minimal secure `urlset` parsing**

Use `defusedxml.ElementTree.fromstring`; identify elements by local name rather than assuming one namespace prefix. For each `<url>` read `<loc>`, `<lastmod>`, `<news:title>`, and `<news:publication_date>`. Reject non-HTTP(S) URLs and embedded credentials. Generate slug titles by URL-decoding the last non-empty path segment, replacing `-` and `_` with spaces, collapsing whitespace and applying a conservative word-capitalization rule. Hash the normalized public URL for `external_id`.

```python
class SitemapFetcher:
    def __init__(self, policy: HttpPolicy):
        self.policy = policy

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ) -> FetchResult:
        headers = {"User-Agent": "NewsRadarIngestion/0.1"}
        response = await self.policy.get(str(method.url), headers=headers, params=method.params)
        response.raise_for_status()
        root = fromstring(response.content)
        if _local_name(root.tag) != "urlset":
            raise ValueError("unsupported_sitemap_root")
        items, warnings = _normalize_urlset(root, limit)
        if not items:
            raise ValueError("sitemap_no_usable_entries")
        return response_result(
            response,
            items=tuple(items),
            items_received=len(items),
            warnings=tuple(warnings),
        )
```

- [ ] **Step 4: Add isolation and date tests**

Cover invalid credential-bearing URL, invalid date, missing/empty slug, query/fragment removal, `news:publication_date` precedence, `lastmod` fallback, limit enforcement and one malformed record alongside one valid record. Expected behavior: valid records succeed; invalid records add stable warning codes without exposing full sensitive URLs.

- [ ] **Step 5: Run focused tests and lint**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/ingestion/fetchers/test_sitemap.py`  
Expected: PASS.  
Run: `.\.venv\Scripts\ruff.exe check src/newsradar/ingestion/fetchers/sitemap.py tests/ingestion/fetchers/test_sitemap.py`  
Expected: `All checks passed!`

- [ ] **Step 6: Commit parser milestone**

```powershell
git add -- src/newsradar/ingestion/fetchers/sitemap.py tests/ingestion/fetchers/test_sitemap.py
git commit -m "feat: parse sitemap discovery records"
```

### Task 2: Factory, Credential-Free and Conditional Request Integration

**Files:**
- Modify: `src/newsradar/ingestion/fetchers/base.py`
- Modify: `src/newsradar/ingestion/fetchers/sitemap.py`
- Modify: `tests/ingestion/fetchers/test_sitemap.py`

**Interfaces:**
- Consumes: `FetcherFactory.for_method(method, credential_free_only=True)`.
- Produces: `SitemapFetcher` selection for every reviewed `AccessKind.SITEMAP`, without hostname-specific logic.

- [ ] **Step 1: Write failing factory and request-policy tests**

```python
def test_factory_selects_credential_free_sitemap_fetcher() -> None:
    method = source().access_methods[0]
    fetcher = FetcherFactory(policy).for_method(method, credential_free_only=True)
    assert isinstance(fetcher, SitemapFetcher)

@pytest.mark.asyncio
@respx.mock
async def test_sitemap_uses_conditional_headers_but_never_configured_sensitive_headers() -> None:
    result = await SitemapFetcher(HttpPolicy(client)).fetch(
        source_with_sensitive_headers(), method, FetchState(etag="old", last_modified="yesterday"), 5
    )
    request = route.calls[0].request
    assert request.headers["if-none-match"] == "old"
    assert request.headers["if-modified-since"] == "yesterday"
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers
```

- [ ] **Step 2: Run tests and verify red**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/ingestion/fetchers/test_sitemap.py -x`  
Expected: factory rejects `sitemap` as `unsupported_fetch_method`.

- [ ] **Step 3: Implement factory and HTTP-state integration**

Import `SitemapFetcher` beside the other focused fetchers; return it when `method.kind is AccessKind.SITEMAP`. Add Sitemap to `_is_explicitly_credential_free`. In the fetcher construct headers only from the fixed User-Agent plus conditional ETag/Last-Modified values; do not merge `method.headers`. Return `NO_CHANGE` for HTTP 304.

- [ ] **Step 4: Run ingestion factory and eligibility regression tests**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/ingestion/fetchers/test_sitemap.py tests/ingestion/test_eligibility.py tests/ingestion/test_trial.py`  
Expected: PASS.

- [ ] **Step 5: Commit integration milestone**

```powershell
git add -- src/newsradar/ingestion/fetchers/base.py src/newsradar/ingestion/fetchers/sitemap.py tests/ingestion/fetchers/test_sitemap.py
git commit -m "feat: route audited sitemap fetches"
```

### Task 3: Bounded Sitemap Index Support Decision

**Files:**
- Modify: `src/newsradar/ingestion/fetchers/sitemap.py`
- Modify: `tests/ingestion/fetchers/test_sitemap.py`

**Interfaces:**
- Consumes: root local name and registered Sitemap host.
- Produces: either bounded same-host index expansion with `MAX_CHILD_SITEMAPS`, or explicit `unsupported_sitemap_index` failure if cancellation cannot be checked safely between children.

- [ ] **Step 1: Inspect the Worker checkpoint/cancellation boundary**

Trace `IngestionService.fetch_source(... checkpoint=...)` and the `Fetcher` protocol. Record whether a callback can be safely passed into child network requests without changing every existing fetcher signature.

- [ ] **Step 2A: If cancellation is available, test bounded same-host expansion**

Tests must prove: at most 10 child Sitemaps, same-host HTTP(S) only, no credentials, total item limit enforcement, child failure becomes a warning, and cancellation stops before the next child request.

- [ ] **Step 2B: If cancellation is unavailable, test explicit fail-closed behavior**

```python
@pytest.mark.asyncio
async def test_sitemap_index_fails_closed_until_child_cancellation_is_supported() -> None:
    with pytest.raises(ValueError, match="unsupported_sitemap_index"):
        await fetch(INDEX_XML)
```

- [ ] **Step 3: Implement only the branch justified by Step 1**

Do not silently treat a Sitemap Index as an empty `urlset`. Do not broaden the `Fetcher` protocol solely for the two first-party targets if both are direct `urlset` documents.

- [ ] **Step 4: Run focused tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/ingestion/fetchers/test_sitemap.py`  
Expected: PASS.

```powershell
git add -- src/newsradar/ingestion/fetchers/sitemap.py tests/ingestion/fetchers/test_sitemap.py
git commit -m "test: enforce sitemap index safety boundary"
```

### Task 4: Controlled Live Probes and Conditional Source Activation

**Files:**
- Modify conditionally: `sources/universe/universe-bens-bites-1.yaml`
- Modify conditionally: `sources/universe/universe-tldr-ai-1.yaml`
- Modify: `tests/ingestion/test_high_value_mixed_catalog.py`
- Modify conditionally: `tests/research/test_placeholder_resolution_catalog.py`
- Modify conditionally: `tests/web/test_capability_queries.py`
- Modify: `tests/test_source_universe_catalog.py`

**Interfaces:**
- Consumes: `SitemapFetcher.fetch` and existing reviewed Sitemap URLs.
- Produces: per-source evidence containing HTTP result, usable record count, title-source distribution, publication-time coverage and stable failure code.

- [ ] **Step 1: Run controlled no-write probes through the new fetcher**

Use the configured `HttpPolicy` and a limit of 20. Print only status, counts, boolean field coverage and scrubbed warning/error codes; never print response bodies or `.env` values.

- [ ] **Step 2: Apply the activation gate separately to each target**

For each source, activate only if HTTP succeeds, at least one item is usable, every item has `canonical_url` and title, and missing publication time is explicitly measured. An accepted source changes to `availability: ready`, `coverage_mode: direct`, `ingestion.enabled: true`, `approved_at: '2026-07-16'`, `research.status: verified`, and documents Sitemap records as discovery-only. A failed source remains manual/catalog-only and gains the verified Chinese reason and next action.

- [ ] **Step 3: Update catalog tests from observed results, not desired counts**

For each accepted target assert `ready`, `direct`, enabled ingestion and Sitemap access. Update direct/catalog-only/enabled fixed counts by exactly the number accepted; total remains 187 and indirect remains 57.

- [ ] **Step 4: Run catalog validation and focused tests**

Run: `.\.venv\Scripts\newsradar.exe sources validate`  
Expected: `Validated 187 sources`.  
Run: `.\.venv\Scripts\python.exe -m pytest -q tests/ingestion/test_high_value_mixed_catalog.py tests/test_source_universe_catalog.py tests/research/test_placeholder_resolution_catalog.py tests/web/test_capability_queries.py`  
Expected: PASS.

- [ ] **Step 5: Commit observed source decisions**

Stage only the two source files that actually changed and their tests; never stage `sources/aggregators/gdelt-ai.yaml`.

```powershell
git commit -m "feat: activate validated sitemap sources"
```

### Task 5: Durable Worker Acceptance, Web Verification and Full Regression

**Files:**
- Modify only if needed: `src/newsradar/web/source_conclusions.py`
- Modify only if needed: `tests/web/test_source_conclusions.py`
- No report files are created or modified.

**Interfaces:**
- Consumes: accepted reviewed source definitions and existing durable `fetch` operations.
- Produces: real FetchRun/RawItem evidence or a per-target verifiable external blocker.

- [ ] **Step 1: Synchronize reviewed YAML into the database**

Run `newsradar sources sync` and verify only the expected source definitions/risk rows changed. Do not read or print `.env`.

- [ ] **Step 2: Queue each accepted target independently**

Run `newsradar fetch <source-id> --max-items 20 --no-wait` once per accepted target. If a running old Worker uses a stale main catalog, do not stop it without user authorization; record the operation ID and stale-worker blocker.

- [ ] **Step 3: Process through a current-code Worker when safe**

Run `newsradar worker --once` from this worktree only when the queued operation is available. Confirm one target failure does not prevent the other operation from completing.

- [ ] **Step 4: Inspect persisted evidence with scrubbed queries**

For each target verify FetchRun outcome, item count, RawItem title, canonical URL, publication-time coverage, `raw_payload.title_source`, duplicate candidates and absence of article content. Do not output full payloads or secrets.

- [ ] **Step 5: Perform browser acceptance**

Open the local targets/source pages and verify Chinese conclusion, reason and next action. Accepted real FetchRuns must display “已真实抓取成功”; a stale Worker or external failure must remain fixable with a precise Chinese diagnostic rather than being counted as success.

- [ ] **Step 6: Run final verification**

Run: `.\.venv\Scripts\python.exe -m pytest -q`  
Expected: all tests pass with only documented skips.  
Run: `.\.venv\Scripts\ruff.exe check src tests`  
Expected: `All checks passed!`  
Run: `git diff --check` and `git status --short --branch`  
Expected: only intended changes plus the preserved unstaged `sources/aggregators/gdelt-ai.yaml` line-ending status.

- [ ] **Step 7: Commit any final diagnostic adjustment**

Commit only if Step 5 required a code/test change. Do not push or merge.

