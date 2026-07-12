# RawItem Ingestion v1.1 Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重做 RawItem v1、也不进入摘要/推荐阶段的前提下，补齐统一任务入口、Worker 联动、凭据、网页运维动作、超时健康、数据库恢复和真实验收，使本地系统可稳定操作、可诊断、可恢复。

**Architecture:** Web 与 CLI 都只通过统一的 `OperationCommandService` 创建和控制持久化任务；`Worker` 是唯一执行网络抓取的进程，`newsradar serve` 只负责监督 Web 与 Worker 两个子进程。抓取继续复用现有 `IngestionService` 和 fetcher，新增的限制、凭据与健康状态均在边界层集中实现并写入现有审计对象。

**Tech Stack:** Python 3.12、Typer、FastAPI/Jinja2、SQLAlchemy 2、PostgreSQL、HTTPX、Pydantic 2、Alembic、pytest、Ruff。

## Global Constraints

- 仅在 `feature/raw-item-v1-1-closure` 工作树实施，不修改 `main`。
- YAML 仍是来源真相，PostgreSQL 只保存运行状态、版本和审计历史；程序不得自动改写 YAML。
- 不使用 Docker、Cookie、登录态网页抓取、验证码破解、代理绕过或高风险非官方接口。
- MiniMax 不接入 v1.1 的抓取、启用、合规或运维决策；现有适配器保持可选和未接线状态。
- 不实现事件聚类、新闻摘要、推荐、日报、通知或后台调度。
- Web 写操作只能从 loopback、同源请求和一次性 token 发起；错误中不得泄露凭据。
- HTTP 默认 connect 10 秒、read 30 秒、单请求 45 秒；单来源 2 分钟、单任务 30 分钟。
- PostgreSQL lock timeout 为 5 秒；Worker lease 为 60 秒、每 15 秒续租。
- 默认只抓 1 页，单次最大 10 页；单一来源失败不得阻断其他来源或 Worker 后续任务。
- X、Facebook 等受限来源保持目录可见但不回退网页抓取；GDELT 默认降级且不进入常规抓取。
- 每个任务遵循测试先行；每个里程碑完成一次集中汇报，内部小步骤不打断用户。

---

## File Map

- Create `src/newsradar/operations/commands.py`: Web/CLI 共用的入队、等待、取消、重试命令层。
- Create `src/newsradar/runtime.py`: `serve` 双进程监督和信号转发。
- Create `src/newsradar/operations/deadlines.py`: 单来源/单任务 deadline 的计算与检查。
- Create `src/newsradar/ingestion/fetchers/retry_after.py`: RFC 兼容的 `Retry-After` 解析。
- Modify `src/newsradar/cli.py`: 删除 CLI 直抓路径，接入统一操作命令、默认常驻 Worker 和真正的 `serve`。
- Modify `src/newsradar/settings.py`: 统一数据库、MiniMax、GitHub、Reddit、YouTube 凭据与运行限制。
- Modify `src/newsradar/ingestion/fetchers/credentials.py`: 从 `Settings` 读取 `SecretStr`，不再直接读取 `os.environ`。
- Modify `src/newsradar/sources/schema.py`: `auth_envs` 列表为规范形式，并兼容旧 `auth_env` 标量。
- Modify `src/newsradar/sources/repository.py`, `src/newsradar/db/models.py`: 同步多凭据需求和来源失败状态。
- Modify `src/newsradar/operations/repository.py`, `worker.py`, `fetch_runtime.py`: 任务 deadline、重试、取消和事件审计。
- Modify `src/newsradar/ingestion/service.py`, `repository.py`, `fetchers/base.py`: 来源超时、失败计数、Retry-After 和有界去重。
- Modify `src/newsradar/web/app.py`, `operation_queries.py`, `item_queries.py`: 取消、重试、重复候选裁决及页面状态。
- Modify `src/newsradar/web/templates/operation_detail.html`, `duplicates.html`, `base.html`, `system.html`: 中文操作说明和表单。
- Modify `src/newsradar/local_postgres.py`: 初始化失败回滚与显式 `db repair`。
- Create `migrations/versions/20260712_0006_raw_item_v1_1_closure.py`: 失败状态、多凭据和去重查询索引。
- Modify `sources/conditional/reddit-*.yaml`, one `sources/universe/universe-youtube-*.yaml`, `sources/aggregators/gdelt-ai.yaml`: 正式认证要求与 GDELT 降级。
- Modify `.env.example`, `README.md`: 凭据、运行模式、写操作、恢复和边界的真实说明。
- Create `tests/operations/test_commands.py`, `tests/test_runtime.py`, `tests/operations/test_deadlines.py`, `tests/ingestion/fetchers/test_retry_after.py`.
- Modify existing CLI、Worker、Web、ingestion、schema、PostgreSQL、migration 和 acceptance tests.

---

### Task 1: 统一 Web/CLI 的持久化任务命令层

**Files:**
- Create: `src/newsradar/operations/commands.py`
- Modify: `src/newsradar/cli.py`
- Modify: `src/newsradar/web/app.py`
- Test: `tests/operations/test_commands.py`
- Test: `tests/test_cli.py`
- Test: `tests/web/test_ingestion_pages.py`

**Interfaces:**
- Consumes: `OperationRepository.enqueue()`, `request_cancel()`, `OperationStatus.terminal()`。
- Produces: `OperationCommandService.enqueue_fetch() -> int`, `retry() -> int`, `cancel() -> bool`, `wait_for_terminal() -> OperationRunRecord`。

- [ ] **Step 1: 写统一命令层失败测试**

```python
def test_enqueue_fetch_records_complete_scope(session):
    service = OperationCommandService(session)
    operation_id = service.enqueue_fetch(
        source_id="github-openai-python",
        provider=None,
        dry_run=False,
        max_items=5,
        one_off=False,
        trigger="cli",
    )
    record = session.get(OperationRunRecord, operation_id)
    assert record.status == "queued"
    assert record.requested_scope == {
        "source_id": "github-openai-python",
        "provider": None,
        "dry_run": False,
        "max_items": 5,
        "one_off": False,
    }

def test_retry_creates_new_auditable_operation(session):
    original = OperationCommandService(session).enqueue_fetch(
        source_id="github-openai-python", trigger="web"
    )
    retry_id = OperationCommandService(session).retry(original, trigger="web")
    retry = session.get(OperationRunRecord, retry_id)
    assert retry.id != original
    assert retry.requested_scope["retry_of_operation_id"] == original
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `uv run pytest tests/operations/test_commands.py -q`

Expected: FAIL，错误包含 `No module named 'newsradar.operations.commands'`。

- [ ] **Step 3: 实现统一命令服务**

```python
class OperationCommandService:
    def __init__(self, session: Session, *, clock: Callable[[], datetime] | None = None):
        self.session = session
        self.clock = clock or (lambda: datetime.now(UTC))

    def enqueue_fetch(
        self,
        *,
        source_id: str,
        provider: str | None = None,
        dry_run: bool = False,
        max_items: int | None = None,
        one_off: bool = False,
        trigger: str,
    ) -> int:
        scope = {
            "source_id": source_id,
            "provider": provider,
            "dry_run": dry_run,
            "max_items": max_items,
            "one_off": one_off,
        }
        record = OperationRepository(self.session).enqueue(
            OperationType.FETCH, scope, trigger=trigger
        )
        self.session.commit()
        return record.id

    def retry(self, operation_id: int, *, trigger: str) -> int:
        original = self.session.get(OperationRunRecord, operation_id)
        if original is None or original.status not in {
            item.value for item in OperationStatus.terminal()
        }:
            raise ValueError("operation is not retryable")
        scope = dict(original.requested_scope)
        scope["retry_of_operation_id"] = operation_id
        record = OperationRepository(self.session).enqueue(
            OperationType(original.operation_type), scope, trigger=trigger
        )
        self.session.commit()
        return record.id

    def cancel(self, operation_id: int) -> bool:
        result = OperationRepository(self.session).request_cancel(operation_id)
        self.session.commit()
        return result

    def wait_for_terminal(self, operation_id: int, *, timeout_seconds: float = 1800) -> OperationRunRecord:
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            self.session.expire_all()
            record = self.session.get(OperationRunRecord, operation_id)
            if record is None:
                raise LookupError(operation_id)
            if record.status in {item.value for item in OperationStatus.terminal()}:
                return record
            sleep(0.25)
        raise TimeoutError(f"operation {operation_id} did not finish within {timeout_seconds}s")
```

- [ ] **Step 4: 将 CLI fetch 改成只入队并默认等待**

给 `fetch_sources()` 增加 `--wait/--no-wait`，默认 `wait=True`。删除 `_fetch_sources()` 和 CLI 内直接构造 `IngestionService` 的路径；来源校验和 one-off 确认保留，随后调用：

```python
operation_ids = [
    OperationCommandService(session).enqueue_fetch(
        source_id=source.id,
        provider=provider,
        dry_run=dry_run,
        max_items=max_items,
        one_off=one_off,
        trigger="cli",
    )
    for source in selected
]
typer.echo(f"Queued operations: {', '.join(map(str, operation_ids))}")
if wait:
    terminals = [
        OperationCommandService(session).wait_for_terminal(operation_id)
        for operation_id in operation_ids
    ]
    for terminal in terminals:
        typer.echo(f"Operation {terminal.id}: {terminal.status}")
    if any(item.status not in {"succeeded", "partial"} for item in terminals):
        raise typer.Exit(1)
```

同时让 Web `/operations/fetch` 调用同一个服务；测试通过 monkeypatch `IngestionService.fetch_source` 为抛错函数，证明请求线程没有网络抓取。

- [ ] **Step 5: 运行统一入口测试**

Run: `uv run pytest tests/operations/test_commands.py tests/test_cli.py tests/web/test_ingestion_pages.py -q`

Expected: PASS；CLI `--no-wait` 立即返回，默认等待终态；Web/CLI 创建的 scope 字段一致且 trigger 分别为 `web`/`cli`。

- [ ] **Step 6: 提交里程碑 A1**

```powershell
git add src/newsradar/operations/commands.py src/newsradar/cli.py src/newsradar/web/app.py tests/operations/test_commands.py tests/test_cli.py tests/web/test_ingestion_pages.py
git commit -m "feat: unify durable fetch commands"
```

---

### Task 2: 实现 `serve` 监督器和明确的 Worker 运行模式

**Files:**
- Create: `src/newsradar/runtime.py`
- Modify: `src/newsradar/cli.py`
- Test: `tests/test_runtime.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: 当前 Python 解释器与 `newsradar web`、`newsradar worker --forever` 命令。
- Produces: `RuntimeSupervisor.run() -> int`；`serve` 返回任一异常子进程的非零退出码并停止兄弟进程。

- [ ] **Step 1: 写进程生命周期失败测试**

```python
def test_supervisor_stops_sibling_when_worker_fails(fake_process_factory):
    web = fake_process_factory(exit_code=None)
    worker = fake_process_factory(exit_code=7)
    result = RuntimeSupervisor(process_factory=fake_process_factory.sequence(web, worker)).run()
    assert result == 7
    assert web.terminate_called
    assert web.wait_called

def test_supervisor_forwards_interrupt_to_both_children(fake_process_factory):
    supervisor = RuntimeSupervisor(process_factory=fake_process_factory)
    supervisor.start()
    supervisor.stop(signal.SIGINT)
    assert all(process.signal_received == signal.SIGINT for process in supervisor.children)
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/test_runtime.py -q`

Expected: FAIL，错误包含 `No module named 'newsradar.runtime'`。

- [ ] **Step 3: 实现无自动重启的双进程监督器**

```python
@dataclass(frozen=True)
class ChildSpec:
    name: str
    args: tuple[str, ...]

class RuntimeSupervisor:
    def __init__(self, process_factory: Callable[..., Popen] = subprocess.Popen):
        self.process_factory = process_factory
        self.children: list[Popen] = []

    def start(self) -> None:
        specs = (
            ChildSpec(
                "web",
                (sys.executable, "-c", "from newsradar.cli import app; app()", "web"),
            ),
            ChildSpec(
                "worker",
                (
                    sys.executable,
                    "-c",
                    "from newsradar.cli import app; app()",
                    "worker",
                    "--forever",
                ),
            ),
        )
        self.children = [self.process_factory(spec.args) for spec in specs]

    def stop(self, signum: int = signal.SIGTERM) -> None:
        for child in self.children:
            if child.poll() is None:
                child.send_signal(signum)
        for child in self.children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=5)

    def run(self) -> int:
        self.start()
        try:
            while True:
                for child in self.children:
                    code = child.poll()
                    if code is not None:
                        self.stop()
                        return code if code != 0 else 1
                time.sleep(0.2)
        except KeyboardInterrupt:
            self.stop(signal.SIGINT)
            return 0
```

- [ ] **Step 4: 接入 CLI 并修正默认值**

`worker` 的 `--once/--forever` 默认改为 `False`，保留显式 `--once`；`serve` 调用 `RuntimeSupervisor().run()`，非零时 `raise typer.Exit(code)`。`web` 与 `worker` 单独命令继续可用。

- [ ] **Step 5: 验证终止、异常退出和帮助信息**

Run: `uv run pytest tests/test_runtime.py tests/test_cli.py -q`

Expected: PASS；帮助文本明确 `serve` 同时启动 Web/Worker，`worker` 默认 forever，异常子进程不会被自动重启。

- [ ] **Step 6: 提交里程碑 A2**

```powershell
git add src/newsradar/runtime.py src/newsradar/cli.py tests/test_runtime.py tests/test_cli.py
git commit -m "feat: supervise web and worker runtime"
```

---

### Task 3: 统一凭据设置并正式登记 Reddit/YouTube 接入

**Files:**
- Modify: `src/newsradar/settings.py`
- Modify: `src/newsradar/ingestion/fetchers/credentials.py`
- Modify: `src/newsradar/ingestion/fetchers/base.py`
- Modify: `src/newsradar/ingestion/eligibility.py`
- Modify: `src/newsradar/sources/schema.py`
- Modify: `src/newsradar/sources/repository.py`
- Modify: `src/newsradar/sources/probes/base.py`
- Modify: `src/newsradar/sources/probes/protocols.py`
- Modify: `src/newsradar/db/models.py`
- Modify: `src/newsradar/web/viewmodels.py`
- Modify: `src/newsradar/web/queries.py`
- Modify: `src/newsradar/web/templates/target_detail.html`
- Modify: `.env.example`
- Modify: `sources/conditional/reddit-artificial.yaml`
- Modify: `sources/conditional/reddit-machinelearning.yaml`
- Modify: `sources/conditional/reddit-localllama.yaml`
- Modify: `sources/universe/universe-youtube-1.yaml`
- Create: `migrations/versions/20260712_0006_raw_item_v1_1_closure.py`
- Test: `tests/test_source_schema.py`
- Test: `tests/ingestion/test_eligibility.py`
- Test: `tests/ingestion/fetchers/test_reddit.py`
- Test: `tests/ingestion/fetchers/test_youtube.py`
- Test: `tests/test_probes.py`
- Test: `tests/test_protocol_probes.py`
- Test: `tests/web/test_queries.py`
- Test: `tests/web/test_routes.py`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Consumes: `.env` 与 `Settings`。
- Produces: `SettingsCredentials.require(name) -> str`；`AccessMethod.auth_envs: tuple[str, ...]`，旧 `auth_env` 输入自动转换。

- [ ] **Step 1: 写多凭据兼容和脱敏失败测试**

```python
def test_access_method_accepts_legacy_auth_env():
    method = AccessMethod.model_validate({
        "kind": "rest_api", "url": "https://api.github.com/repos/openai/openai-python/releases",
        "priority": 1, "auth_env": "GITHUB_TOKEN",
    })
    assert method.auth_envs == ("GITHUB_TOKEN",)

def test_settings_credentials_unwraps_only_requested_secret():
    settings = Settings(
        reddit_client_id="client", reddit_client_secret="secret", youtube_api_key="video"
    )
    provider = SettingsCredentials(settings)
    assert provider.require("REDDIT_CLIENT_SECRET") == "secret"
    assert "secret" not in repr(settings)
```

- [ ] **Step 2: 运行并确认当前标量字段/环境读取导致失败**

Run: `uv run pytest tests/test_source_schema.py tests/ingestion/fetchers/test_reddit.py tests/ingestion/fetchers/test_youtube.py -q`

Expected: FAIL，`auth_envs` 与 `SettingsCredentials` 尚不存在。

- [ ] **Step 3: 实现 Settings 和凭据提供器**

```python
class Settings(BaseSettings):
    # existing fields stay unchanged
    github_token: SecretStr | None = None
    reddit_client_id: SecretStr | None = None
    reddit_client_secret: SecretStr | None = None
    youtube_api_key: SecretStr | None = None

class SettingsCredentials:
    _fields = {
        "GITHUB_TOKEN": "github_token",
        "REDDIT_CLIENT_ID": "reddit_client_id",
        "REDDIT_CLIENT_SECRET": "reddit_client_secret",
        "YOUTUBE_API_KEY": "youtube_api_key",
    }

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def require(self, name: str) -> str:
        field = self._fields.get(name)
        value = getattr(self.settings, field, None) if field else None
        if value is None:
            raise KeyError(name)
        return value.get_secret_value()
```

`FetcherFactory` 默认使用 `SettingsCredentials()`；probe 与 eligibility 也通过 Settings 提供的已配置凭据名称判断，禁止再直接索引 `os.environ`。Web viewmodel 将 `auth_env` 替换为 `auth_envs: tuple[str, ...]`，目标详情只展示变量名称和“已配置/未配置”，绝不展示值。

- [ ] **Step 4: 规范化 `auth_envs` 并保持旧 YAML 可读**

在 `AccessMethod` 使用 `validation_alias=AliasChoices("auth_envs", "auth_env")` 接收字符串或列表，验证后存为非空、去重、全大写 tuple；序列化和数据库同步只写 `auth_envs`。迁移给 `source_access_methods` 新增非空 JSON `auth_envs`，用旧 `auth_env` 回填后保留旧列一个版本以便回滚。

- [ ] **Step 5: 修正审核目录**

三个 Reddit YAML 的首选方法设置：

```yaml
auth_envs:
  - REDDIT_CLIENT_ID
  - REDDIT_CLIENT_SECRET
```

YouTube 目标改为官方 Data API、`coverage_mode: direct`、默认禁用 ingestion：

```yaml
access_methods:
  - kind: rest_api
    url: https://www.googleapis.com/youtube/v3/search
    priority: 1
    auth_envs:
      - YOUTUBE_API_KEY
    params:
      part: snippet
      channelId: UCXZCJLdBC09xxGZ6gcdrc6A
      order: date
      type: video
      maxResults: "5"
ingestion:
  enabled: false
```

身份 URL 和 channelId 必须与现有人工审核目标一致；如果 `universe-youtube-1` 的身份不能证明该 channelId，则将该文件改名/命名为已审核官方频道，而不是伪造映射。

- [ ] **Step 6: 运行 Schema、fetcher、迁移和泄露测试**

Run: `uv run pytest tests/test_source_schema.py tests/test_source_repository.py tests/test_probes.py tests/test_protocol_probes.py tests/ingestion/test_eligibility.py tests/ingestion/fetchers/test_reddit.py tests/ingestion/fetchers/test_youtube.py tests/web/test_queries.py tests/web/test_routes.py tests/test_migrations.py -q`

Expected: PASS；无凭据返回明确 blocked；日志、异常、模型 repr 和 YAML 快照都不出现真实 secret。

- [ ] **Step 7: 提交里程碑 B**

```powershell
git add .env.example src/newsradar/settings.py src/newsradar/ingestion src/newsradar/sources src/newsradar/db/models.py src/newsradar/web/viewmodels.py src/newsradar/web/queries.py src/newsradar/web/templates/target_detail.html migrations/versions/20260712_0006_raw_item_v1_1_closure.py sources/conditional sources/universe/universe-youtube-1.yaml tests
git commit -m "feat: centralize audited source credentials"
```

---

### Task 4: 补齐 Web 取消、重试和重复候选裁决

**Files:**
- Modify: `src/newsradar/web/security.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/item_queries.py`
- Modify: `src/newsradar/web/operation_queries.py`
- Modify: `src/newsradar/web/templates/operation_detail.html`
- Modify: `src/newsradar/web/templates/duplicates.html`
- Modify: `src/newsradar/web/templates/base.html`
- Test: `tests/web/test_security.py`
- Test: `tests/web/test_ingestion_pages.py`
- Test: `tests/web/test_operation_queries.py`
- Test: `tests/web/test_item_queries.py`

**Interfaces:**
- Consumes: `OperationCommandService.cancel/retry` 与 `DuplicateCandidateRecord.status`。
- Produces: POST `/operations/{id}/cancel`, `/operations/{id}/retry`, `/duplicates/{id}/confirm`, `/duplicates/{id}/dismiss`。

- [ ] **Step 1: 写安全写操作和多标签 token 失败测试**

```python
def test_two_open_pages_keep_independent_tokens(client):
    first = extract_token(client.get("/operations").text)
    second = extract_token(client.get("/duplicates").text)
    assert post_cancel(client, operation_id=1, token=first).status_code == 303
    assert post_duplicate(client, duplicate_id=1, action="dismiss", token=second).status_code == 303

def test_retry_creates_new_operation_linked_in_scope(client, session):
    response = post_retry(client, finished_operation_id=1)
    assert response.status_code == 303
    created = session.scalar(select(OperationRunRecord).order_by(OperationRunRecord.id.desc()))
    assert created.requested_scope["retry_of_operation_id"] == 1
```

- [ ] **Step 2: 运行并确认路由缺失/token 覆盖失败**

Run: `uv run pytest tests/web/test_security.py tests/web/test_ingestion_pages.py -q`

Expected: FAIL；路由返回 404，且首次页面 token 被第二次 GET 覆盖。

- [ ] **Step 3: 修复一次性 token 集合**

```python
def issue_action_token(request: Request) -> str:
    token = token_urlsafe(32)
    tokens = list(request.session.get("tokens", []))[-15:]
    tokens.append(token)
    request.session["tokens"] = tokens
    return token
```

消费逻辑仍删除单个 token；最多保留 16 个，防止 session 无限增长。

- [ ] **Step 4: 实现四个 POST 路由**

每条路由先 `await require_safe_action(request)`，再验证对象存在和状态转换：queued/running 才能取消；terminal 才能重试；pending duplicate 才能 confirm/dismiss。重复候选更新为：

```python
def review_duplicate(self, duplicate_id: int, status: Literal["confirmed", "dismissed"]):
    record = self.session.get(DuplicateCandidateRecord, duplicate_id, with_for_update=True)
    if record is None or record.status != "pending":
        return False
    record.status = status
    record.reviewed_at = datetime.now(UTC)
    self.session.commit()
    return True
```

裁决只改变候选状态，不合并、不删除 RawItem。

- [ ] **Step 5: 更新中文页面与可用动作**

任务详情只在可取消状态展示“请求取消”，只在终态展示“重新入队”；重复页为 pending 行展示“确认重复/排除重复”。每个表单携带独立 token，并说明操作影响。

- [ ] **Step 6: 运行 Web 全套测试**

Run: `uv run pytest tests/web -q`

Expected: PASS；非 loopback、跨域、token 重用、非法状态均拒绝且数据库无副作用。

- [ ] **Step 7: 提交里程碑 C**

```powershell
git add src/newsradar/web tests/web
git commit -m "feat: add safe ingestion controls to web"
```

---

### Task 5: 落实 deadline、Retry-After、来源失败健康和有界去重

**Files:**
- Create: `src/newsradar/operations/deadlines.py`
- Create: `src/newsradar/ingestion/fetchers/retry_after.py`
- Modify: `src/newsradar/settings.py`
- Modify: `src/newsradar/db/session.py`
- Modify: `src/newsradar/db/models.py`
- Modify: `src/newsradar/operations/repository.py`
- Modify: `src/newsradar/operations/worker.py`
- Modify: `src/newsradar/operations/fetch_runtime.py`
- Modify: `src/newsradar/ingestion/fetchers/base.py`
- Modify: `src/newsradar/ingestion/service.py`
- Modify: `src/newsradar/ingestion/repository.py`
- Modify: `migrations/versions/20260712_0006_raw_item_v1_1_closure.py`
- Test: `tests/operations/test_deadlines.py`
- Test: `tests/operations/test_worker.py`
- Test: `tests/operations/test_fetch_runtime.py`
- Test: `tests/ingestion/fetchers/test_retry_after.py`
- Test: `tests/ingestion/test_service.py`
- Test: `tests/ingestion/test_repository.py`
- Test: `tests/acceptance/test_nonblocking_web.py`

**Interfaces:**
- Consumes: operation scope、`FetchResult.retry_after_seconds`、`SourceFetchStateRecord`。
- Produces: `OperationDeadline`, `parse_retry_after(value, now) -> float | None`、持久化失败连续次数。

- [ ] **Step 1: 写 deadline 和 Retry-After 失败测试**

```python
def test_http_date_retry_after_is_parsed_and_bounded():
    now = datetime(2026, 7, 12, tzinfo=UTC)
    assert parse_retry_after("Sun, 12 Jul 2026 00:02:00 GMT", now=now) == 120.0
    assert parse_retry_after("invalid", now=now) is None

def test_operation_deadline_rejects_expired_scope():
    deadline = OperationDeadline.from_scope(
        {"deadline_at": "2026-07-12T00:00:00+00:00"},
        now=lambda: datetime(2026, 7, 12, 0, 0, 1, tzinfo=UTC),
    )
    with pytest.raises(OperationTimedOut):
        deadline.check("before_source")
```

- [ ] **Step 2: 写失败健康与有界候选测试**

```python
async def test_failed_fetch_increments_source_failure_state(service, state):
    await service.fetch_source(source, approved_only=True)
    service.session.refresh(state)
    assert state.consecutive_failures == 1
    assert state.last_failure_at is not None
    assert state.last_error_code == "upstream_timeout"

def test_title_duplicate_query_is_cross_source_and_time_bounded(repository, inserted):
    statement = repository.last_duplicate_statement
    sql = str(statement)
    assert "source_id !=" in sql
    assert "published_at" in sql
```

- [ ] **Step 3: 运行并确认失败**

Run: `uv run pytest tests/operations/test_deadlines.py tests/ingestion/fetchers/test_retry_after.py tests/ingestion/test_service.py tests/ingestion/test_repository.py -q`

Expected: FAIL；deadline/解析器和失败字段尚不存在，标题查询仍扫描全部跨源 RawItem。

- [ ] **Step 4: 实现集中限制与数据库超时**

Settings 增加精确默认值：

```python
http_connect_timeout_seconds: float = 10
http_read_timeout_seconds: float = 30
http_request_timeout_seconds: float = 45
source_timeout_seconds: float = 120
operation_timeout_seconds: float = 1800
db_lock_timeout_seconds: float = 5
worker_lease_seconds: float = 60
worker_heartbeat_seconds: float = 15
default_pages_per_fetch: int = 1
max_pages_per_fetch: int = 10
```

PostgreSQL engine connect hook 执行 `SET lock_timeout = '5s'`；非 PostgreSQL 不执行。HTTPX timeout 从 Settings 构造，不在 fetcher 各自复制。

- [ ] **Step 5: 实现任务/来源 deadline 与取消边界**

入队时将 UTC `deadline_at` 写入 scope。Worker 在 lease 后、每个 source 前后、每页前后和每个持久化 item 前检查取消及 deadline。来源抓取使用 `asyncio.timeout(source_timeout_seconds)`；超时生成 `error_category=transport`、`error_code=source_timeout`，任务总超时生成 `operation_timeout`，都保留 Attempt/Event。

- [ ] **Step 6: 实现标准 Retry-After**

```python
def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        current = now or datetime.now(UTC)
        return max(0.0, (parsed.astimezone(UTC) - current).total_seconds())
```

HTTP retry sleep 最大 30 秒，持久化任务 retry hint 最大 300 秒；二者均不超过剩余 deadline。

- [ ] **Step 7: 持久化来源失败状态**

迁移给 `source_fetch_states` 增加 nullable `last_failure_at`、`last_error_code`。`_finish_run()` 在有 method_id 时创建/锁定 state，`consecutive_failures += 1` 并写错误；`_commit_success()` 重置为 0 并清空最后错误。blocked eligibility 不伪造网络失败。

- [ ] **Step 8: 将标题去重限制在合理候选集**

标题候选必须跨来源，且优先使用 `published_at`；双方有发布时间时限制在 ±7 天，缺少发布时间时只查最近 30 天写入的最多 500 条。迁移新增：

```python
op.create_index(
    "ix_raw_items_source_published_at",
    "raw_items",
    ["source_id", sa.text("published_at DESC")],
)
op.create_index(
    "ix_raw_items_title_fingerprint_published_at",
    "raw_items",
    ["title_fingerprint", sa.text("published_at DESC")],
)
```

Canonical URL hash 仍保持精确优先，不改变候选阈值 0.9。

- [ ] **Step 9: 运行可靠性与性能测试**

Run: `uv run pytest tests/operations tests/ingestion tests/acceptance/test_nonblocking_web.py -q`

Expected: PASS；超时不会卡住 Worker，取消在边界生效，lease 每 15 秒续租，Retry-After 两种格式正确，失败/成功状态转换正确，去重不再全表 Python 扫描。

- [ ] **Step 10: 提交里程碑 D**

```powershell
git add src/newsradar/settings.py src/newsradar/db src/newsradar/operations src/newsradar/ingestion migrations/versions/20260712_0006_raw_item_v1_1_closure.py tests/operations tests/ingestion tests/acceptance/test_nonblocking_web.py
git commit -m "feat: bound ingestion runtime and health state"
```

---

### Task 6: 数据库初始化回滚、显式修复和 GDELT 降级

**Files:**
- Modify: `src/newsradar/local_postgres.py`
- Modify: `src/newsradar/cli.py`
- Modify: `sources/aggregators/gdelt-ai.yaml`
- Test: `tests/test_local_postgres.py`
- Test: `tests/test_cli.py`
- Test: `tests/ingestion/test_open_source_matrix.py`

**Interfaces:**
- Consumes: `.local/postgres/data`、`.local/postgres/postgres.log`、`.env`。
- Produces: `LocalPostgresManager.repair() -> str`，只修复可判定的部分初始化状态且不删除数据/日志。

- [ ] **Step 1: 写初始化失败回滚与修复失败测试**

```python
def test_init_failure_stops_started_cluster_and_preserves_logs(manager):
    manager.runner.fail_on("createdb.exe")
    with pytest.raises(LocalPostgresError):
        manager.initialize(password="fixed")
    assert manager.runner.called("pg_ctl.exe", "stop")
    assert manager.paths.log_file.exists()
    assert not manager.has_project_database_url()

def test_repair_restores_missing_env_for_valid_cluster(manager):
    manager.paths.data_dir.joinpath("PG_VERSION").write_text("17")
    manager.runner.database_exists = True
    message = manager.repair(password="fixed")
    assert "DATABASE_URL" in manager.paths.env_file.read_text()
    assert "repaired" in message.lower()
```

- [ ] **Step 2: 运行并确认缺少 repair**

Run: `uv run pytest tests/test_local_postgres.py tests/test_cli.py -q`

Expected: FAIL；`repair` 不存在，createdb 失败后进程可能仍运行。

- [ ] **Step 3: 实现保守恢复状态机**

`initialize()` 记录本次是否启动 cluster；任何 configure/start/createdb/write-env 异常都尝试停止本次启动的进程，删除临时口令文件，但保留 data 和 postgres.log。`repair()` 只执行以下确定性动作：

- cluster 有效且目标数据库存在、`.env` 缺 URL：要求 `--password` 后重写 URL；
- cluster 有效且数据库不存在：启动 cluster、创建数据库、写 URL；
- `.env` 有本项目 URL 但无有效 PG_VERSION：报错并指导备份后人工处理，不自动删除；
- 端口被其他进程占用：停止并报告，不覆盖。

- [ ] **Step 4: 增加 CLI `db repair`**

```python
@db_app.command("repair")
def repair_database(
    password: Annotated[str | None, typer.Option(prompt=True, hide_input=True)] = None,
) -> None:
    try:
        typer.echo(build_local_postgres_manager().repair(password=password))
    except LocalPostgresError as exc:
        typer.echo(f"Database error: {exc}", err=True)
        raise typer.Exit(1) from None
```

测试确认密码不出现在 stdout/stderr。

- [ ] **Step 5: 将 GDELT 改为降级且默认不抓**

```yaml
status: degraded
ingestion:
  enabled: false
```

保留 `availability: ready` 和内容探测能力；常规 fetch 选择排除它，显式 `gdelt-ai --one-off` 仍可在风险确认后探测/抓取。

- [ ] **Step 6: 运行恢复与来源矩阵测试**

Run: `uv run pytest tests/test_local_postgres.py tests/test_cli.py tests/ingestion/test_open_source_matrix.py -q`

Expected: PASS；任何路径不递归删除 `.local/postgres`，GDELT 不在常规启用集合中。

- [ ] **Step 7: 提交里程碑 E**

```powershell
git add src/newsradar/local_postgres.py src/newsradar/cli.py sources/aggregators/gdelt-ai.yaml tests/test_local_postgres.py tests/test_cli.py tests/ingestion/test_open_source_matrix.py
git commit -m "fix: make local runtime recovery explicit"
```

---

### Task 7: 中文 UI/README 事实收口与端到端验收

**Files:**
- Modify: `README.md`
- Modify: `src/newsradar/web/templates/base.html`
- Modify: `src/newsradar/web/templates/dashboard.html`
- Modify: `src/newsradar/web/templates/system.html`
- Modify: `src/newsradar/web/templates/operations.html`
- Modify: `src/newsradar/web/templates/operation_detail.html`
- Modify: `src/newsradar/web/templates/duplicates.html`
- Modify: `tests/web/test_routes.py`
- Modify: `tests/web/test_system.py`
- Create: `tests/acceptance/test_cli_web_worker_flow.py`
- Create: `reports/raw-item-v1-1-verification.md`

**Interfaces:**
- Consumes: Tasks 1–6 的最终运行模式和状态。
- Produces: 与实际行为一致的中文操作指引、端到端证据和最终验收报告。

- [ ] **Step 1: 写页面事实与端到端失败测试**

```python
def test_navigation_distinguishes_read_pages_and_safe_actions(client):
    page = client.get("/")
    assert "浏览页面不会发起网络抓取" in page.text
    assert "抓取、取消、重试和重复候选裁决会写入数据库" in page.text

def test_cli_web_worker_end_to_end(postgres, source_root):
    operation_id = enqueue_from_web("github-openai-python")
    run_worker_once(source_root)
    detail = get_operation_page(operation_id)
    assert "succeeded" in detail.text or "partial" in detail.text
    assert fetch_run_for(operation_id) is not None
```

- [ ] **Step 2: 运行并确认文案/端到端断言失败**

Run: `uv run pytest tests/web/test_routes.py tests/web/test_system.py tests/acceptance/test_cli_web_worker_flow.py -q`

Expected: FAIL；旧 README/页面仍称整体只读，端到端 helper 尚未落地。

- [ ] **Step 3: 更新中文流程说明**

首页和导航明确区分：

- “目录、来源、探测、RawItem 浏览”为只读查看；
- “抓取入队、取消、重试、重复候选裁决、诊断包”为本地数据库写操作；
- `serve` 是推荐的日常启动方式；`web` 单独启动时 Worker 离线，任务只会排队；
- 凭据从 `.env` 读取，页面只显示“已配置/未配置”，不显示值；
- GDELT 是降级发现源，默认不抓；
- MiniMax 适配器存在但未接入 RawItem v1.1。

- [ ] **Step 4: 更新 README 命令和故障恢复**

README 的主路径改为：

```powershell
uv run newsradar db start
uv run alembic upgrade head
uv run newsradar providers sync --root providers
uv run newsradar sources sync --root sources
uv run newsradar serve
```

并记录 `worker --once`、`worker --forever`、`fetch --no-wait`、`db repair`、Reddit/YouTube/GitHub 凭据用途与最小权限风险；禁止复制真实 key 到报告、YAML、日志或 Git。

- [ ] **Step 5: 在真实本地 PostgreSQL 跑迁移与目录同步**

Run:

```powershell
uv run newsradar db start
uv run alembic upgrade head
uv run newsradar providers validate --root providers
uv run newsradar sources validate --root sources
uv run newsradar providers sync --root providers
uv run newsradar sources sync --root sources
```

Expected: 所有命令 exit 0，migration head 为 `20260712_0006`，目录同步幂等，第二次 sync 的 created/updated 为 0。

- [ ] **Step 6: 执行真实 Web → Worker 流程和三轮开放来源验收**

每轮只选择已审核、免费、direct、ingestion enabled 的开放来源；每轮记录 operation id、attempt、fetch run、结果、延迟、items 和错误码。三轮之间不修改 YAML 或凭据；失败来源不得阻断其他来源。GDELT 不在常规集合。

Run:

```powershell
uv run newsradar worker --forever --root sources
uv run pytest tests/acceptance/test_cli_web_worker_flow.py -q
uv run newsradar fetch hackernews-top --root sources
uv run newsradar fetch arxiv-cs-ai --root sources
uv run newsradar fetch openai-news --root sources
```

Expected: Web 入队后 Worker 消费；三轮中每个任务都有 Attempt/Event/FetchRun；至少 15 个稳定开放来源的既有 Milestone D 证据不回退，任何网络波动在报告中如实标为 degraded/failed，而不是篡改测试。

- [ ] **Step 7: 生成最终验证报告**

`reports/raw-item-v1-1-verification.md` 必须写入：commit、migration head、测试数/跳过数、Ruff、真实 PostgreSQL DSN 的脱敏形式、Web/CLI/Worker 操作 ID、三轮来源结果、凭据缺口、GDELT 状态、未接入 MiniMax 声明、已知限制和复现命令。不得包含 feed body、API 响应、数据库密码或 token。

- [ ] **Step 8: 提交里程碑 F**

```powershell
git add README.md src/newsradar/web/templates tests/web tests/acceptance/test_cli_web_worker_flow.py reports/raw-item-v1-1-verification.md
git commit -m "docs: close raw item v1.1 operations"
```

---

### Task 8: 全量门禁、独立审查与合并准备

**Files:**
- Modify: no production file is planned in this task; a review finding must first name one of the exact production and test paths listed in Tasks 1–7, then add a regression test beside that component before editing it.
- Test: `tests/` (entire tree).

**Interfaces:**
- Consumes: Tasks 1–7 的提交。
- Produces: 零跳过的本地 PostgreSQL 测试证据、干净分支和可合并审查结论。

- [ ] **Step 1: 执行迁移往返与全量质量门禁**

Run:

```powershell
uv run alembic current
uv run alembic downgrade 20260712_0005
uv run alembic upgrade head
uv run pytest -q
uv run ruff check .
git diff --check
```

Expected: migration 往返成功；pytest 0 failed、0 skipped；Ruff 和 diff check exit 0。

- [ ] **Step 2: 执行秘密扫描和诊断脱敏检查**

Run:

```powershell
git grep -n -E "sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|client_secret[=:][^ ]+" -- . ":(exclude).env.example"
uv run newsradar diagnostics create --destination .local/diagnostics
```

Expected: git grep 无真实凭据匹配；诊断 ZIP 中只包含环境变量名/配置状态，不含值和原始响应体。

- [ ] **Step 3: 浏览器验收两种运行模式**

模式一仅运行 `newsradar web`：入队后页面明确显示“等待 Worker”，请求不阻塞。模式二运行 `newsradar serve`：同一操作被 Worker 消费，状态、Attempt、Event、FetchRun 和 RawItem 可下钻；取消/重试/重复裁决均可用且中文说明正确。

- [ ] **Step 4: 使用 5.6 Sol + 高推理做最终代码审查**

审查范围固定为设计文档、计划、`git diff main...HEAD`、迁移、运行报告与完整门禁输出。审查重点：是否重复实现 v1、Web 是否执行网络、凭据是否泄露、deadline 是否真正终止等待、lease/cancel 是否竞态安全、数据库恢复是否破坏数据、GDELT 是否被常规抓取、文档是否夸大能力。

- [ ] **Step 5: 修复审查发现并重跑完整门禁**

每个实质问题先增加最小回归测试，再修代码。重跑 Step 1–3；若无实质问题，不制造无关重构。

- [ ] **Step 6: 提交审查修复并确认分支状态**

```powershell
git add -A
git commit -m "fix: address raw item v1.1 final review"
git status --short --branch
git log --oneline --decorate main..HEAD
```

Expected: 工作树 clean；分支只包含 v1.1 设计、计划和实现提交；不自动合并、不强推、不删除任何工作树或本地 `.env/.local`。

---

## Self-Review Mapping

- 统一入口与不重复直抓：Task 1。
- Web + Worker 推荐启动和异常生命周期：Task 2。
- Settings/SecretStr、Reddit 双凭据、YouTube 官方 API：Task 3。
- Web 取消/重试/重复裁决、多标签 token：Task 4。
- HTTP/来源/任务/数据库限制、lease、Retry-After、失败健康、去重性能：Task 5。
- PostgreSQL 部分初始化恢复、GDELT 降级：Task 6。
- 中文事实展示、操作流程、真实网络与三轮证据：Task 7。
- 零跳过、秘密扫描、浏览器双模式、Sol 高推理最终审查：Task 8。
- 后续事件聚类、摘要、推荐、通知和调度均未进入任何任务。
