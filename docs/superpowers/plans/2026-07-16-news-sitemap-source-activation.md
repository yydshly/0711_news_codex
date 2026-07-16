# Official News Sitemap Source Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate Axios, Forbes, Fortune, and Semafor through their official News Sitemaps using the existing shared Sitemap ingestion path.

**Architecture:** This is a catalog activation, not a new fetcher. Provider and primary Target YAML will point to the four robots-published News Sitemap URLs, while existing `SitemapFetcher`, durable operations, RawItem storage, duplicate handling, and web conclusions remain unchanged.

**Tech Stack:** Python 3.12, YAML/Pydantic catalogs, existing httpx/defusedxml Sitemap ingestion, SQLAlchemy/PostgreSQL, pytest, Ruff.

## Global Constraints

- Keep exactly 187 Target records.
- Do not fetch article bodies or bypass paywalls.
- Sitemap items are discovery leads and cannot independently confirm events.
- Do not add site-specific fetcher branches.
- Use only robots-published official News Sitemap URLs.
- Keep Discord and Washington Post unchanged.
- Each source receives an independent durable operation; one failure cannot block the others.
- Do not modify or stage reports, `.env`, or unrelated files.
- Do not push or merge without confirmation.

---

### Task 1: Lock the Four Catalog Decisions with Failing Tests

**Files:**
- Modify: `tests/ingestion/test_high_value_mixed_catalog.py`
- Modify: `tests/research/test_placeholder_resolution_catalog.py`
- Modify: `tests/web/test_capability_queries.py`

**Interfaces:**
- Consumes: `load_provider_tree(Path("providers"))` and `load_source_tree(Path("sources"))`.
- Produces: exact catalog assertions for four providers/targets and updated fixed counts.

- [ ] **Step 1: Add the failing catalog test**

```python
def test_professional_media_use_shared_official_news_sitemaps() -> None:
    expected = {
        "universe-axios-1": "https://www.axios.com/sitemaps/news.xml",
        "universe-forbes-1": "https://www.forbes.com/news_sitemap.xml",
        "universe-fortune-1": "https://fortune.com/feed/googlenews/articles.xml",
        "universe-semafor-1": "https://www.semafor.com/sitemap-news.xml",
    }
    for source_id, url in expected.items():
        source = sources[source_id]
        provider = providers[source.provider_id]
        assert provider.availability.value == "ready"
        assert provider.auth_mode.value == "none"
        assert source.availability.value == "ready"
        assert source.coverage_mode.value == "direct"
        assert source.ingestion.enabled is True
        assert source.ingestion.max_items_per_run == 20
        assert source.access_methods[0].kind.value == "sitemap"
        assert str(source.access_methods[0].url) == url
        assert not source.access_methods[0].auth_envs
        assert not source.access_methods[0].requires_manual_approval
        assert source.research.status.value == "verified"
```

- [ ] **Step 2: Update expected fixed catalog counts**

Expect direct 77, indirect 57, catalog-only 53, enabled ingestion 87, and total 187.

- [ ] **Step 3: Run tests and verify red**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/ingestion/test_high_value_mixed_catalog.py tests/research/test_placeholder_resolution_catalog.py tests/web/test_capability_queries.py -x`  
Expected: FAIL because the four targets/providers are still manual catalog entries.

### Task 2: Update Providers and Primary Targets

**Files:**
- Modify: `providers/axios.yaml`
- Modify: `providers/forbes.yaml`
- Modify: `providers/fortune.yaml`
- Modify: `providers/semafor.yaml`
- Modify: `sources/universe/universe-axios-1.yaml`
- Modify: `sources/universe/universe-forbes-1.yaml`
- Modify: `sources/universe/universe-fortune-1.yaml`
- Modify: `sources/universe/universe-semafor-1.yaml`

**Interfaces:**
- Consumes: the existing `AccessKind.SITEMAP` and `SitemapFetcher` behavior.
- Produces: four `ready + direct + enabled` reviewed targets with exact official entry URLs.

- [ ] **Step 1: Update provider capability metadata**

For each provider set `auth_mode: none`, `availability: ready`, `reviewed_at: '2026-07-16'`, clear `unlock_requirements`, add robots/Sitemap evidence, and state that only public Sitemap discovery is enabled—not article-body access.

- [ ] **Step 2: Update each primary Target**

Set `availability: ready`, `coverage_mode: direct`, clear unlock requirements and hard block, make the official Sitemap priority 1, retain manual HTML only as priority-2 fallback, and add:

```yaml
ingestion: {enabled: true, approved_at: '2026-07-16', max_items_per_run: 20}
```

Set research to `verified`; record the controlled 20/20 title/URL/time sample, `implementation: httpx`, `sample_status: succeeded`, discovery-only/no-body limitations, and a no-fallback explanation.

- [ ] **Step 3: Validate YAML and run focused tests**

Run: `.\.venv\Scripts\newsradar.exe providers validate`  
Expected: 67 providers validated.  
Run: `.\.venv\Scripts\newsradar.exe sources validate`  
Expected: 187 sources validated.  
Run the Task 1 pytest command.  
Expected: PASS.

- [ ] **Step 4: Commit catalog activation**

Stage only the eight YAML files and catalog tests, then commit `feat: activate official news sitemap sources`.

### Task 3: Controlled Probe and Independent Worker Acceptance

**Files:**
- No code changes expected.

**Interfaces:**
- Consumes: four reviewed YAML targets and current shared `SitemapFetcher`.
- Produces: per-target FetchRun and RawItem evidence.

- [ ] **Step 1: Run bounded no-write probes**

For each target use `SitemapFetcher.fetch(..., limit=20)` and print only HTTP status, usable count, title/URL/time counts, official-title count, and warning count. Expected for each: HTTP 200 and 20 complete records.

- [ ] **Step 2: Synchronize providers and sources**

Run the worktree executable from the main project working directory so existing database configuration is inherited. Confirm exactly four providers and four sources update.

- [ ] **Step 3: Ensure a current-code Worker**

If the running main Worker has stale YAML, do not rely on it. Start an isolated Worker with explicit `--root` and `--provider-root` pointing to this worktree; do not stop unrelated PostgreSQL processes.

- [ ] **Step 4: Queue four separate operations**

Queue Axios, Forbes, Fortune, and Semafor separately with max 20 and no wait. Verify each operation reaches a terminal state independently.

- [ ] **Step 5: Inspect scrubbed persisted evidence**

For every target report latest FetchRun outcome, received/inserted/updated counts, current RawItem sample count, title/URL/time completeness, zero body content, and News Sitemap title-source count. Do not print payload bodies or secrets.

- [ ] **Step 6: Handle failure without weakening safety**

If any source fails, retain its catalog configuration only when failure is transient and the controlled probe remains valid; otherwise revert that target/provider to manual state and commit the observed decision. Never increase response limits or fetch article HTML merely to pass acceptance.

### Task 4: Full Regression and Browser Acceptance

**Files:**
- No further production changes expected.

**Interfaces:**
- Consumes: real database evidence after Task 3.
- Produces: final test/UI acceptance.

- [ ] **Step 1: Run complete verification**

Run `.\.venv\Scripts\python.exe -m pytest -q`, `.\.venv\Scripts\ruff.exe check src tests`, provider/source validation, `git diff --check`, and `git status --short --branch`.

- [ ] **Step 2: Start a read-only feature Web instance**

Use an unused local port and do not start another Worker.

- [ ] **Step 3: Verify live target rows and summary**

Confirm four primary targets show `已真实抓取成功`; their four same-identity secondary targets show `已由同一官方目标覆盖`; Discord remains manual; Washington Post remains public-candidate pending acceptance; total remains 187.

- [ ] **Step 4: Stop the temporary Web instance and preserve service state**

Do not leave duplicate Web processes. Keep the normal 8766 service untouched unless a later merge explicitly restarts it.

