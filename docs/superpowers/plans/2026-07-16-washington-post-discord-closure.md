# Washington Post and Discord Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate Washington Post discovery through its official News Sitemap while preserving an explicit, actionable manual boundary for Discord Communities.

**Architecture:** This is a catalog-only change using the existing shared `SitemapFetcher`. Washington Post receives one reviewed direct Sitemap path plus RSS/HTML fallbacks; Discord remains disabled and gains precise research/unlock metadata without any network-capable implementation.

**Tech Stack:** Python 3.12, YAML/Pydantic catalogs, existing httpx/defusedxml Sitemap ingestion, SQLAlchemy/PostgreSQL, pytest, Ruff.

## Global Constraints

- Keep exactly 187 Target records.
- Do not add a fetcher, Discord Bot, OAuth flow, Gateway client, Cookie use, HTML extraction, or paywall bypass.
- Washington Post Sitemap records are discovery leads and cannot independently confirm events.
- Do not expand the Washington Post root Sitemap Index.
- Discord produces no RawItem and receives no Worker operation.
- Do not modify or stage reports, `.env`, or unrelated files.
- Do not push or merge without user confirmation.

---

### Task 1: Catalog Tests First

**Files:**
- Modify: `tests/ingestion/test_high_value_mixed_catalog.py`
- Modify: `tests/research/test_placeholder_resolution_catalog.py`
- Modify: `tests/web/test_capability_queries.py`

**Interfaces:**
- Consumes: provider/source YAML loaders.
- Produces: exact assertions for Washington Post activation, Discord manual boundary, and fixed catalog counts.

- [ ] **Step 1: Replace the Washington Post pending-RSS test with activation expectations**

Assert Provider `ready + none`; Target `ready + direct + enabled`; priority 1 Sitemap equals `https://www.washingtonpost.com/sitemaps/news-sitemap.xml.gz`; priority 2 RSS remains `https://feeds.washingtonpost.com/rss/business/technology`; max items is 20; research is verified.

- [ ] **Step 2: Add Discord boundary assertions**

Assert Provider/Target remain manual, catalog-only and disabled; research is `needs_research`; conclusion says company blog is not community content; unlock requirements mention a concrete server/channel plus administrator Bot/OAuth authorization.

- [ ] **Step 3: Update fixed counts**

Expect total 187, direct 78, indirect 57, catalog-only 52, enabled ingestion 88.

- [ ] **Step 4: Run focused tests and verify red**

Run `.\.venv\Scripts\python.exe -m pytest -q tests/ingestion/test_high_value_mixed_catalog.py tests/research/test_placeholder_resolution_catalog.py tests/web/test_capability_queries.py -x`. Expected: failure on old Washington Post/Discord YAML.

### Task 2: Update Washington Post and Discord YAML

**Files:**
- Modify: `providers/washington-post.yaml`
- Modify: `sources/universe/universe-washington-post-1.yaml`
- Modify: `providers/discord.yaml`
- Modify: `sources/universe/universe-discord-1.yaml`

**Interfaces:**
- Consumes: existing `AccessKind.SITEMAP`, RSS fallback, and manual HTML access method.
- Produces: one approved Washington Post target and one explicitly bounded Discord target.

- [ ] **Step 1: Activate Washington Post provider/target**

Set Provider to `ready + none`; set Target to `ready + direct`; configure Sitemap priority 1, RSS priority 2, manual HTML priority 3; remove hard block; add enabled ingestion with 20-item limit; record the observed 20/20 sample and discovery-only limits.

- [ ] **Step 2: Clarify Discord without enabling it**

Keep status manual/catalog-only/disabled. Update provider unlock requirements and target research fields to require a user-named server/channel, administrator authorization, official Bot/OAuth access, channel permissions, and applicable intents. State that Discord blog RSS is company content and not a substitute.

- [ ] **Step 3: Validate and run focused tests**

Run provider/source validation and the Task 1 pytest command. Expected: all pass.

- [ ] **Step 4: Commit catalog closure**

Stage only the four YAML files and catalog tests; commit `feat: close Washington Post and Discord availability`.

### Task 3: Washington Post Worker Acceptance

**Files:**
- No code changes expected.

**Interfaces:**
- Consumes: reviewed Washington Post YAML and existing durable Worker.
- Produces: one successful FetchRun and bounded RawItems, or a verifiable blocker.

- [ ] **Step 1: Run a no-write 20-item Sitemap probe**

Verify HTTP 200, 20 titles, 20 URLs, 20 publication times, 20 News Sitemap titles, zero warnings and zero content.

- [ ] **Step 2: Sync only reviewed catalog state**

Run provider/source sync from the main project working directory with worktree roots; expect Washington Post and Discord definitions to update.

- [ ] **Step 3: Run a current-code explicit Worker**

Temporarily prevent the stale main Worker from claiming the operation, preserve the 8766 Web UI, and start a Worker with explicit worktree source/provider roots.

- [ ] **Step 4: Queue only Washington Post**

Create one independent max-20 operation. Do not queue Discord.

- [ ] **Step 5: Verify persisted fields**

Check FetchRun outcome/counts and current RawItem title/URL/time completeness; content must be zero. Confirm Discord still has no FetchRun/RawItem introduced by this milestone.

### Task 4: Full and Browser Verification

**Files:**
- No additional production changes expected.

- [ ] **Step 1: Run full pytest, Ruff, provider/source validation and git checks**

- [ ] **Step 2: Start a temporary read-only feature Web instance**

- [ ] **Step 3: Verify Washington Post primary is successful, its secondary is covered, Discord primary remains manual, Discord secondary remains duplicate, and summary total is 187**

- [ ] **Step 4: Stop temporary Web and finish the branch without pushing or merging**

