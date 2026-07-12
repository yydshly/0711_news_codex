# News Codex Chinese Source Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, read-only, Chinese web dashboard that accurately explains News Codex provider/target coverage, access methods, probe health, risks, and unlock gaps.

**Architecture:** Add a small server-rendered FastAPI application inside the existing Python package. A SQLAlchemy-backed query service converts database records into typed page ViewModels; Jinja templates render the A-style command center, and centralized Chinese labels plus deterministic diagnostics prevent catalog coverage from being confused with actual content coverage.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, Uvicorn, SQLAlchemy 2, Typer, native CSS/JavaScript, pytest, HTTPX TestClient.

## Global Constraints

- Keep the web UI local-only and read-only; default bind is exactly `127.0.0.1:8765`.
- Do not add authentication, public hosting, web-triggered sync/probe/fetch, news summaries, recommendations, notifications, or scheduling.
- Read current provider, target, risk, and probe state directly from PostgreSQL through SQLAlchemy 2.
- Never expose `.env` values, API keys, cookies, authorization headers, database passwords, or stack traces.
- UI copy is Chinese-first; technical identifiers may appear as secondary English text.
- Catalog registration, provider capability checks, target content checks, and verified news coverage must remain distinct concepts.
- Social sources are discovery/engagement signals and never independent factual evidence.
- MiniMax is not called by the dashboard; diagnostics are deterministic.
- Preserve existing report modifications and all unrelated user changes.

---

## File Structure

- `src/newsradar/web/__init__.py`: exports `create_app`.
- `src/newsradar/web/i18n.py`: centralized Chinese enum labels and failure explanations.
- `src/newsradar/web/viewmodels.py`: immutable page-facing dataclasses.
- `src/newsradar/web/queries.py`: read-only SQLAlchemy aggregation and detail queries.
- `src/newsradar/web/diagnostics.py`: deterministic Chinese capability narrative.
- `src/newsradar/web/app.py`: FastAPI factory, routes, dependency wiring, errors, and security headers.
- `src/newsradar/web/templates/*.html`: server-rendered layout and seven page templates.
- `src/newsradar/web/static/styles.css`: A-style dark command-center visual system and responsive rules.
- `src/newsradar/web/static/app.js`: progressive enhancement for mobile navigation only.
- `tests/web/conftest.py`: isolated SQLite fixtures populated with representative registry history.
- `tests/web/test_i18n.py`: translation and safe fallback tests.
- `tests/web/test_queries.py`: aggregation, separation, detail, and secret-redaction tests.
- `tests/web/test_diagnostics.py`: deterministic narrative tests.
- `tests/web/test_routes.py`: route, filtering, error, security header, and HTML tests.
- `tests/web/test_cli.py`: local bind defaults.
- `src/newsradar/cli.py`: add `newsradar web`.
- `pyproject.toml`, `uv.lock`, `README.md`: runtime dependencies and user instructions.

---

### Task 1: Web Dependencies and Chinese Label Boundary

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/newsradar/web/__init__.py`
- Create: `src/newsradar/web/i18n.py`
- Create: `tests/web/__init__.py`
- Create: `tests/web/test_i18n.py`

**Interfaces:**
- Consumes: string-valued enums already persisted by `newsradar.db.models`.
- Produces: `zh_label(group: str, value: str) -> str` and `explain_failure(reason: str, http_status: int | None, error_code: str | None) -> str`.

- [ ] **Step 1: Add failing label tests**

```python
from newsradar.web.i18n import explain_failure, zh_label


def test_zh_label_covers_dashboard_enums():
    assert zh_label("availability", "ready") == "可直接使用"
    assert zh_label("coverage_mode", "indirect") == "间接发现"
    assert zh_label("probe_type", "capability") == "能力探测"
    assert zh_label("target_type", "community") == "社区"


def test_zh_label_preserves_unknown_value():
    assert zh_label("availability", "future_state") == "future_state"


def test_failure_explanation_is_deterministic():
    assert explain_failure("rate limit", 429, "rate_limited") == "触发远端限流，请等待后重试"
    assert explain_failure("missing token", 401, None) == "需要有效凭据才能访问"
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `uv run pytest tests/web/test_i18n.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'newsradar.web'`.

- [ ] **Step 3: Add exact web dependencies**

Add to `project.dependencies` in `pyproject.toml`:

```toml
"fastapi>=0.116,<1",
"jinja2>=3.1,<4",
"uvicorn>=0.35,<1",
```

Run: `uv lock && uv sync --extra dev`

Expected: lockfile updates and environment synchronization succeeds.

- [ ] **Step 4: Implement centralized labels and explanations**

Create `src/newsradar/web/i18n.py` with a `LABELS: dict[str, dict[str, str]]` that includes every current persisted value for `provider_category`, `availability`, `coverage_mode`, `target_type`, `nature`, `role`, `status`, `access_kind`, `outcome`, `probe_type`, `risk_band`, `cost_tier`, and `auth_mode`. Implement:

```python
def zh_label(group: str, value: str) -> str:
    return LABELS.get(group, {}).get(value, value)


def explain_failure(reason: str, http_status: int | None, error_code: str | None) -> str:
    normalized = f"{reason} {error_code or ''}".lower()
    if http_status == 429 or "rate" in normalized:
        return "触发远端限流，请等待后重试"
    if http_status == 401 or "credential" in normalized or "token" in normalized:
        return "需要有效凭据才能访问"
    if http_status == 403 or "approval" in normalized or "permission" in normalized:
        return "当前权限未获批准或被远端拒绝"
    if http_status == 404:
        return "远端入口不存在，可能已经迁移"
    if http_status is not None and http_status >= 500:
        return "远端服务暂时不可用"
    if "timeout" in normalized:
        return "连接远端超时"
    if "schema" in normalized or "field" in normalized:
        return "响应结构或字段可能已经变化"
    return "探测未成功，请查看原始原因"
```

Export `create_app` lazily from `src/newsradar/web/__init__.py` so importing `newsradar.web.i18n` does not construct the application.

- [ ] **Step 5: Run tests and quality checks**

Run: `uv run pytest tests/web/test_i18n.py -v && uv run ruff check src/newsradar/web tests/web`

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 6: Commit**

```powershell
git add pyproject.toml uv.lock src/newsradar/web tests/web
git commit -m "feat: add Chinese dashboard vocabulary"
```

---

### Task 2: Typed ViewModels and Read-Only Query Service

**Files:**
- Create: `src/newsradar/web/viewmodels.py`
- Create: `src/newsradar/web/queries.py`
- Create: `tests/web/conftest.py`
- Create: `tests/web/test_queries.py`

**Interfaces:**
- Consumes: `sqlalchemy.orm.Session` and records from `newsradar.db.models`.
- Produces: `DashboardQueryService` methods `summary()`, `providers(filters)`, `provider_detail(provider_id)`, `targets(filters)`, `target_detail(source_id)`, `probes(filters)`, and `gap_groups()`.

- [ ] **Step 1: Create representative database fixtures**

In `tests/web/conftest.py`, create an in-memory SQLite engine with `StaticPool`, create all `Base.metadata` tables, and insert:

- providers: `github` (`free`, `ready`) and `x` (`paid`, `requires_payment`);
- targets: one ready/direct GitHub target, one ready/indirect search target, one blocked/direct X target;
- one risk row and one primary access method per target;
- three successful content probe runs for the GitHub target and one blocked provider capability probe for X.

Expose `db_session()` and `query_service()` pytest fixtures. Use fixed UTC timestamps so ordering assertions are stable.

- [ ] **Step 2: Write failing aggregation and separation tests**

```python
def test_summary_uses_strict_coverage_definitions(query_service):
    result = query_service.summary()
    assert result.provider_count == 2
    assert result.target_count == 3
    assert result.free_direct_count == 1
    assert result.indirect_count == 1
    assert result.blocked_count == 1
    assert result.three_success_count == 1


def test_probes_keep_capability_and_content_distinct(query_service):
    rows = query_service.probes()
    assert {row.probe_type for row in rows} == {"capability", "content"}
    capability = next(row for row in rows if row.probe_type == "capability")
    assert capability.completeness is None
    assert capability.object_id == "x"


def test_missing_probe_history_is_not_success(query_service, db_session):
    row = next(item for item in query_service.targets() if item.source_id == "search-ai")
    assert row.latest_outcome is None
    assert row.latest_outcome_label == "尚未探测"
```

- [ ] **Step 3: Run query tests and verify missing types**

Run: `uv run pytest tests/web/test_queries.py -v`

Expected: FAIL because `DashboardQueryService` and ViewModels do not exist.

- [ ] **Step 4: Implement immutable ViewModels**

In `viewmodels.py`, use frozen, slotted dataclasses. Define exact public models:

```python
@dataclass(frozen=True, slots=True)
class DashboardSummary:
    provider_count: int
    target_count: int
    free_direct_count: int
    indirect_count: int
    blocked_count: int
    three_success_count: int
    category_counts: tuple[tuple[str, int], ...]
    latest_probe_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProviderRow:
    provider_id: str
    name: str
    category: str
    category_label: str
    cost_tier: str
    cost_label: str
    availability: str
    availability_label: str
    target_count: int
    direct_count: int
    indirect_count: int
    latest_outcome: str | None
    latest_outcome_label: str
    reviewed_at: date


@dataclass(frozen=True, slots=True)
class TargetRow:
    source_id: str
    name: str
    provider_id: str
    provider_name: str
    target_type: str
    target_type_label: str
    coverage_mode: str
    coverage_label: str
    availability: str
    availability_label: str
    access_kind: str | None
    access_label: str
    risk_total: int | None
    latest_content_at: datetime | None
    latest_outcome: str | None
    latest_outcome_label: str


@dataclass(frozen=True, slots=True)
class ProbeRow:
    probe_id: str
    object_id: str
    object_name: str
    probe_type: str
    probe_type_label: str
    outcome: str
    outcome_label: str
    checked_at: datetime
    http_status: int | None
    latency_ms: float | None
    completeness: float | None
    reason_zh: str
    reason_raw: str
```

Also define `ProviderDetail`, `TargetDetail`, `AccessMethodView`, `RiskView`, and `GapGroup` with only fields required by the approved spec. Secret values are not fields on any ViewModel.

- [ ] **Step 5: Implement SQLAlchemy query methods**

Implement `DashboardQueryService(session)` using `select()`, explicit joins, and small private helpers. Required rules:

```python
FREE_COST_TIERS = {"free", "free_quota", "freemium"}
SUCCESS_OUTCOMES = {"success"}

# Free direct coverage:
source.coverage_mode == "direct"
and source.availability == "ready"
and provider.cost_tier in FREE_COST_TIERS

# Three-round stability:
latest_three = ordered_runs[:3]
len(latest_three) == 3 and all(run.outcome in SUCCESS_OUTCOMES for run in latest_three)
```

`probes()` must normalize `SourceProbeRunRecord` to `probe_type="content"` and `ProviderProbeRunRecord` to `probe_type="capability"`. `provider_detail()` and `target_detail()` return `None` for unknown IDs. `targets()` loads only each target's priority-1 method and most recent risk/probe record. Never include `headers`, environment values, or database URLs in output objects.

- [ ] **Step 6: Run focused and full model tests**

Run: `uv run pytest tests/web/test_queries.py -v`

Expected: all query tests pass.

Run: `uv run pytest tests/test_source_repository.py tests/test_provider_repository.py tests/web/test_queries.py -v`

Expected: existing repository behavior remains unchanged.

- [ ] **Step 7: Commit**

```powershell
git add src/newsradar/web/viewmodels.py src/newsradar/web/queries.py tests/web
git commit -m "feat: query dashboard coverage state"
```

---

### Task 3: Deterministic Chinese Diagnostics

**Files:**
- Create: `src/newsradar/web/diagnostics.py`
- Create: `tests/web/test_diagnostics.py`

**Interfaces:**
- Consumes: `DashboardSummary`, `list[ProviderRow]`, and `tuple[GapGroup, ...]`.
- Produces: `DiagnosticNarrative(current_capability, blind_spots, next_steps)` through `build_diagnostic_narrative(...)`.

- [ ] **Step 1: Write failing narrative tests**

```python
def test_diagnostic_distinguishes_catalog_from_content(summary, providers, gaps):
    result = build_diagnostic_narrative(summary, providers, gaps)
    assert "已登记" in result.current_capability
    assert "不代表已经抓取新闻" in result.current_capability
    assert "X" in result.blind_spots
    assert "付费" in result.next_steps


def test_diagnostic_handles_no_probe_history(summary_without_probes, providers, gaps):
    result = build_diagnostic_narrative(summary_without_probes, providers, gaps)
    assert "尚无内容探测历史" in result.current_capability
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/web/test_diagnostics.py -v`

Expected: FAIL because `newsradar.web.diagnostics` is missing.

- [ ] **Step 3: Implement deterministic rules**

Define:

```python
@dataclass(frozen=True, slots=True)
class DiagnosticNarrative:
    current_capability: str
    blind_spots: str
    next_steps: str


def build_diagnostic_narrative(
    summary: DashboardSummary,
    providers: Sequence[ProviderRow],
    gaps: Sequence[GapGroup],
) -> DiagnosticNarrative:
    # Use counts and the top three gap groups only.
    # Do not call a model and do not claim that catalog targets are fetched news.
```

Use fixed sentence templates. Sort gaps by `target_count` descending then label. Recommend, in order: enable free credentials, request approvals, preserve indirect discovery, and only then evaluate paid sources. If no probe timestamp exists, explicitly say “尚无内容探测历史，当前只能判断目录覆盖”。

- [ ] **Step 4: Run tests and commit**

Run: `uv run pytest tests/web/test_diagnostics.py -v && uv run ruff check src/newsradar/web/diagnostics.py tests/web/test_diagnostics.py`

Expected: all pass.

```powershell
git add src/newsradar/web/diagnostics.py tests/web/test_diagnostics.py
git commit -m "feat: explain source capability in Chinese"
```

---

### Task 4: FastAPI Application Shell, Safety, and Failure Pages

**Files:**
- Create: `src/newsradar/web/app.py`
- Create: `src/newsradar/web/templates/base.html`
- Create: `src/newsradar/web/templates/error.html`
- Create: `src/newsradar/web/templates/not_found.html`
- Create: `src/newsradar/web/static/styles.css`
- Create: `src/newsradar/web/static/app.js`
- Modify: `src/newsradar/web/__init__.py`
- Create: `tests/web/test_routes.py`

**Interfaces:**
- Consumes: `DashboardQueryService`, `create_session()` and Jinja templates.
- Produces: `create_app(service_factory: Callable[[], ContextManager[DashboardQueryService]] | None = None) -> FastAPI`.

- [ ] **Step 1: Write failing application-shell tests**

```python
def test_root_renders_chinese_read_only_shell(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "总览指挥台" in response.text
    assert "只读本机模式" in response.text


def test_security_headers_are_present(client):
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_unknown_route_is_chinese_404(client):
    response = client.get("/missing")
    assert response.status_code == 404
    assert "页面不存在" in response.text
```

Create a `FakeDashboardService` in the test module returning typed fixed values. The `client` fixture calls `create_app(lambda: fake_service_context())` so route tests never require PostgreSQL.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run pytest tests/web/test_routes.py -v`

Expected: FAIL because `create_app` does not exist.

- [ ] **Step 3: Build the application factory and safe session context**

`create_app()` must mount `/static`, configure Jinja, and add:

```python
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; "
        "img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
    )
    return response
```

The production service context opens `create_session()`, yields `DashboardQueryService(session)`, and always closes the session. Catch `OperationalError` and missing-table `ProgrammingError` at the route boundary and render `error.html` with the correct safe command. Never render exception text.

- [ ] **Step 4: Build accessible shell styles**

`base.html` contains a skip link, semantic `aside/nav/main`, five navigation links, database/status header, and blocks `title`, `header`, `content`, `scripts`. Use Jinja autoescape and no `|safe` filter.

`styles.css` defines exact status tokens:

```css
:root {
  --bg: #080d17;
  --panel: #101827;
  --panel-2: #151f31;
  --text: #eef5ff;
  --muted: #91a0b6;
  --line: #25324a;
  --healthy: #65e6c4;
  --info: #78a7ff;
  --blocked: #f5b95f;
  --failed: #ff7383;
  --focus: #b4c9ff;
}
```

All interactive elements have visible `:focus-visible`. At `max-width: 760px`, the sidebar becomes a top navigation drawer controlled by a button with `aria-expanded`; without JavaScript, links remain visible in normal document flow.

- [ ] **Step 5: Run shell tests**

Run: `uv run pytest tests/web/test_routes.py -v`

Expected: shell, headers, 404, and safe error tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/newsradar/web tests/web/test_routes.py
git commit -m "feat: add safe local dashboard shell"
```

---

### Task 5: A-Style Overview Command Center

**Files:**
- Create: `src/newsradar/web/templates/dashboard.html`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/static/styles.css`
- Modify: `tests/web/test_routes.py`

**Interfaces:**
- Consumes: `summary()`, `providers()`, `probes()`, `gap_groups()`, and `build_diagnostic_narrative()`.
- Produces: `GET /` dashboard with linked metric filters.

- [ ] **Step 1: Add failing overview assertions**

```python
def test_dashboard_shows_strict_metrics_and_diagnostic(client):
    response = client.get("/")
    assert response.status_code == 200
    for text in ("Provider 总数", "Target 总数", "免费直接覆盖", "间接发现", "阻塞目标", "连续三轮成功"):
        assert text in response.text
    assert "当前能感知" in response.text
    assert "主要盲区" in response.text
    assert "建议下一步" in response.text
    assert 'href="/targets?coverage_mode=direct&amp;availability=ready"' in response.text
```

- [ ] **Step 2: Run and verify missing overview**

Run: `uv run pytest tests/web/test_routes.py::test_dashboard_shows_strict_metrics_and_diagnostic -v`

Expected: FAIL because the dashboard content is absent.

- [ ] **Step 3: Implement dashboard route and template**

The route opens one service context, reads all required values once, and passes only ViewModels to Jinja. `dashboard.html` renders:

- six linked metric cards;
- seven category distribution rows with count and proportional CSS bar;
- three diagnostic panels using plain escaped strings;
- latest ten probe rows with type labels;
- top five gap groups with unlock links.

Use real counts from the service. If `latest_probe_at is None`, render “暂无探测历史” rather than a percentage. Metric links use URL query parameters exactly as tested.

- [ ] **Step 4: Add responsive command-center CSS**

Desktop uses a 12-column grid: metrics span two columns each, category distribution spans seven, diagnostic spans five, and lower tables span six each. At 1100px switch to two columns; at 760px use one column. Do not use canvas or SVG charts; bars are semantic HTML with CSS widths and text counts.

- [ ] **Step 5: Run route tests and commit**

Run: `uv run pytest tests/web/test_routes.py -v`

Expected: all route tests pass.

```powershell
git add src/newsradar/web/app.py src/newsradar/web/templates/dashboard.html src/newsradar/web/static/styles.css tests/web/test_routes.py
git commit -m "feat: render source command center"
```

---

### Task 6: Provider and Target Catalog with Details

**Files:**
- Create: `src/newsradar/web/templates/providers.html`
- Create: `src/newsradar/web/templates/provider_detail.html`
- Create: `src/newsradar/web/templates/targets.html`
- Create: `src/newsradar/web/templates/target_detail.html`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/static/styles.css`
- Modify: `tests/web/test_routes.py`

**Interfaces:**
- Consumes: query service provider/target list and detail methods.
- Produces: `GET /providers`, `/providers/{provider_id}`, `/targets`, and `/targets/{source_id}`.

- [ ] **Step 1: Add failing list, filter, detail, and redaction tests**

```python
def test_provider_filter_is_forwarded(client, fake_service):
    response = client.get("/providers?availability=requires_payment&cost_tier=paid&q=X")
    assert response.status_code == 200
    assert fake_service.provider_filters == {
        "availability": "requires_payment", "cost_tier": "paid", "q": "X"
    }


def test_target_detail_explains_access_and_risk_without_secrets(client):
    response = client.get("/targets/github-openai-python")
    assert response.status_code == 200
    assert "首选访问方式" in response.text
    assert "风险分项" in response.text
    assert "GITHUB_TOKEN" in response.text
    assert "secret-token-value" not in response.text
    assert "Authorization" not in response.text


def test_unknown_provider_and_target_return_404(client):
    assert client.get("/providers/unknown").status_code == 404
    assert client.get("/targets/unknown").status_code == 404
```

- [ ] **Step 2: Run and verify route failures**

Run: `uv run pytest tests/web/test_routes.py -v`

Expected: FAIL with 404 for the new valid routes.

- [ ] **Step 3: Implement validated filter models and list routes**

Use FastAPI query parameters typed as current enum strings or `None`; trim `q` to 100 characters. Preserve active filters in the template and render a real GET form. Provider columns: name, category, cost, auth, availability, capabilities, target counts, latest capability probe, reviewed date. Target columns: name, provider, type, roles, coverage, availability, primary protocol, risk, latest content time, latest content probe.

- [ ] **Step 4: Implement detail routes and templates**

Provider detail must show official homepage, docs, terms, evidence, environment variable names, unlock steps, related targets, and latest capability probes. Target detail must show audited metadata, primary/fallback methods, expected fields, risk breakdown, latest sample completeness, latest three content probes, and evidence.

External links use `target="_blank" rel="noopener noreferrer"`. Display environment variable names only. Do not pass `SourceAccessMethodRecord.headers` to a template.

- [ ] **Step 5: Add table accessibility and mobile behavior**

Wrap each table in a labeled horizontal scroll region with `tabindex="0"`. Keep name, availability, coverage, and result columns present at every width. Filters stack vertically below 760px.

- [ ] **Step 6: Run tests and commit**

Run: `uv run pytest tests/web/test_routes.py tests/web/test_queries.py -v`

Expected: all tests pass.

```powershell
git add src/newsradar/web tests/web
git commit -m "feat: browse provider and target capabilities"
```

---

### Task 7: Probe History and Blocked-Coverage Gaps

**Files:**
- Create: `src/newsradar/web/templates/probes.html`
- Create: `src/newsradar/web/templates/gaps.html`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/static/styles.css`
- Modify: `tests/web/test_routes.py`
- Modify: `tests/web/test_queries.py`

**Interfaces:**
- Consumes: `DashboardQueryService.probes(filters)` and `gap_groups()`.
- Produces: `GET /probes` and `GET /gaps`.

- [ ] **Step 1: Add failing distinction and restricted-platform tests**

```python
def test_probe_page_visibly_distinguishes_probe_types(client):
    response = client.get("/probes")
    assert response.status_code == 200
    assert "能力探测" in response.text
    assert "内容探测" in response.text
    assert "原始原因" in response.text


def test_gap_page_keeps_restricted_platforms_visible(client):
    response = client.get("/gaps")
    assert response.status_code == 200
    for platform in ("X", "Facebook", "Instagram", "TikTok", "LinkedIn"):
        assert platform in response.text
    assert "不等于实时内容覆盖" in response.text
    assert "不会使用 Cookie" in response.text
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run pytest tests/web/test_routes.py -v`

Expected: FAIL because routes are missing.

- [ ] **Step 3: Implement probe route and filters**

Support `probe_type`, `outcome`, `provider_id`, `from_date`, and `to_date`. Default order is `checked_at DESC`. Render type badge, object, outcome, HTTP status, latency, completeness only for content probes, Chinese explanation, and a disclosure element containing escaped raw reason. Capability rows explicitly say “只确认平台能力，不代表获取到内容”.

- [ ] **Step 4: Implement gap grouping and unlock view**

`gap_groups()` returns groups in this fixed order: credentials, approval, payment, manual, unavailable. Each target shows Provider, impact, current indirect alternative, cost label, unlock steps, and evidence. If an alternative does not exist, display “无已审核替代路径”.

The page always includes the compliance notice and renders restricted platforms from current database records, never from hard-coded successful coverage claims.

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest tests/web/test_routes.py tests/web/test_queries.py -v`

Expected: all tests pass.

```powershell
git add src/newsradar/web tests/web
git commit -m "feat: explain probe history and coverage gaps"
```

---

### Task 8: Local CLI, Safe Operational Errors, and Documentation

**Files:**
- Modify: `src/newsradar/cli.py`
- Modify: `README.md`
- Create: `tests/web/test_cli.py`
- Modify: `tests/web/test_routes.py`

**Interfaces:**
- Consumes: `newsradar.web.create_app`.
- Produces: `newsradar web --host 127.0.0.1 --port 8765`.

- [ ] **Step 1: Add failing CLI default test**

```python
from typer.testing import CliRunner
from newsradar.cli import app


def test_web_command_uses_local_only_defaults(monkeypatch):
    called = {}

    def fake_run(application, *, host, port, log_level):
        called.update(host=host, port=port, log_level=log_level)

    monkeypatch.setattr("uvicorn.run", fake_run)
    result = CliRunner().invoke(app, ["web"])
    assert result.exit_code == 0
    assert called == {"host": "127.0.0.1", "port": 8765, "log_level": "info"}
```

- [ ] **Step 2: Run and verify missing command**

Run: `uv run pytest tests/web/test_cli.py -v`

Expected: FAIL because the command does not exist.

- [ ] **Step 3: Implement CLI without reload or public defaults**

Add:

```python
@app.command("web")
def run_web(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8765,
) -> None:
    import uvicorn
    from newsradar.web import create_app

    uvicorn.run(create_app(), host=host, port=port, log_level="info")
```

Do not add `reload=True`. Keep the host option available for explicit expert use, but documentation only advertises the safe default command.

- [ ] **Step 4: Test safe PostgreSQL failure messages**

Add route tests that make the service context raise `OperationalError` and `ProgrammingError`. Assert the rendered page contains respectively `uv run newsradar db start` and `uv run alembic upgrade head`, does not contain exception text, and returns HTTP 503.

- [ ] **Step 5: Document local usage and meaning**

Add a `## Chinese source dashboard` section to README with:

```powershell
uv run newsradar db start
uv run alembic upgrade head
uv run newsradar providers sync --root providers
uv run newsradar sources sync --root sources
uv run newsradar web
```

Document `http://127.0.0.1:8765`, read-only behavior, no MiniMax calls, and the distinction between registered, directly readable, indirectly discoverable, capability-probed, and content-probed.

- [ ] **Step 6: Run CLI and route tests**

Run: `uv run pytest tests/web/test_cli.py tests/web/test_routes.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/newsradar/cli.py README.md tests/web
git commit -m "feat: run dashboard on local host"
```

---

### Task 9: Full Verification and Browser Acceptance

**Files:**
- Modify only files required by failures found in this task.

**Interfaces:**
- Consumes: complete dashboard implementation and local PostgreSQL data.
- Produces: verified local dashboard matching the approved design.

- [ ] **Step 1: Run the complete automated suite**

Run: `uv run ruff check .`

Expected: no lint errors.

Run: `uv run pytest`

Expected: all existing and new tests pass.

- [ ] **Step 2: Confirm the database and current registry**

Run:

```powershell
uv run newsradar db start
uv run alembic upgrade head
uv run newsradar providers sync --root providers
uv run newsradar sources sync --root sources
```

Expected: local database starts, migrations are current, and sync reports 67 providers and 161 targets with no destructive change.

- [ ] **Step 3: Start the dashboard and inspect real data**

Run in a retained terminal: `uv run newsradar web`

Expected: Uvicorn reports `http://127.0.0.1:8765`.

Open the exact URL in the in-app browser. Verify the first viewport contains Provider total, Target total, direct, indirect, blocked, three-round stability, and the three-part Chinese diagnostic.

- [ ] **Step 4: Perform desktop interaction acceptance**

At 1440px width:

1. Click the free-direct metric and confirm `/targets` opens with direct/ready filters.
2. Open one Provider and then one related Target.
3. Confirm target access method, risk, and probe history render.
4. Open `/probes` and confirm capability/content labels differ.
5. Open `/gaps` and confirm X, Facebook, Instagram, TikTok, and LinkedIn are visible with unlock requirements.
6. Search rendered HTML for `MINIMAX_API_KEY`, `DATABASE_URL`, `Authorization`, and `Cookie`; none may appear.

- [ ] **Step 5: Perform mobile and no-JavaScript acceptance**

At 390px width, verify navigation, cards, filters, and scrollable tables remain usable. Disable JavaScript and reload; confirm all five routes and detail links remain readable and navigable.

- [ ] **Step 6: Re-run verification after any acceptance fix**

Run: `uv run ruff check . && uv run pytest`

Expected: both commands pass after final changes.

- [ ] **Step 7: Commit final acceptance fixes if any**

```powershell
git add src tests README.md pyproject.toml uv.lock
git commit -m "fix: complete dashboard acceptance"
```

If no files changed, do not create an empty commit.

---

## Completion Checklist

- [ ] `uv run newsradar web` binds to `127.0.0.1:8765`.
- [ ] The A-style overview shows real PostgreSQL counts and deterministic Chinese diagnostics.
- [ ] Provider, Target, probes, and gaps are independently navigable and filterable.
- [ ] Capability checks and content checks are visibly distinct.
- [ ] Restricted social platforms remain visible with real unlock conditions.
- [ ] No write action or secret value is available through the web UI.
- [ ] Desktop, mobile, keyboard, and no-JavaScript acceptance passes.
- [ ] `uv run ruff check .` and `uv run pytest` pass.
