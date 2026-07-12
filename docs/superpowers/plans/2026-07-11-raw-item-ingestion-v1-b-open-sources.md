# RawItem Ingestion v1 Milestone B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add open professional-media, aggregator, and social discovery adapters so ingestion covers five information layers rather than mostly official sources.

**Architecture:** Extend the Milestone A fetcher protocol. Aggregators preserve discovery URLs and publisher attribution; public social adapters use only audited account/feed targets; role policy prevents social or aggregator items from becoming independent evidence.

**Tech Stack:** Milestone A stack plus BeautifulSoup-free controlled HTTP redirects; no article HTML parsing.

## Global Constraints

- Milestone A must be merged into the feature branch and its gates must pass.
- Only public official endpoints and audited targets are allowed.
- Professional media uses official RSS/Atom through the existing RSS Fetcher.
- Google News/GDELT are discovery sources, never sole evidence.
- Redirect resolution reads redirect responses only and never downloads article bodies.

## File Structure

- `src/newsradar/ingestion/attribution.py`: publisher attribution and evidence-role policy.
- `src/newsradar/ingestion/origin_resolver.py`: bounded redirect-only original publisher resolution.
- `src/newsradar/ingestion/fetchers/bluesky.py`: public AppView adapter.
- `src/newsradar/ingestion/fetchers/mastodon.py`: audited instance/account adapter.
- `src/newsradar/ingestion/fetchers/gdelt.py`: discovery-only GDELT adapter.
- `src/newsradar/ingestion/fetchers/google_news.py`: Google News RSS adapter composed with origin resolution.
- `tests/ingestion/fetchers/`: fixed protocol fixtures; no live network.
- `reports/ingestion-open-source-review.md`: audited open-source target evidence.

---

### Task 1: Attribution and Evidence-Role Contracts

**Files:**
- Modify: `src/newsradar/ingestion/schema.py`
- Create: `src/newsradar/ingestion/attribution.py`
- Modify: `src/newsradar/ingestion/repository.py`
- Create: `tests/ingestion/test_attribution.py`

**Interfaces:**
- Produces: `OriginResolutionStatus`, `Attribution`, `resolve_evidence_role(source, attribution)`.
- Consumes: Source roles/nature and `NormalizedRawItem` from Milestone A.

```python
@dataclass(frozen=True)
class Attribution:
    publisher_name: str | None
    publisher_url: str | None
    discovery_url: str | None
    resolution_status: OriginResolutionStatus

def resolve_evidence_role(source: SourceDefinition, attribution: Attribution) -> tuple[str, ...]:
    if source.nature in {SourceNature.AGGREGATOR, SourceNature.SOCIAL, SourceNature.COMMUNITY}:
        return tuple(role for role in source.roles if role != SourceRole.EVIDENCE)
    return tuple(source.roles)
```

- [ ] Write failing tests proving professional media can contribute evidence, while aggregator/social content remains discovery/engagement unless independently confirmed.
- [ ] Add immutable attribution fields: publisher name/URL, discovery URL, resolution status, item kind, account ID/handle and thread root.
- [ ] Implement the pure role policy; never call a model.
- [ ] Run: `uv run pytest tests/ingestion/test_attribution.py tests/ingestion/test_repository.py -q`.

Expected: PASS.

- [ ] Commit:

```bash
git add src/newsradar/ingestion/schema.py src/newsradar/ingestion/attribution.py src/newsradar/ingestion/repository.py tests/ingestion/test_attribution.py
git commit -m "feat: preserve source attribution and evidence roles"
```

### Task 2: Bluesky and Mastodon Public Fetchers

**Files:**
- Create: `src/newsradar/ingestion/fetchers/bluesky.py`
- Create: `src/newsradar/ingestion/fetchers/mastodon.py`
- Modify: `src/newsradar/ingestion/fetchers/__init__.py`
- Create: `tests/ingestion/fetchers/test_bluesky.py`
- Create: `tests/ingestion/fetchers/test_mastodon.py`

**Interfaces:**
- Produces: `BlueskyFetcher`, `MastodonFetcher` registered in `FetcherFactory`.
- Consumes: fetcher contract, shared HTTP policy and social attribution fields.

```python
class BlueskyFetcher:
    async def fetch(self, source, method, state, limit) -> FetchResult:
        return await self._fetch_registered_target(source, method, state.cursor, limit)

class MastodonFetcher:
    async def fetch(self, source, method, state, limit) -> FetchResult:
        self._require_registered_instance(method.url)
        return await self._fetch_account_statuses(source, method, state.cursor, limit)
```

- [ ] Write Bluesky fixture tests for author feed, approved query, cursor, DID/Handle, AT URI/CID identity, metrics, thread root, deleted/unavailable item and API-search degradation.
- [ ] Implement `BlueskyFetcher` using only configured public AppView URLs and registered target parameters.
- [ ] Write Mastodon fixture tests for audited instance/account, instance-qualified status ID, pagination link, metrics, content warning, deleted item, per-instance 429 and one-host concurrency.
- [ ] Implement `MastodonFetcher`; reject unregistered instance hosts and unbounded instance discovery.
- [ ] Run: `uv run pytest tests/ingestion/fetchers/test_bluesky.py tests/ingestion/fetchers/test_mastodon.py -q`.

Expected: PASS.

- [ ] Commit:

```bash
git add src/newsradar/ingestion/fetchers tests/ingestion/fetchers/test_bluesky.py tests/ingestion/fetchers/test_mastodon.py
git commit -m "feat: ingest public social signals"
```

### Task 3: GDELT and Google News Discovery Fetchers

**Files:**
- Create: `src/newsradar/ingestion/fetchers/gdelt.py`
- Create: `src/newsradar/ingestion/fetchers/google_news.py`
- Create: `src/newsradar/ingestion/origin_resolver.py`
- Modify: `src/newsradar/ingestion/fetchers/__init__.py`
- Create: `tests/ingestion/fetchers/test_gdelt.py`
- Create: `tests/ingestion/fetchers/test_google_news.py`
- Create: `tests/ingestion/test_origin_resolver.py`

**Interfaces:**
- Produces: `GdeltFetcher`, `GoogleNewsFetcher`, `OriginResolver.resolve(url) -> Attribution`.
- Consumes: shared HTTP policy and B1 attribution contracts.

```python
class OriginResolver:
    async def resolve(self, url: str) -> Attribution:
        current = self._require_public_https(url)
        for _ in range(5):
            async with self.client.stream("GET", current, follow_redirects=False) as response:
                if not response.is_redirect:
                    return self._attribution_from_final_url(current)
                current = self._require_public_https(urljoin(current, response.headers["location"]))
        return Attribution(None, None, url, OriginResolutionStatus.TOO_MANY_REDIRECTS)
```

- [ ] Write resolver tests for direct publisher URL, bounded redirect chain, loop, too many redirects, cross-scheme rejection, disallowed private/local address, missing publisher and response-body non-consumption.
- [ ] Implement a redirect-only resolver with maximum five hops, public HTTPS destination validation and no article parsing.
- [ ] Write GDELT tests for stable result identity, duplicate URL across queries, publisher ambiguity, language/time and missing attribution.
- [ ] Implement `GdeltFetcher` as discovery-only.
- [ ] Write Google News tests for topic/query feeds, discovery URL retention, resolved canonical URL, unresolved fallback and publisher labeling.
- [ ] Implement `GoogleNewsFetcher` by composing RSS parsing and `OriginResolver`.
- [ ] Run: `uv run pytest tests/ingestion/test_origin_resolver.py tests/ingestion/fetchers/test_gdelt.py tests/ingestion/fetchers/test_google_news.py -q`.

Expected: PASS and no fixture request for an article body.

- [ ] Commit:

```bash
git add src/newsradar/ingestion/fetchers src/newsradar/ingestion/origin_resolver.py tests/ingestion
git commit -m "feat: ingest attributed news discovery"
```

### Task 4: Audit Professional-Media and Open-Social Targets

**Files:**
- Modify: selected audited files under `providers/`
- Modify: selected audited files under `sources/universe/`
- Create: `reports/ingestion-open-source-review.md`
- Modify: `tests/test_source_universe_catalog.py`
- Create: `tests/ingestion/test_open_source_matrix.py`

**Interfaces:**
- Produces: audited target matrix with five professional-media RSS targets, two aggregators, Bluesky, Mastodon and existing HN/open targets.
- Consumes: strict YAML schema and provider/target evidence fields.

- [ ] Write a failing matrix test requiring official identity, endpoint evidence, role, attribution mode, risk, reviewed date and ingestion approval for every enabled target.
- [ ] Manually verify official RSS/API pages and update only targets with direct evidence; do not enable generated placeholder URLs.
- [ ] Ensure the selected matrix includes at least five professional-media targets, two aggregator targets, and three open social/community targets before credential sources.
- [ ] Generate `reports/ingestion-open-source-review.md` from audited YAML with method, fields, freshness, role, risk, fallback and conclusion.
- [ ] Run: `uv run pytest tests/test_source_universe_catalog.py tests/ingestion/test_open_source_matrix.py -q`.

Expected: PASS.

- [ ] Commit:

```bash
git add providers sources reports/ingestion-open-source-review.md tests/test_source_universe_catalog.py tests/ingestion/test_open_source_matrix.py
git commit -m "docs: audit open ingestion source matrix"
```

### Task 5: Open-Source Milestone Verification

**Files:**
- Modify: `README.md`
- Create: `reports/milestone-b-verification.md`

- [ ] Add operator documentation for public social and discovery sources, attribution limitations and evidence roles.
- [ ] Run `uv run ruff check .` and `uv run pytest`; record exact counts.
- [ ] Run each open adapter against one approved live target with conservative limits and persistence disabled only through the explicit dry-run path.
- [ ] Verify logs contain correlation IDs and no response credentials or full payloads.
- [ ] Record live outcomes, timestamps, endpoint evidence and failures in the report; do not convert live failures into passing claims.
- [ ] Commit:

```bash
git add README.md reports/milestone-b-verification.md
git commit -m "docs: verify open source ingestion milestone"
```
