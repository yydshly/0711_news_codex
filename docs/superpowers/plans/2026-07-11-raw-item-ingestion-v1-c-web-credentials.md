# RawItem Ingestion v1 Milestone C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add official credential-gated Reddit/YouTube adapters and extend the existing Chinese dashboard with safe guided operations, content browsing, diagnostics and worker visibility.

**Architecture:** Credential adapters use the Milestone A fetcher contract and return explicit blocked results when configuration is absent. FastAPI routes remain thin controllers over shared operation/query services; write operations enqueue durable jobs and never perform network work inside the request.

**Tech Stack:** Existing stack plus Starlette session/CSRF primitives implemented locally; no auth server or JavaScript framework.

## Global Constraints

- Milestones A and B must pass.
- Never log credential values or expose them to templates.
- Web is local-only but still enforces POST, Host/Origin, CSRF and idempotency.
- Preserve existing A-style pages and navigation; add routes rather than replacing the dashboard.

## File Structure

- `src/newsradar/ingestion/fetchers/reddit.py`: official OAuth subreddit adapter.
- `src/newsradar/ingestion/fetchers/youtube.py`: official Data API metadata adapter.
- `src/newsradar/web/security.py`: local write safety, CSRF and idempotency.
- `src/newsradar/web/routes/operations.py`: operation enqueue/status/cancel/retry routes.
- `src/newsradar/web/routes/items.py`: FetchRun, RawItem, versions and duplicate routes.
- `src/newsradar/web/routes/system.py`: worker, queue, migration and diagnostic routes.
- `src/newsradar/web/operation_queries.py`: read-only operation projections.
- `src/newsradar/diagnostics.py`: scrubbed local diagnostic archive builder.
- `src/newsradar/web/templates/`: additive A-style operation/content/system templates.

---

### Task C1: Reddit OAuth and YouTube Data API Fetchers

**Files:**
- Create: `src/newsradar/ingestion/fetchers/reddit.py`
- Create: `src/newsradar/ingestion/fetchers/youtube.py`
- Modify: `src/newsradar/ingestion/fetchers/__init__.py`
- Create: `tests/ingestion/fetchers/test_reddit.py`
- Create: `tests/ingestion/fetchers/test_youtube.py`

**Interfaces:**
- Produces: `RedditFetcher`, `YouTubeFetcher`, and stable blocked errors `missing_credential`, `permission_required`, `quota_exhausted`.
- Consumes: Fetcher contract, configured secret provider and shared HTTP policy.

```python
class CredentialProvider(Protocol):
    def require(self, name: str) -> str: ...

class RedditFetcher:
    def __init__(self, client: httpx.AsyncClient, credentials: CredentialProvider): ...

class YouTubeFetcher:
    def __init__(self, client: httpx.AsyncClient, credentials: CredentialProvider): ...
```

- [ ] Write Reddit tests for missing OAuth, token request, Hot/New listing, Post ID, self/text link, deleted author/content, metrics, pagination, 401/403/429 and token redaction.
- [ ] Implement OAuth through an injected credential provider; never store access tokens in PostgreSQL or Payload.
- [ ] Write YouTube tests for missing key, channel/search target, Video ID, channel/title/description/metrics, pagination, missing captions, quota error and key redaction.
- [ ] Implement only Data API metadata; do not scrape pages or promise transcripts.
- [ ] Run: `uv run pytest tests/ingestion/fetchers/test_reddit.py tests/ingestion/fetchers/test_youtube.py tests/operations/test_logging.py -q`.

Expected: PASS.

- [ ] Commit:

```bash
git add src/newsradar/ingestion/fetchers tests/ingestion/fetchers
git commit -m "feat: ingest credential gated community sources"
```

### Task C2: Safe Web Operation API and Guided Workflow

**Files:**
- Create: `src/newsradar/web/security.py`
- Create: `src/newsradar/web/routes/operations.py`
- Create: `src/newsradar/web/operation_queries.py`
- Modify: `src/newsradar/web/app.py`
- Create: `tests/web/test_security.py`
- Create: `tests/web/test_operations.py`

**Interfaces:**
- Produces: operation list/new/detail/status/cancel/retry routes and `OperationQueryService`.
- Consumes: OperationService/Repository from A4 and EligibilityService from A2.

```python
def require_safe_write(request: Request, form: FormData, session: SessionState) -> None:
    require_loopback_host(request.headers.get("host"))
    require_same_origin(request.headers.get("origin"))
    session.consume_csrf(str(form["csrf_token"]))
    session.consume_idempotency(str(form["idempotency_token"]))
```

- [ ] Write failing tests for Host, Origin, CSRF, SameSite=Strict, one-time idempotency token, GET write rejection, arbitrary URL/header/env rejection and duplicate submit.
- [ ] Implement one security dependency shared by every write route.
- [ ] Write route tests proving POST enqueues and returns immediately without executing network work.
- [ ] Implement typed forms that accept only registered operation, Provider and Source IDs.
- [ ] Add homepage workflow-state tests for database, sync, probe, eligibility, worker, first fetch and existing content states.
- [ ] Implement deterministic Chinese next-step guidance without MiniMax.
- [ ] Run: `uv run pytest tests/web/test_security.py tests/web/test_operations.py tests/web/test_routes.py -q`.

Expected: PASS and existing routes unchanged.

- [ ] Commit:

```bash
git add src/newsradar/web tests/web
git commit -m "feat: guide and enqueue web operations"
```

### Task C3: Fetch Runs, Raw Items, Versions, and Duplicate Review UI

**Files:**
- Create: `src/newsradar/web/routes/items.py`
- Modify: `src/newsradar/web/queries.py`
- Modify: `src/newsradar/web/viewmodels.py`
- Create: `src/newsradar/web/templates/operations.html`
- Create: `src/newsradar/web/templates/operation_detail.html`
- Create: `src/newsradar/web/templates/fetch_runs.html`
- Create: `src/newsradar/web/templates/items.html`
- Create: `src/newsradar/web/templates/item_detail.html`
- Create: `src/newsradar/web/templates/duplicates.html`
- Modify: `src/newsradar/web/templates/base.html`
- Modify: `src/newsradar/web/static/styles.css`
- Create: `tests/web/test_item_queries.py`
- Create: `tests/web/test_item_routes.py`

**Interfaces:**
- Produces: paginated fetch-run/item/version/duplicate views and confirm/dismiss POST actions.
- Consumes: ingestion ORM records and shared Web security.

```python
@dataclass(frozen=True, slots=True)
class RawItemListRow:
    raw_item_id: int
    title: str
    source_name: str
    published_at: datetime | None
    first_seen_at: datetime
    duplicate_count: int
    evidence_roles: tuple[str, ...]
```

- [ ] Write SQL query tests for pagination at 10,000 RawItems, published/first-seen ordering, source/provider/language/time filters, title search, lazy Payload detail and duplicate counts.
- [ ] Implement immutable viewmodels and database-side pagination; do not load Payload in list queries.
- [ ] Write route/template tests for untrusted HTML escaping, sanitized Feed content, source role warnings, preprint/social/aggregator labels, version history and original/discovery URLs.
- [ ] Implement templates by extending current A-style components and responsive rules.
- [ ] Write duplicate confirm/dismiss CSRF tests and implement audit-only status changes; never merge/delete RawItems.
- [ ] Run: `uv run pytest tests/web/test_item_queries.py tests/web/test_item_routes.py tests/web/test_routes.py -q`.

Expected: PASS.

- [ ] Commit:

```bash
git add src/newsradar/web tests/web
git commit -m "feat: browse ingested source content"
```

### Task C4: System Health, Structured Diagnostics, and Operator CLI

**Files:**
- Create: `src/newsradar/diagnostics.py`
- Create: `src/newsradar/web/routes/system.py`
- Create: `src/newsradar/web/templates/system.html`
- Modify: `src/newsradar/cli.py`
- Create: `tests/test_diagnostics_bundle.py`
- Create: `tests/web/test_system.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `/system`, `newsradar diagnostics create`, and Worker/queue/migration health summaries.
- Consumes: worker, operation and logging repositories.

```python
def create_diagnostic_bundle(destination: Path, snapshot: DiagnosticSnapshot) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"newsradar-diagnostics-{snapshot.created_at:%Y%m%dT%H%M%SZ}.zip"
    write_scrubbed_archive(archive, snapshot)
    return archive
```

- [ ] Write tests that build a diagnostic archive and assert it contains versions, migration, worker health, scrubbed events, definition hashes and configured-variable booleans, but no credential values.
- [ ] Implement bounded local archives under `.local/diagnostics/` with manifest and scrubbed JSON/text entries.
- [ ] Write `/system` tests for DB offline, migration missing, worker online/offline, stale heartbeat, queue depth, current operation and recent error categories.
- [ ] Implement the system page and diagnostic POST action.
- [ ] Add CLI tests and command output for diagnostic path and scrub summary.
- [ ] Run: `uv run pytest tests/test_diagnostics_bundle.py tests/web/test_system.py tests/test_cli.py -q`.

Expected: PASS.

- [ ] Commit:

```bash
git add src/newsradar/diagnostics.py src/newsradar/web src/newsradar/cli.py tests
git commit -m "feat: diagnose ingestion runtime health"
```

### Task C5: Browser and Full-Gate Verification

**Files:**
- Modify: `README.md`
- Create: `reports/milestone-c-browser-acceptance.md`

- [ ] Document `newsradar serve`, web-only and worker-only modes, credential names without values, recovery commands, local-only boundary and operation workflow.
- [ ] Run `uv run ruff check .` and `uv run pytest`; record exact results.
- [ ] Start local PostgreSQL, migrate, sync catalogs, start `newsradar serve`, and verify workflow from homepage through operation, progress, fetch run, item detail, duplicate review and system health.
- [ ] Repeat at desktop and 390px viewport; verify keyboard focus, long errors, long titles, long Payload and worker-offline state.
- [ ] Run a bounded fetch while navigating read-only pages; record that requests remain responsive and no page waits for fetch completion.
- [ ] Commit:

```bash
git add README.md reports/milestone-c-browser-acceptance.md
git commit -m "docs: verify ingestion web operations"
```
