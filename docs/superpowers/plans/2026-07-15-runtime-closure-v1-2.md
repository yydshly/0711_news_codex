# News Codex v1.2 运行闭环收口实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 MiniMax、Web、Worker、来源目录和探测能力收口为一个可由 `newsradar serve` 启动、状态可见、历史可审计的本机运行闭环。

**Architecture:** 保留现有 FastAPI + Typer + PostgreSQL + SQLAlchemy 架构；通过 MiniMax 脱敏检查器、Worker 空闲心跳、来源 current/archived 投影和有界健康波次补足运行缺口。Web 继续只读展示和任务入队，Worker 继续独占正式抓取与事件处理。

**Tech Stack:** Python 3.12、Typer、FastAPI、SQLAlchemy 2、Alembic、Pydantic 2、HTTPX、PostgreSQL、pytest、Ruff。

## Global Constraints

- 暂不使用 Docker，不新增 Windows 服务、计划任务、PID 后台管理器或网页进程启停按钮。
- 所有新增行为必须使用测试先行的 Red-Green-Refactor 循环。
- MiniMax Key 只写入 Git 忽略的根目录 `.env`，不得出现在命令输出、数据库正文、日志、报告、诊断包、网页或 Git。
- `MINIMAX_DEEP_MODEL=MiniMax-M2.7`，`MINIMAX_FAST_MODEL=MiniMax-M2.7-highspeed`。
- 历史来源只能归档，禁止删除 RawItem、FetchRun、Probe 或 Event 证据。
- HTML 策略阻塞不得自动降级为可抓取；Reddit 不得回退 Cookie 或登录态。
- 本计划不实现定时抓取、中文日报、提醒、实体抽取、推荐或个性化。
- 实施分支固定为 `codex/runtime-closure-v1-2`，工作树固定为 `.worktrees/runtime-closure-v1-2`。

---

## 文件职责映射

### 新建文件

- `src/newsradar/ai/health.py`：MiniMax 配置检查、模型可见性检查和脱敏结果类型。
- `src/newsradar/sources/catalog_reconcile.py`：目录 current/archived 对账计划与应用服务。
- `src/newsradar/sources/health_wave.py`：健康波次选择、执行摘要和中文报告渲染。
- `migrations/versions/20260715_0016_runtime_closure_v1_2.py`：来源目录归档字段与约束。
- `tests/test_minimax_health.py`：MiniMax 配置及 live 检查测试。
- `tests/test_catalog_reconcile.py`：目录对账和历史保留测试。
- `tests/test_source_health_wave.py`：健康波次选择、并发与报告测试。
- `tests/acceptance/test_runtime_closure_v1_2.py`：PostgreSQL、CLI、Web、Worker 总体验收。
- `reports/runtime-closure-v1-2.md`：真实运行验收报告。
- `reports/source-health-v1-2.md`：真实健康波次报告。

### 修改文件

- `src/newsradar/settings.py`、`.env.example`：MiniMax 当前官方模型默认值。
- `src/newsradar/ai/minimax.py`：复用现有结构化调用，不改变模型决策边界。
- `src/newsradar/cli.py`：新增 `minimax check`、`sources reconcile`、`sources health-wave`，扩展 `serve` 参数。
- `src/newsradar/runtime.py`：将 host、port、worker-id 传给两个子进程。
- `src/newsradar/operations/repository.py`、`src/newsradar/operations/worker.py`：空闲心跳和 idle/running 状态。
- `src/newsradar/db/models.py`：来源归档字段。
- `src/newsradar/sources/repository.py`：归档来源重新同步时恢复 current。
- `src/newsradar/sources/probes/runner.py`：有界并发且单源异常隔离。
- `src/newsradar/web/routes/system.py`、`src/newsradar/web/app.py`、`src/newsradar/web/templates/system.html`：Worker 与 MiniMax 中文状态。
- `src/newsradar/web/capability_queries.py`、`src/newsradar/web/queries.py`、`src/newsradar/web/templates/capability_overview.html`：历史归档统计与目录漂移口径。
- `src/newsradar/web/templates/targets.html`、Target 查询层：默认 current、显式 archived。
- `README.md`：唯一推荐运行入口和诊断命令。

---

### Task 1: MiniMax 主运行时与脱敏健康检查

**Files:**
- Create: `src/newsradar/ai/health.py`
- Create: `tests/test_minimax_health.py`
- Modify: `src/newsradar/settings.py`
- Modify: `src/newsradar/cli.py`
- Modify: `.env.example`
- Modify: `README.md`
- Test: `tests/test_minimax.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `MiniMaxConfigView`、`MiniMaxLiveCheck`、`check_minimax_config(settings)`、`check_minimax_live(settings, http, usage_sink)`。
- Produces CLI: `newsradar minimax check [--live]`。
- Consumes: `Settings`、`MiniMaxClient.infer_source_topics()`、`SourceRepository.save_model_usage()`。

- [ ] **Step 1: 写失败测试，锁定官方模型默认值与无网络配置检查**

```python
from newsradar.ai.health import check_minimax_config
from newsradar.settings import Settings


def test_minimax_defaults_use_current_official_models() -> None:
    settings = Settings(_env_file=None)
    assert settings.minimax_deep_model == "MiniMax-M2.7"
    assert settings.minimax_fast_model == "MiniMax-M2.7-highspeed"


def test_config_check_reports_region_without_exposing_key() -> None:
    result = check_minimax_config(
        Settings(
            _env_file=None,
            minimax_api_key="secret-value",
            minimax_base_url="https://api.minimaxi.com",
        )
    )
    assert result.configured is True
    assert result.region == "china"
    assert "secret-value" not in repr(result)
```

- [ ] **Step 2: 运行失败测试并确认失败原因**

Run: `D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/test_minimax_health.py -q`

Expected: FAIL，因为 `newsradar.ai.health` 尚不存在且 deep model 仍为 `MiniMax-M3`。

- [ ] **Step 3: 实现配置投影和当前官方默认值**

```python
@dataclass(frozen=True, slots=True)
class MiniMaxConfigView:
    configured: bool
    region: Literal["china", "international", "custom"]
    fast_model: str
    deep_model: str


def check_minimax_config(settings: Settings) -> MiniMaxConfigView:
    host = urlsplit(settings.minimax_base_url).hostname
    region = (
        "china" if host == "api.minimaxi.com"
        else "international" if host == "api.minimax.io"
        else "custom"
    )
    return MiniMaxConfigView(
        configured=settings.minimax_api_key is not None,
        region=region,
        fast_model=settings.minimax_fast_model,
        deep_model=settings.minimax_deep_model,
    )
```

同时修改 `Settings.minimax_deep_model`、`.env.example` 和 README 为 `MiniMax-M2.7`。

- [ ] **Step 4: 写失败测试，锁定 live 模型检查、结构化调用和脱敏输出**

```python
@pytest.mark.asyncio
async def test_live_check_queries_model_and_records_structured_usage() -> None:
    usages: list[ModelUsage] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-value"
        if request.method == "GET":
            assert request.url.path == "/v1/models/MiniMax-M2.7-highspeed"
            return httpx.Response(200, json={"id": "MiniMax-M2.7-highspeed"}, request=request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"topics":["agents"],"confidence":0.9}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
            request=request,
        )

    settings = Settings(
        _env_file=None,
        minimax_api_key="secret-value",
        minimax_base_url="https://api.minimaxi.com",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await check_minimax_live(settings, http, usages.append)

    assert result.model_visible is True
    assert result.structured_outcome == "success"
    assert usages[-1].outcome == "success"
    assert "secret-value" not in repr(result)
```

- [ ] **Step 5: 运行失败测试，确认缺少 live 接口**

Run: `D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/test_minimax_health.py -q`

Expected: FAIL，因为 `check_minimax_live` 尚不存在。

- [ ] **Step 6: 实现 live 检查与 CLI**

`check_minimax_live()` 必须：

```python
response = await http.get(
    f"{settings.minimax_base_url.rstrip('/')}/v1/models/{settings.minimax_fast_model}",
    headers={"Authorization": f"Bearer {settings.minimax_api_key.get_secret_value()}"},
    timeout=settings.event_model_timeout_seconds,
)
```

模型可见后调用一次 `MiniMaxClient(..., usage_sink).infer_source_topics("AI agent SDK release")`。CLI 默认只调用 `check_minimax_config()`；只有 `--live` 才创建 HTTP 客户端和数据库 usage sink。终端不得输出模型正文。

- [ ] **Step 7: 验证 Task 1**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/test_minimax_health.py tests/test_minimax.py tests/test_cli.py -q
D:\codex_project_work\news_codex\.venv\Scripts\ruff.exe check src/newsradar/ai src/newsradar/settings.py src/newsradar/cli.py tests/test_minimax_health.py
```

Expected: 全部 PASS，Ruff 无错误。

- [ ] **Step 8: 提交 Task 1**

```powershell
git add .env.example README.md src/newsradar/settings.py src/newsradar/ai/health.py src/newsradar/cli.py tests/test_minimax_health.py tests/test_minimax.py tests/test_cli.py
git commit -m "feat: close minimax runtime configuration"
```

---

### Task 2: Worker 空闲心跳与统一 `serve`

**Files:**
- Modify: `src/newsradar/operations/repository.py`
- Modify: `src/newsradar/operations/worker.py`
- Modify: `src/newsradar/runtime.py`
- Modify: `src/newsradar/cli.py`
- Modify: `tests/operations/test_repository.py`
- Modify: `tests/operations/test_worker.py`
- Modify: `tests/test_runtime.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `OperationRepository.heartbeat_worker(worker_id, status="idle") -> None`。
- Produces: `RuntimeSupervisor(host, port, worker_id, process_factory=None)`。
- Produces CLI: `newsradar serve --host --port --worker-id`。
- Consumes: `Worker.run_once()`、`WorkerRecord`、现有租约续期逻辑。

- [ ] **Step 1: 写失败测试，锁定 idle/running 状态机**

```python
def test_worker_without_operation_persists_idle_heartbeat(db_session) -> None:
    worker = Worker(OperationRepository(db_session), "idle-worker")
    assert worker.run_once(lambda *_: None) is False
    record = db_session.get(WorkerRecord, "idle-worker")
    assert record is not None
    assert record.status == "idle"
    assert record.current_operation_run_id is None
    assert record.last_heartbeat_at is not None


def test_finished_operation_returns_worker_to_idle(db_session) -> None:
    operation = OperationRepository(db_session).enqueue(OperationType.FETCH, {})
    db_session.commit()
    Worker(OperationRepository(db_session), "worker-a").run_once(lambda *_: None)
    record = db_session.get(WorkerRecord, "worker-a")
    assert record.status == "idle"
    assert record.current_operation_run_id is None
    assert db_session.get(OperationRunRecord, operation.id).status == "succeeded"
```

- [ ] **Step 2: 运行失败测试**

Run: `D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/operations/test_worker.py tests/operations/test_repository.py -q`

Expected: FAIL，因为空队列不创建 Worker，完成后状态仍为 `running`。

- [ ] **Step 3: 实现 Worker 心跳状态机**

```python
def heartbeat_worker(self, worker_id: str, *, status: str = "idle") -> None:
    if status not in {"idle", "running"}:
        raise ValueError("worker status must be idle or running")
    with self._transaction():
        worker = self._ensure_worker(worker_id)
        if worker.current_operation_run_id is not None and status == "idle":
            return
        worker.last_heartbeat_at = self._now()
        worker.status = status
```

`Worker.run_once()` 在 `lease_next()` 前调用 `heartbeat_worker(..., status="idle")`；租用后保持 `running`；`finish_attempt()` 将当前 Worker 恢复 `idle`。

- [ ] **Step 4: 写失败测试，锁定 serve 参数传递**

```python
def test_supervisor_passes_runtime_options_to_children() -> None:
    specs = RuntimeSupervisor(
        host="127.0.0.1", port=8766, worker_id="newsradar-local"
    ).specifications()
    assert specs[0].args[-5:] == ("web", "--host", "127.0.0.1", "--port", "8766")
    assert specs[1].args[-3:] == ("--worker-id", "newsradar-local", "--forever")
```

- [ ] **Step 5: 实现参数化 RuntimeSupervisor 和 CLI**

`RuntimeSupervisor` 保存 host、port、worker-id；实例方法 `specifications()` 返回两个 `ChildSpec`。`serve()` 增加 Typer 参数并传入 supervisor。保留现有异常退出与 Ctrl+C 联动停止行为。

- [ ] **Step 6: 验证 Task 2**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/operations tests/test_runtime.py tests/test_cli.py tests/acceptance/test_worker_recovery.py -q
D:\codex_project_work\news_codex\.venv\Scripts\ruff.exe check src/newsradar/operations src/newsradar/runtime.py src/newsradar/cli.py tests/operations tests/test_runtime.py
```

Expected: 全部 PASS。

- [ ] **Step 7: 提交 Task 2**

```powershell
git add src/newsradar/operations/repository.py src/newsradar/operations/worker.py src/newsradar/runtime.py src/newsradar/cli.py tests/operations tests/test_runtime.py tests/test_cli.py
git commit -m "feat: expose reliable local runtime state"
```

---

### Task 3: `/system` MiniMax 与 Worker 中文状态

**Files:**
- Modify: `src/newsradar/web/routes/system.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/system.html`
- Modify: `tests/web/test_system.py`
- Modify: `tests/web/test_security.py`

**Interfaces:**
- Produces: `SystemHealth` 新字段 `online_worker_count`、`idle_worker_count`、`busy_worker_count`、`stale_worker_count`、`last_worker_heartbeat_at`。
- Produces: `MiniMaxRuntimeView`，只包含配置布尔值、区域、模型和安全 usage 汇总。
- Consumes: `check_minimax_config()`、`ModelUsageRecord`、`WorkerRecord`。

- [ ] **Step 1: 写失败测试，锁定 Worker 中文状态投影**

```python
def test_system_health_distinguishes_idle_busy_and_stale(db_session) -> None:
    now = datetime.now(UTC)
    db_session.add_all([
        WorkerRecord(worker_id="idle", hostname="local", started_at=now,
                     last_heartbeat_at=now, status="idle"),
        WorkerRecord(worker_id="busy", hostname="local", started_at=now,
                     last_heartbeat_at=now, status="running", current_operation_run_id=1),
        WorkerRecord(worker_id="stale", hostname="local", started_at=now,
                     last_heartbeat_at=now - timedelta(minutes=10), status="idle"),
    ])
    db_session.commit()
    health = build_system_health(db_session, now=now)
    assert health.idle_worker_count == 1
    assert health.busy_worker_count == 1
    assert health.stale_worker_count == 1
```

- [ ] **Step 2: 运行失败测试并实现新投影**

Run: `D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/web/test_system.py -q`

Expected: FAIL，因为新字段不存在。

实现时使用一个有界 Worker 查询，在 Python 中按 5 分钟阈值分类；不得枚举操作系统进程。

- [ ] **Step 3: 写失败测试，锁定 MiniMax 页面脱敏和运行说明**

```python
def test_system_page_shows_minimax_summary_without_secrets(monkeypatch, db_session) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "secret-value")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.minimaxi.com")
    get_settings.cache_clear()
    response = TestClient(create_app()).get("/system")
    assert "MiniMax 运行状态" in response.text
    assert "中国区" in response.text
    assert "MiniMax-M2.7-highspeed" in response.text
    assert "newsradar serve --host 127.0.0.1 --port 8766" in response.text
    assert "secret-value" not in response.text
    assert "api.minimaxi.com" not in response.text
```

- [ ] **Step 4: 实现 `/system` 卡片**

模板显示四种 Worker 文案和 MiniMax 安全 usage 汇总；增加启动/停止说明但不增加表单或按钮。测试后清理 `get_settings` 缓存。

- [ ] **Step 5: 验证 Task 3**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/web/test_system.py tests/web/test_security.py tests/web/test_routes.py -q
D:\codex_project_work\news_codex\.venv\Scripts\ruff.exe check src/newsradar/web tests/web
```

Expected: 全部 PASS，页面不含敏感值。

- [ ] **Step 6: 提交 Task 3**

```powershell
git add src/newsradar/web/routes/system.py src/newsradar/web/app.py src/newsradar/web/templates/system.html tests/web/test_system.py tests/web/test_security.py
git commit -m "feat: explain minimax and worker runtime health"
```

---

### Task 4: 来源 current/archived 对账

**Files:**
- Create: `migrations/versions/20260715_0016_runtime_closure_v1_2.py`
- Create: `src/newsradar/sources/catalog_reconcile.py`
- Create: `tests/test_catalog_reconcile.py`
- Modify: `src/newsradar/db/models.py`
- Modify: `src/newsradar/sources/repository.py`
- Modify: `src/newsradar/cli.py`
- Modify: `src/newsradar/web/capability_queries.py`
- Modify: Target 查询层与 `src/newsradar/web/templates/targets.html`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_source_repository.py`
- Modify: `tests/web/test_capability_queries.py`
- Modify: `tests/web/test_routes.py`

**Interfaces:**
- Produces: `CatalogReconcilePlan`、`build_reconcile_plan(session, yaml_ids)`、`apply_reconcile_plan(session, plan)`。
- Produces CLI: `newsradar sources reconcile [--apply]`。
- Produces DB: `catalog_state`、`catalog_archived_at`、`catalog_archive_reason`。

- [ ] **Step 1: 写迁移失败测试**

```python
def test_runtime_closure_migration_adds_catalog_archive_columns(postgres_url) -> None:
    upgrade(postgres_url, "20260715_0016")
    with create_engine(postgres_url).connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("source_definitions")}
        assert {"catalog_state", "catalog_archived_at", "catalog_archive_reason"} <= columns
        assert connection.execute(text("select count(*) from source_definitions where catalog_state='current'")).scalar_one() >= 0
```

- [ ] **Step 2: 实现迁移和 ORM 字段**

迁移增加非空 `catalog_state`，服务端默认 `current`，以及归档时间/原因；添加 `catalog_state IN ('current','archived')` CheckConstraint。降级只删除新增字段和约束，不删除来源数据。

- [ ] **Step 3: 写失败测试，锁定只读计划、阻塞保护和恢复 current**

```python
def yaml_source(source_id: str) -> SourceDefinition:
    payload = valid_source()
    payload["id"] = source_id
    payload["name"] = source_id
    return SourceDefinition.model_validate(payload)


def seed_source(db_session, source_id: str) -> SourceDefinitionRecord:
    SourceRepository(db_session).sync([yaml_source(source_id)])
    db_session.commit()
    return db_session.get(SourceDefinitionRecord, source_id)


def test_reconcile_archives_only_missing_yaml_sources(db_session) -> None:
    seed_source(db_session, "keep")
    seed_source(db_session, "legacy")
    plan = build_reconcile_plan(db_session, {"keep"})
    assert plan.archive_ids == ("legacy",)
    assert db_session.get(SourceDefinitionRecord, "legacy").catalog_state == "current"
    apply_reconcile_plan(db_session, plan)
    assert db_session.get(SourceDefinitionRecord, "legacy").catalog_state == "archived"
    assert db_session.get(SourceDefinitionRecord, "keep").catalog_state == "current"


def test_sync_restores_archived_source(db_session) -> None:
    record = seed_source(db_session, "alpha")
    record.catalog_state = "archived"
    record.catalog_archived_at = datetime.now(UTC)
    record.catalog_archive_reason = "absent_from_current_yaml"
    db_session.commit()
    SourceRepository(db_session).sync([yaml_source("alpha")])
    assert record.catalog_state == "current"
    assert record.catalog_archived_at is None
```

另写测试：存在 queued/running Operation 的 source ID 时 `apply_reconcile_plan()` 抛出 `CatalogReconcileBlocked`，且不修改任何状态。

- [ ] **Step 4: 实现对账服务和 CLI**

```python
@dataclass(frozen=True, slots=True)
class CatalogReconcilePlan:
    yaml_count: int
    current_db_count: int
    archive_ids: tuple[str, ...]
    restore_ids: tuple[str, ...]
    blocked_ids: tuple[str, ...]
```

CLI 默认只打印计划；`--apply` 在单个事务中应用。固定归档原因 `absent_from_current_yaml`。

- [ ] **Step 5: 写失败测试并修改能力与 Target 查询**

测试 `/targets` 默认不出现 archived，`?catalog_state=archived` 只显示 archived；能力总览的 drift 排除 archived，并显示归档数量与链接。

- [ ] **Step 6: 验证 Task 4**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/test_migrations.py tests/test_source_repository.py tests/test_catalog_reconcile.py tests/web/test_capability_queries.py tests/web/test_routes.py -q
D:\codex_project_work\news_codex\.venv\Scripts\ruff.exe check src/newsradar/db src/newsradar/sources src/newsradar/web tests/test_catalog_reconcile.py
```

Expected: 全部 PASS。

- [ ] **Step 7: 提交 Task 4**

```powershell
git add migrations/versions/20260715_0016_runtime_closure_v1_2.py src/newsradar/db/models.py src/newsradar/sources/catalog_reconcile.py src/newsradar/sources/repository.py src/newsradar/cli.py src/newsradar/web tests/test_migrations.py tests/test_source_repository.py tests/test_catalog_reconcile.py
git commit -m "feat: archive historical catalog targets safely"
```

---

### Task 5: 有界来源健康波次

**Files:**
- Create: `src/newsradar/sources/health_wave.py`
- Create: `tests/test_source_health_wave.py`
- Modify: `src/newsradar/sources/probes/runner.py`
- Modify: `src/newsradar/cli.py`
- Modify: `tests/test_probes.py`

**Interfaces:**
- Produces: `HealthProbeState`、`HealthWaveCandidate`、`HealthWavePlan`、`select_health_wave()`、`render_health_wave_report()`。
- Produces: `ProbeRunner(factory, max_concurrency=8)`。
- Produces CLI: `newsradar sources health-wave [--execute] [--concurrency] [--output]`。

- [ ] **Step 1: 写失败测试，锁定选择规则**

```python
def wave_source(
    source_id: str,
    *,
    kind: str,
    manual: bool = False,
    auth_env: str | None = None,
) -> SourceDefinition:
    payload = valid_source()
    payload["id"] = source_id
    payload["name"] = source_id
    method = {
        "kind": kind,
        "url": f"https://example.com/{source_id}",
        "priority": 1,
        "requires_manual_approval": manual,
    }
    if auth_env:
        method["auth_env"] = auth_env
    payload["access_methods"] = [method]
    return SourceDefinition.model_validate(payload)


def test_health_wave_selects_unprobed_and_latest_failed_feeds_only() -> None:
    sources = [
        wave_source("unprobed", kind="rss"),
        wave_source("rss-failed", kind="rss"),
        wave_source("html-blocked", kind="html", manual=True),
        wave_source("reddit", kind="rest_api", auth_env="REDDIT_CLIENT_ID"),
        wave_source("healthy", kind="rss"),
    ]
    latest = {
        "rss-failed": HealthProbeState("failed", "rss"),
        "html-blocked": HealthProbeState("blocked", "html"),
        "reddit": HealthProbeState("blocked", "rest_api"),
        "healthy": HealthProbeState("success", "rss"),
    }
    plan = select_health_wave(sources, latest, configured_credentials=set())
    assert [item.source.id for item in plan.candidates] == ["rss-failed", "unprobed"]
    assert plan.excluded_reasons["html_policy_blocked"] == 1
    assert plan.excluded_reasons["credential_or_permission_required"] == 1
```

- [ ] **Step 2: 运行失败测试并实现纯选择函数**

Run: `D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/test_source_health_wave.py -q`

Expected: FAIL，因为模块不存在。

选择函数不得访问网络或数据库，只消费已加载 YAML、最新探测投影和配置变量名称集合。

- [ ] **Step 3: 写失败测试，锁定最大并发与单源隔离**

```python
@pytest.mark.asyncio
async def test_probe_runner_bounds_concurrency_and_isolates_failure() -> None:
    active = 0
    peak = 0

    class FakeProbe:
        async def probe(self, source, method):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1
            if source.id == "broken":
                raise RuntimeError("boom")
            now = datetime.now(UTC)
            return ProbeResult(
                source_id=source.id,
                access_kind=method.kind.value,
                access_url=str(method.url),
                outcome=ProbeOutcome.SUCCESS,
                started_at=now,
                finished_at=now,
                suggested_status=SourceStatus.CANDIDATE,
                reason="ok",
            )

    class FakeFactory:
        def create(self, method):
            return FakeProbe()

    def runner_source(source_id: str) -> SourceDefinition:
        source = source_with(
            {"kind": "rss", "url": f"https://example.com/{source_id}", "priority": 1}
        )
        return source.model_copy(update={"id": source_id, "name": source_id})

    runner = ProbeRunner(FakeFactory(), max_concurrency=2)
    results = await runner.probe_all(
        [runner_source("a"), runner_source("broken"), runner_source("c")]
    )
    assert peak <= 2
    assert results["a"].outcome == ProbeOutcome.SUCCESS
    assert results["broken"].outcome == ProbeOutcome.FAILED
    assert results["broken"].error_code == "internal_probe_error"
```

- [ ] **Step 4: 实现有界 ProbeRunner**

使用 `asyncio.Semaphore(max_concurrency)` 包裹 `probe_one()`；将未预期异常转换为不含异常正文的安全失败 `ProbeResult`。构造失败结果时必须使用来源 ID、首选访问方式、当前时间和固定错误码。

- [ ] **Step 5: 写失败测试并实现计划/执行 CLI 与中文报告**

默认命令只输出选择清单并写计划报告，不调用 `_probe_sources()`；`--execute` 才调用有界 runner、持久化结果并覆盖报告中的运行结果。报告敏感词测试至少检查 `Authorization`、`Cookie`、`Bearer`、`MINIMAX_API_KEY` 和测试 secret 均不存在。

- [ ] **Step 6: 验证 Task 5**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/test_source_health_wave.py tests/test_probes.py tests/test_cli.py -q
D:\codex_project_work\news_codex\.venv\Scripts\ruff.exe check src/newsradar/sources src/newsradar/cli.py tests/test_source_health_wave.py
```

Expected: 全部 PASS。

- [ ] **Step 7: 提交 Task 5**

```powershell
git add src/newsradar/sources/health_wave.py src/newsradar/sources/probes/runner.py src/newsradar/cli.py tests/test_source_health_wave.py tests/test_probes.py tests/test_cli.py
git commit -m "feat: run bounded source health waves"
```

---

### Task 6: 真实本地运行迁移与 v1.2 验收

**Files:**
- Create: `tests/acceptance/test_runtime_closure_v1_2.py`
- Create: `reports/runtime-closure-v1-2.md`
- Create: `reports/source-health-v1-2.md`
- Modify: `README.md`
- Modify: `reports/project-capability-acceptance-2026-07-15.md` only if its status section must reference the new report; do not overwrite unrelated user edits in root checkout.

**Interfaces:**
- Consumes all Tasks 1-5 commands and Web pages。
- Produces real PostgreSQL, MiniMax, Worker, catalog and browser acceptance evidence。

- [ ] **Step 1: 写 PostgreSQL 总体验收测试**

测试使用真实 `DATABASE_URL`；未配置 PostgreSQL 时 skip。覆盖：迁移 head、idle heartbeat、current/archived 查询、历史引用保留、MiniMax usage 安全字段和能力总览 drift=0。

- [ ] **Step 2: 运行验收测试并确认在迁移前失败**

Run: `D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest tests/acceptance/test_runtime_closure_v1_2.py -q`

Expected: 若数据库尚未迁移，FAIL 于缺少归档字段；不能以 skip 代替已配置本地 PostgreSQL 的失败。

- [ ] **Step 3: 安全迁移本地 MiniMax 配置**

执行 PowerShell 仅做本地文件更新：从 `.worktrees/raw-item-ingestion/.env` 读取 `MINIMAX_API_KEY` 值，写入根目录 `.env`；同时写入中国区 Base URL、M2.7 deep 和 M2.7-highspeed fast。命令输出只允许布尔状态：

```text
MINIMAX_KEY_CONFIGURED=True
MINIMAX_REGION=china
```

禁止输出值。不得修改旧工作树 `.env`。

- [ ] **Step 4: 应用迁移、同步并执行目录对账**

Run:

```powershell
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\newsradar.exe providers sync --root providers
.venv\Scripts\newsradar.exe sources sync --root sources
.venv\Scripts\newsradar.exe sources reconcile --root sources
.venv\Scripts\newsradar.exe sources reconcile --root sources --apply
```

Expected: 归档 `legacy-source`、`universe-youtube-1`；无 queued/running 阻塞；再次运行计划时 archive=0、restore=0。

- [ ] **Step 5: 执行 MiniMax 真实检查**

Run:

```powershell
.venv\Scripts\newsradar.exe minimax check
.venv\Scripts\newsradar.exe minimax check --live
```

Expected: 配置检查为中国区；模型可见；结构化调用 success；数据库新增一条安全 usage。若失败，保留安全错误码并按系统调试，不切换到未支持 M3。

- [ ] **Step 6: 执行来源健康波次**

Run:

```powershell
.venv\Scripts\newsradar.exe sources health-wave --root sources --output reports/source-health-v1-2.md
.venv\Scripts\newsradar.exe sources health-wave --root sources --execute --concurrency 8 --output reports/source-health-v1-2.md
```

Expected: 计划先列出候选；执行后每个候选有结果；单源失败不终止批次；报告不包含凭据或响应正文。

- [ ] **Step 7: 用统一入口替换当前 Web-only 进程**

确认 8766 监听进程命令行属于当前项目后停止；使用隐藏窗口仅用于本次 Codex 验收启动：

```powershell
Start-Process .venv\Scripts\newsradar.exe `
  -ArgumentList @('serve','--host','127.0.0.1','--port','8766','--worker-id','newsradar-local') `
  -WorkingDirectory 'D:\codex_project_work\news_codex' `
  -WindowStyle Hidden
```

不得停止不属于本项目的进程。

- [ ] **Step 8: 浏览器验收**

依次检查：

- `/sources`：current=187、archived=2、目录漂移为 0、MiniMax 已配置；
- `/system`：数据库 current、Worker 在线空闲、MiniMax 最近成功；
- `/targets?catalog_state=archived`：仅有两个历史来源且无抓取动作；
- `/probes`：健康波次结果可见；
- `/events`：固定 Operation 快照仍可访问。

不得通过浏览器触发额外全量抓取。

- [ ] **Step 9: 生成中文运行验收报告**

`reports/runtime-closure-v1-2.md` 必须包含：提交、迁移、配置布尔值、MiniMax 安全结果、Worker 状态、目录对账、健康波次分布、网页验收和剩余问题。不得包含 Key、代理值、请求或响应正文。

- [ ] **Step 10: 全量验证**

Run:

```powershell
D:\codex_project_work\news_codex\.venv\Scripts\python.exe -m pytest -q
D:\codex_project_work\news_codex\.venv\Scripts\ruff.exe check .
git diff --check
rg -n "sk-|Bearer |MINIMAX_API_KEY=.*[^=]" reports docs src tests -g '!*.example'
```

Expected: pytest 0 failures；Ruff 0 errors；diff check 0 errors；敏感值扫描 0 个真实密钥匹配。测试夹具中的固定字符串必须是明确假值且不进入报告。

- [ ] **Step 11: 提交 Task 6**

```powershell
git add README.md tests/acceptance/test_runtime_closure_v1_2.py reports/runtime-closure-v1-2.md reports/source-health-v1-2.md
git commit -m "docs: accept runtime closure v1.2"
```

---

## 最终审查清单

- [ ] 对照设计文档逐条确认 MiniMax、Worker、归档、健康波次和 Web 要求均有实现或测试证据。
- [ ] 确认没有实现定时任务、推荐、摘要、推送、实体抽取或非官方社交抓取。
- [ ] 确认所有生产代码均有先失败后通过的测试记录。
- [ ] 确认工作树只包含 v1.2 范围文件，没有带入根目录用户报告改动。
- [ ] 确认真实 `.env`、`.local/postgres` 和旧工作树未进入 Git。
- [ ] 请求代码审查并修复 P0/P1 问题。
- [ ] 验证分支可安全快进合并，合并后重新运行全量测试。
