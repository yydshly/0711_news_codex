# RawItem Ingestion v1 Milestone A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reliable PostgreSQL-backed ingestion core with bounded worker execution and production fetchers for RSS, Hacker News, GitHub Releases, and arXiv.

**Architecture:** Add focused `operations` and `ingestion` packages. Web/CLI enqueue typed operations; an independent worker leases jobs from PostgreSQL; fetchers return normalized items without touching the database; ingestion repositories enforce idempotency, snapshots, and duplicate candidates.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, Pydantic 2, HTTPX, feedparser, Typer, PostgreSQL, pytest, respx, Ruff.

## Global Constraints

- Follow the index plan global constraints.
- Default limits: 1 active operation, 4 concurrent sources, 2 requests per host, 5 HN item requests, 10-second connect timeout, 30-second read timeout, 45-second request timeout, 2-minute source deadline, 30-minute operation deadline, 60-second lease, 10-second heartbeat.
- Automatic request retries: at most two, only for transport errors, 502/503/504, and bounded 429 Retry-After.
- Keep network requests outside database transactions.

## File Structure

- `src/newsradar/operations/schema.py`: operation, attempt, worker, event, status and error contracts.
- `src/newsradar/operations/repository.py`: PostgreSQL queue, leases, events and worker heartbeats.
- `src/newsradar/operations/worker.py`: worker loop, lease renewal, cancellation and recovery.
- `src/newsradar/operations/logging.py`: structured logging and secret redaction.
- `src/newsradar/ingestion/schema.py`: normalized item and fetch result contracts.
- `src/newsradar/ingestion/eligibility.py`: one eligibility decision shared by CLI and Web.
- `src/newsradar/ingestion/normalization.py`: URL, title, author, time and hashes.
- `src/newsradar/ingestion/repository.py`: RawItem upsert, snapshots, observations and candidates.
- `src/newsradar/ingestion/service.py`: per-source fetch orchestration and transaction boundaries.
- `src/newsradar/ingestion/fetchers/*.py`: protocol-specific fetchers with no persistence.
- `migrations/versions/20260711_0003_raw_item_ingestion.py`: additive migration from `0002`.

---

### Task A1: Domain Contracts, ORM Models, and Additive Migration

**Files:**
- Create: `src/newsradar/operations/__init__.py`
- Create: `src/newsradar/operations/schema.py`
- Create: `src/newsradar/ingestion/__init__.py`
- Create: `src/newsradar/ingestion/schema.py`
- Modify: `src/newsradar/db/models.py`
- Create: `migrations/versions/20260711_0003_raw_item_ingestion.py`
- Modify: `tests/test_migrations.py`
- Create: `tests/operations/test_schema.py`
- Create: `tests/ingestion/test_schema.py`

**Interfaces:**
- Produces: `OperationType`, `OperationStatus`, `FetchOutcome`, `ErrorCategory`, `NormalizedRawItem`, `FetchResult`, and additive ORM records named in the design.
- Consumes: existing `Base`, `SourceDefinitionRecord`, `SourceAccessMethodRecord`, and migration revision `20260711_0002`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_normalized_item_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        NormalizedRawItem(
            external_id="42", title="A", canonical_url="https://example.com/a",
            raw_payload={}, invented=True,
        )

def test_operation_status_has_terminal_states():
    assert OperationStatus.terminal() == {
        OperationStatus.SUCCEEDED, OperationStatus.PARTIAL,
        OperationStatus.FAILED, OperationStatus.INTERRUPTED,
        OperationStatus.CANCELLED,
    }
```

- [ ] **Step 2: Run the new contract tests**

Run: `uv run pytest tests/operations/test_schema.py tests/ingestion/test_schema.py -q`

Expected: FAIL because the packages and contracts do not exist.

- [ ] **Step 3: Implement strict enums and Pydantic contracts**

```python
class NormalizedRawItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    external_id: str
    title: str
    canonical_url: AnyHttpUrl
    original_url: AnyHttpUrl | None = None
    authors: tuple[str, ...] = ()
    summary: str | None = None
    content: str | None = None
    language: str | None = None
    content_type: str = "article"
    published_at: datetime | None = None
    source_updated_at: datetime | None = None
    discussion_url: AnyHttpUrl | None = None
    engagement: dict[str, int | float] = Field(default_factory=dict)
    raw_payload: dict[str, Any]
```

Define every enum value exactly as the design specifies. Add `FetchResult` with immutable tuples, response metadata, cursor, counters, warnings and error fields.

- [ ] **Step 4: Write the migration test before the migration**

Extend `tests/test_migrations.py` to upgrade a `0002` database containing one legacy RawItem and assert that the row, payload, Provider, Source and Probe history survive `upgrade head`.

Run: `uv run pytest tests/test_migrations.py -q`

Expected: FAIL because revision `0003` and new tables are absent.

- [ ] **Step 5: Add ORM records and the additive `0003` migration**

Create `OperationRunRecord`, `OperationAttemptRecord`, `OperationEventRecord`, `WorkerRecord`, `RawItemSnapshotRecord`, `FetchRunItemRecord`, `DuplicateCandidateRecord`, and `SourceFetchStateRecord`. Extend `FetchRunRecord` and `RawItemRecord` without dropping legacy columns. Add indexes for queue status/next attempt, source/time, canonical URL hash, title fingerprint, and lease expiry.

- [ ] **Step 6: Verify migration and contracts**

Run: `uv run pytest tests/test_migrations.py tests/operations/test_schema.py tests/ingestion/test_schema.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/newsradar/db/models.py src/newsradar/operations src/newsradar/ingestion/schema.py migrations/versions/20260711_0003_raw_item_ingestion.py tests/test_migrations.py tests/operations tests/ingestion/test_schema.py
git commit -m "feat: add ingestion runtime data model"
```

### Task A2: YAML Eligibility and Deterministic Normalization

**Files:**
- Modify: `src/newsradar/sources/schema.py`
- Create: `src/newsradar/ingestion/eligibility.py`
- Create: `src/newsradar/ingestion/normalization.py`
- Modify: `tests/test_source_schema.py`
- Create: `tests/ingestion/test_eligibility.py`
- Create: `tests/ingestion/test_normalization.py`

**Interfaces:**
- Produces: `IngestionConfig`, `EligibilityDecision`, `evaluate_fetch_eligibility()`, `normalize_url()`, `normalize_title()`, `content_hash()`, and `title_similarity()`.
- Consumes: `SourceDefinition`, `AccessMethod`, Provider/Source enums and `NormalizedRawItem`.

- [ ] **Step 1: Write failing YAML compatibility and leak tests**

```python
def test_ingestion_defaults_disabled(legacy_source_dict):
    source = SourceDefinition.model_validate(legacy_source_dict)
    assert source.ingestion.enabled is False

def test_ingestion_rejects_unknown_and_secret_fields(legacy_source_dict):
    legacy_source_dict["ingestion"] = {"enabled": True, "api_key": "secret"}
    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(legacy_source_dict)
```

- [ ] **Step 2: Implement `IngestionConfig` and rerun schema tests**

```python
class IngestionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = False
    approved_at: date | None = None
    max_items_per_run: int = Field(default=100, ge=1, le=500)
```

Run: `uv run pytest tests/test_source_schema.py -q`

Expected: PASS including unchanged legacy YAML fixtures.

- [ ] **Step 3: Write failing eligibility matrix tests**

Parametrize approved, one-off, paused, disabled, payment, approval, catalog-only, HTML-only, missing credential and hard-block cases. Assert stable `allowed`, `error_code`, selected method and Chinese reason.

- [ ] **Step 4: Implement one pure eligibility function**

```python
def evaluate_fetch_eligibility(
    source: SourceDefinition,
    *,
    approved_only: bool,
    configured_env: AbstractSet[str],
    hard_block_reason: str | None,
) -> EligibilityDecision:
    ...
```

The function must not read process environment, mutate YAML or query the database.

- [ ] **Step 5: Write normalization tests, including tracking and business parameters**

Assert Fragment/default-port removal, `utm_*`/`fbclid` removal, business parameter preservation, Unicode title normalization, stable hashes, engagement exclusion and seven-day title-candidate boundaries.

- [ ] **Step 6: Implement deterministic normalization**

Use `urllib.parse`, `html.unescape`, `unicodedata.normalize("NFKC", value)`, sorted JSON and SHA-256. Do not make network requests.

- [ ] **Step 7: Verify and commit**

Run: `uv run pytest tests/test_source_schema.py tests/ingestion/test_eligibility.py tests/ingestion/test_normalization.py -q`

Expected: PASS.

```bash
git add src/newsradar/sources/schema.py src/newsradar/ingestion/eligibility.py src/newsradar/ingestion/normalization.py tests/test_source_schema.py tests/ingestion/test_eligibility.py tests/ingestion/test_normalization.py
git commit -m "feat: validate ingestion eligibility and identity"
```

### Task A3: Idempotent RawItem Persistence

**Files:**
- Create: `src/newsradar/ingestion/repository.py`
- Create: `tests/ingestion/test_repository.py`

**Interfaces:**
- Produces: `RawItemRepository.upsert(fetch_run_id, source_id, item) -> ItemWriteResult` and `record_failure()`.
- Consumes: contracts from A1 and hashes from A2.

- [ ] **Step 1: Write failing repository tests**

Cover insert plus initial snapshot, unchanged observation, meaningful update plus one snapshot, engagement-only update without snapshot, same-source canonical fallback, External-ID/URL conflict, canonical duplicate candidate and title candidate idempotency.

- [ ] **Step 2: Run repository tests**

Run: `uv run pytest tests/ingestion/test_repository.py -q`

Expected: FAIL because `RawItemRepository` does not exist.

- [ ] **Step 3: Implement explicit write results**

```python
class ItemAction(StrEnum):
    INSERTED = "inserted"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    FAILED = "failed"

@dataclass(frozen=True)
class ItemWriteResult:
    raw_item_id: int | None
    action: ItemAction
    error_code: str | None = None
```

Implement `upsert()` using database uniqueness as the final concurrency guard. Never merge two existing RawItems during conflict handling.

- [ ] **Step 4: Verify transaction rollback boundaries**

Add a test that forces one item insert to fail and proves earlier committed source results and later items remain processable.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/ingestion/test_repository.py -q`

Expected: PASS.

```bash
git add src/newsradar/ingestion/repository.py tests/ingestion/test_repository.py
git commit -m "feat: persist raw items idempotently"
```

### Task A4: PostgreSQL Queue, Worker Leases, Logging, and Recovery

**Files:**
- Create: `src/newsradar/operations/repository.py`
- Create: `src/newsradar/operations/service.py`
- Create: `src/newsradar/operations/worker.py`
- Create: `src/newsradar/operations/logging.py`
- Create: `tests/operations/test_repository.py`
- Create: `tests/operations/test_worker.py`
- Create: `tests/operations/test_logging.py`

**Interfaces:**
- Produces: `OperationRepository.enqueue()`, `lease_next()`, `renew_lease()`, `finish_attempt()`, `request_cancel()`, `Worker.run_once()` and `configure_logging()`.
- Consumes: operation contracts and ORM records from A1.

- [ ] **Step 1: Write failing queue and lease tests**

Test FIFO-ready ordering, `SKIP LOCKED` double-worker exclusion, heartbeat renewal, expired lease reclamation, maximum three attempts, cancellation and terminal-state immutability.

- [ ] **Step 2: Implement queue repository with database time**

Use PostgreSQL `now()` for lease comparisons. `lease_next()` must create a new OperationAttempt and atomically bind it to the Worker.

- [ ] **Step 3: Write and implement worker-loop tests**

Inject a fake operation handler and clock. Assert that Web is not involved, heartbeat continues during work, cancellation is checked at source/page boundaries, and an unhandled exception creates a scrubbed failure event.

```python
class Worker:
    async def run_once(self) -> bool:
        lease = self.repository.lease_next(self.worker_id)
        if lease is None:
            return False
        await self.executor.execute(lease, heartbeat=self._heartbeat)
        return True
```

- [ ] **Step 4: Write secret-redaction and rotation tests**

Assert that bearer tokens, Cookie, database URLs, API-key query parameters and environment values are absent from rendered logs. Assert JSON Lines contain all correlation IDs.

- [ ] **Step 5: Implement structured logging**

Use stdlib `logging.handlers.RotatingFileHandler` at `.local/logs/newsradar.log`, `maxBytes=10 * 1024 * 1024`, `backupCount=5`. Centralize redaction in one formatter/filter used by console, file and operation events.

- [ ] **Step 6: Verify and commit**

Run: `uv run pytest tests/operations -q`

Expected: PASS.

```bash
git add src/newsradar/operations tests/operations
git commit -m "feat: run durable leased operations"
```

### Task A5: Baseline Fetchers, Ingestion Service, and CLI

**Files:**
- Create: `src/newsradar/ingestion/fetchers/__init__.py`
- Create: `src/newsradar/ingestion/fetchers/base.py`
- Create: `src/newsradar/ingestion/fetchers/rss.py`
- Create: `src/newsradar/ingestion/fetchers/hackernews.py`
- Create: `src/newsradar/ingestion/fetchers/github.py`
- Create: `src/newsradar/ingestion/fetchers/arxiv.py`
- Create: `src/newsradar/ingestion/service.py`
- Modify: `src/newsradar/cli.py`
- Create: `tests/ingestion/fetchers/test_rss.py`
- Create: `tests/ingestion/fetchers/test_hackernews.py`
- Create: `tests/ingestion/fetchers/test_github.py`
- Create: `tests/ingestion/fetchers/test_arxiv.py`
- Create: `tests/ingestion/test_service.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `Fetcher.fetch() -> FetchResult`, `FetcherFactory.for_method()`, `IngestionService.fetch_source()`, and CLI commands `fetch`, `operations`, `worker`, `serve`.
- Consumes: eligibility, normalization, repository and operation interfaces from A1–A4.

- [ ] **Step 1: Write fixed-sample failing tests for all four fetchers**

Use respx fixtures for RSS/Atom with 304 and malformed entry; HN Top/New/Ask/dead item and bounded five-item concurrency; GitHub release/draft/prerelease/ETag/rate limit/pagination; arXiv authors/version/pagination/rate delay. Assert fetchers never open article/PDF URLs and never access a database.

- [ ] **Step 2: Implement the fetcher protocol and shared HTTP policy**

```python
class Fetcher(Protocol):
    async def fetch(
        self,
        source: SourceDefinition,
        method: AccessMethod,
        state: FetchState,
        limit: int,
    ) -> FetchResult: ...
```

Reuse existing parser helpers only after extracting them without changing ProbeResult behavior. Configure HTTPX pool, timeouts, per-host semaphore, response-size guard and retry policy centrally.

- [ ] **Step 3: Implement each fetcher until its fixed-sample tests pass**

Run each focused file after its implementation. Expected: PASS with no live network.

- [ ] **Step 4: Write failing service isolation tests**

Assert one source timeout yields a failed FetchRun while later sources continue; 304 yields `no_change`; per-source transaction counts match `fetch_run_items`; advisory locks prevent duplicate source runs; and dry-run writes no RawItem or cursor.

- [ ] **Step 5: Implement `IngestionService`**

Keep qualification before network, network before transaction, and item writes in bounded batches. Update SourceFetchState only after successful committed processing.

- [ ] **Step 6: Write CLI tests and add commands**

Cover `fetch --approved`, explicit source, provider filter, max-items cannot raise YAML, dry-run, operation list/show/retry, worker and serve help. CLI synchronous fetch must create an OperationRun and wait for its terminal state.

- [ ] **Step 7: Run Milestone A gates**

Run:

```text
uv run ruff check .
uv run pytest
```

Expected: Ruff exit 0; all tests pass, including the original 147.

- [ ] **Step 8: Commit**

```bash
git add src/newsradar/ingestion src/newsradar/cli.py tests/ingestion tests/test_cli.py
git commit -m "feat: ingest baseline open sources"
```

Milestone A exit report must include migration compatibility, queue/worker recovery evidence, four fetcher fixture results, full test count, Ruff result and known limitations. Do not claim full source-universe coverage.

