# Source Universe v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a provider/target source universe for global AI and technology news that catalogs restricted platforms honestly, probes free sources directly, and reports coverage gaps without unsafe scraping.

**Architecture:** Provider YAML records platform-level policy, authentication, cost, capabilities, and evidence. Existing source YAML remains the target layer and gains provider, target-type, availability, and coverage metadata. Provider capability probes and target content probes remain distinct, with PostgreSQL preserving immutable definitions and probe history.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy 2, Alembic, Typer, HTTPX, YAML, PostgreSQL 18, pytest.

## Global Constraints

- Work only on `feature/source-universe`, based on `feature/local-postgresql-runtime`; never modify `main`.
- Scope is global AI and technology news, with near-zero source-service budget.
- Do not use account cookies, browser sessions, proxy evasion, CAPTCHA bypass, or unaudited scraping.
- X, Facebook, Instagram, TikTok, and LinkedIn must remain visible when blocked; never claim catalog or capability coverage as content coverage.
- Social sources provide discovery/engagement; facts require first-party evidence or independent professional media.
- MiniMax does not decide legality, availability, risk, or activation.

---

### Task 1: Provider and target schemas

**Files:**
- Create: `src/newsradar/providers/schema.py`
- Create: `src/newsradar/providers/yaml_loader.py`
- Modify: `src/newsradar/sources/schema.py`
- Test: `tests/test_provider_schema.py`
- Modify: `tests/test_source_schema.py`

**Interfaces:**
- Produces `ProviderDefinition`, `ProviderCategory`, `TargetType`, `Availability`, and `CoverageMode` strict Pydantic models/enums.
- Produces `load_provider_tree(root: Path) -> list[ProviderDefinition]` with duplicate-ID and credential-key rejection.
- Extends `SourceDefinition` with backward-compatible defaults: `provider_id="independent"`, `target_type="publisher_feed"`, `availability="ready"`, `coverage_mode="direct"`, `official_identity_url=None`, `reviewed_at=None`, and `unlock_requirements=[]`.

- [x] Write failing tests for strict enums, HTTPS evidence, duplicate IDs, unknown fields, plaintext credentials, old source compatibility, and social-role restrictions.
- [x] Run `uv run pytest tests/test_provider_schema.py tests/test_source_schema.py -v` and confirm failures are caused by missing provider types.
- [x] Implement the minimal schema/loaders. Require social targets to include `discovery` or `engagement`; reject `evidence` as their only role.
- [x] Re-run focused tests and `uv run ruff check`.
- [x] Commit with `feat: add provider and target source schemas`.

### Task 2: Provider persistence and idempotent synchronization

**Files:**
- Modify: `src/newsradar/db/models.py`
- Create: `src/newsradar/providers/repository.py`
- Create: `migrations/versions/20260711_0002_source_providers.py`
- Test: `tests/test_provider_repository.py`

**Interfaces:**
- Adds `source_providers`, `source_provider_versions`, and `source_provider_probe_runs`.
- `ProviderRepository.sync(providers) -> SyncResult` creates immutable versions only when canonical YAML changes.
- Provider probe history stores `probe_type="capability"`, outcome, HTTP/auth status, latency, availability, reason, evidence URL, and checked time; it stores no content samples.

- [x] Write failing SQLite repository tests for create/update/unchanged behavior and immutable snapshots.
- [x] Run focused tests and observe missing tables/repository failure.
- [x] Implement ORM models, repository, and additive Alembic migration; do not alter existing 27 source rows.
- [x] Verify focused tests and offline PostgreSQL SQL generation.
- [x] Commit with `feat: persist provider registry and capability history`.

### Task 3: Capability probes and CLI

**Files:**
- Create: `src/newsradar/providers/probes.py`
- Create: `src/newsradar/providers/reporting.py`
- Modify: `src/newsradar/cli.py`
- Test: `tests/test_provider_probes.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- `ProviderProbe.probe(provider) -> ProviderProbeResult` distinguishes documentation reachability, missing credentials, missing approval, payment, manual-only, and unavailable states.
- Adds `newsradar providers validate|sync|probe --all|report`.
- Adds `newsradar sources coverage [--provider ID] [--output PATH]`.
- Capability success never changes a provider to `ready` or creates content samples.

- [x] Write failing tests for 200, 401, 403, 429, timeout, missing credential, approval, payment, and forbidden cookie fallback.
- [x] Write failing CLI tests for all provider commands and provider-filtered coverage.
- [x] Implement probes, batch isolation, persistence, and Markdown reporting.
- [x] Verify focused tests and confirm secrets/authorization headers are redacted.
- [x] Commit with `feat: probe provider capabilities and report coverage`.

### Task 4: Audited provider and target universe

**Files:**
- Create: `providers/*.yaml`
- Create/modify: `sources/**/*.yaml`
- Create: `reports/source-universe.md`
- Test: `tests/test_source_universe_catalog.py`

**Interfaces:**
- Catalogs at least 35 providers and 120 targets across seven classes: social/community, professional media, first-party, aggregators/search, research/developer, newsletters/podcasts, and trend/business signals.
- Every provider contains official homepage/docs, auth mode, cost tier, capabilities, evidence, availability, review date, and unlock requirements.
- Every target contains provider, target type, official identity URL, roles, coverage mode, availability, reviewed date, preferred method, fallback or explicit no-fallback note.

- [x] Write failing catalog tests for minimum counts, seven-class coverage, required restricted platforms, official identity evidence, and no `.invalid`, cookies, or credentials.
- [x] Add provider YAML for X, Threads, Facebook, Instagram, TikTok, YouTube, LinkedIn, Bluesky, Mastodon, Reddit, HN, Telegram, Discord, Product Hunt; major media; aggregators; research; newsletters/podcasts; and signal providers.
- [x] Expand targets to at least 120 using verified publisher feeds, official channels/accounts, communities, queries, and signal endpoints. Paid/approval targets remain `catalog_only` and blocked honestly.
- [x] Generate `reports/source-universe.md` from the registry, not by hand.
- [x] Run catalog tests and validation commands.
- [x] Commit with `feat: catalog global AI technology source universe`.

### Task 5: Live migration, probes, coverage acceptance, and documentation

**Files:**
- Modify: `README.md`
- Update: `reports/source-coverage.md`
- Update: this implementation plan by checking completed steps.

**Interfaces:**
- Applies migration to the existing project-local PostgreSQL instance at `127.0.0.1:55432` using a worktree-local ignored `.env`.
- Persists provider definitions and capability probes; runs content probes only for direct/indirect targets that are technically accessible.

- [x] Copy only the ignored database connection configuration from the parent feature worktree; do not print or commit the password.
- [x] Run Alembic, provider sync twice, and source sync twice; second runs must be unchanged.
- [x] Run all provider capability probes and accessible content probes; blocked sources must complete without browser fallback.
- [x] Generate coverage report with catalog/direct/indirect/blocked counts, gaps, unlock requirements, and cost tiers.
- [x] Verify at least 35 providers, 120 targets, seven classes, restricted-platform visibility, and at least 25 direct free targets. Three consecutive content-success rounds are recorded only for accessible targets.
- [x] Run `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, both YAML validators, Alembic verification, tracked-secret scan, and `git diff --check`.
- [x] Commit with `docs: document source universe coverage and operations`.
