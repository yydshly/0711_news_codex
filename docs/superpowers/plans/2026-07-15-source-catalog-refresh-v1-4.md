# 来源目录全量刷新 v1.4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复用现有来源注册表、探测器和持久化 Worker，为 187 个当前来源建立一次能力感知、可恢复、可审计的全量刷新批次，并在中文网页中展示准确的内容、能力和目录结论。

**Architecture:** 新增 `source_catalog_refresh` 持久化操作和冻结成员表。纯规则规划器把来源路由到 `content`、`capability` 或 `catalog`；Worker 只对允许自动访问的来源执行网络探测，其余来源保存能力或目录结论。所有结果关联到批次，网页只入队和读取，不直接执行网络请求。

**Tech Stack:** Python 3.12、SQLAlchemy 2、Alembic、Pydantic 2、Typer、HTTPX、FastAPI、Jinja2、PostgreSQL、pytest、Ruff。

## Global Constraints

- 不使用 Docker，不新增后台调度器。
- YAML 仍是人工审核的来源真相，程序不得自动修改 YAML。
- 旧 Provider、Source、探测历史和操作历史必须无损兼容。
- `ready` 来源才能进入内容通道；受限来源不能因本机存在凭据而绕过 availability 审核。
- `requires_credentials`、`requires_approval`、`requires_payment`、`unavailable` 只进入能力通道。
- `manual_only`、`catalog_only`、人工批准 HTML 和无自动方法来源只进入目录通道。
- 不新增 Cookie、登录态、验证码、代理绕过、媒体下载或 HTML 自动回退。
- Google News、GDELT、社交和社区来源继续只作发现或热度信号。
- MiniMax 不参与路由、合规、启用或最终状态；v1.4 不新增强制模型调用。
- API Key、Authorization、Cookie、数据库密码、请求头和完整响应正文不得进入数据库结果、日志、HTML 或报告。
- 单个来源失败不得中断其他成员；所有网络工作必须由 Worker 执行。
- 默认全局并发 8，同 Provider 并发 2；同一来源三轮严格串行。
- 所有新增文案、设计、计划、报告和主要网页说明使用中文。

---

## File Structure

### 新建文件

- `src/newsradar/sources/catalog_refresh.py`：纯规则路由、冻结快照、目录校验和摘要类型。
- `src/newsradar/sources/catalog_refresh_repository.py`：批次成员的短事务读写、恢复和汇总。
- `src/newsradar/sources/catalog_refresh_runtime.py`：Worker Handler、内容/能力/目录三通道执行和并发边界。
- `src/newsradar/sources/catalog_refresh_reporting.py`：中文 Markdown 报告。
- `src/newsradar/web/source_wave_queries.py`：批次列表、详情、筛选和视图模型。
- `src/newsradar/web/templates/source_waves.html`：全量盘点列表与创建入口。
- `src/newsradar/web/templates/source_wave_detail.html`：批次详情与成员筛选。
- `migrations/versions/20260715_0017_source_catalog_refresh.py`：冻结成员表和探测关联迁移。
- `tests/test_catalog_refresh.py`：纯规划与目录校验测试。
- `tests/test_catalog_refresh_repository.py`：冻结成员、恢复和汇总测试。
- `tests/operations/test_catalog_refresh_runtime.py`：三通道、并发、错误和恢复测试。
- `tests/web/test_source_wave_queries.py`：查询层测试。
- `tests/web/test_source_wave_pages.py`：路由、表单和中文页面测试。
- `tests/acceptance/test_source_catalog_refresh_v1_4.py`：PostgreSQL、Web、Worker 端到端验收。
- `reports/source-catalog-refresh-v1-4.md`：真实运行验收报告，仅在最终任务生成。

### 修改文件

- `src/newsradar/db/models.py`：新增成员模型及两个可空操作关联。
- `src/newsradar/operations/schema.py`：新增 `SOURCE_CATALOG_REFRESH`。
- `src/newsradar/operations/commands.py`：新增入队与受控重试命令。
- `src/newsradar/sources/repository.py`：保存内容探测时可关联操作。
- `src/newsradar/providers/repository.py`：保存能力探测时可关联操作。
- `src/newsradar/cli.py`：注册 Worker Handler 和四个 CLI 命令。
- `src/newsradar/web/app.py`：全量盘点 GET/POST 路由。
- `src/newsradar/web/templates/base.html`：增加“全量盘点”导航。
- `src/newsradar/web/static/styles.css`：仅增加新页面需要且现有组件无法覆盖的少量样式。
- `tests/test_migrations.py`：迁移升级、历史保留和约束测试。
- `tests/operations/test_commands.py`：入队、防重和重试测试。
- `tests/test_cli.py`：计划、入队、状态和报告命令测试。
- `tests/operations/test_router.py`：Worker 路由注册回归测试。

---

### Task 1：确定性规划器与目录校验

**Files:**
- Create: `src/newsradar/sources/catalog_refresh.py`
- Create: `tests/test_catalog_refresh.py`

**Interfaces:**
- Consumes: `SourceDefinition`、`ProviderDefinition`、现有最新探测 `HealthProbeState`、已配置环境变量名称集合。
- Produces: `CatalogRefreshLane`、`CatalogMemberState`、`CatalogResultCode`、`CatalogRefreshMemberSnapshot`、`CatalogRefreshPlan`、`CatalogValidationResult`；规划函数接收来源、Provider、最新状态和已配置凭据名称；目录校验函数接收一个来源和对应 Provider。

- [ ] **Step 1: 写三通道路由失败测试**

测试模块复用 `tests.test_source_schema.valid_source` 和 `tests.test_provider_schema.valid_provider`，新增 `catalog_source`、`catalog_provider` 两个局部工厂，只改写用例明确传入的 availability、coverage mode、access kind、人工批准和凭据字段。

测试必须覆盖：

```python
def test_planner_routes_each_current_source_to_one_lane():
    plan = build_catalog_refresh_plan(
        sources=[
            source("open", availability="ready", coverage_mode="direct", kind="rss"),
            source("keyed", availability="requires_credentials", kind="rest_api"),
            source("paid", availability="requires_payment", kind="rest_api"),
            source("manual", availability="manual_only", kind="html", manual=True),
            source("catalog", availability="ready", coverage_mode="catalog_only"),
        ],
        providers=providers_for("open", "keyed", "paid", "manual", "catalog"),
        latest={},
        configured_credentials={"EXAMPLE_KEY"},
    )
    assert [(m.source_id, m.lane.value) for m in plan.members] == [
        ("catalog", "catalog"),
        ("keyed", "capability"),
        ("manual", "catalog"),
        ("open", "content"),
        ("paid", "capability"),
    ]
```

还要断言归档来源不进入计划、缺少凭据的 `ready` 来源进入能力通道、人工批准 HTML 不进入内容通道。

- [ ] **Step 2: 写陈旧结果与稳定摘要失败测试**

```python
def test_planner_marks_latest_probe_with_old_access_kind_as_stale():
    plan = build_catalog_refresh_plan(
        sources=[source("media", availability="ready", kind="rss")],
        providers=providers_for("media"),
        latest={"media": HealthProbeState(outcome="blocked", access_kind="html")},
        configured_credentials=set(),
    )
    assert plan.members[0].initial_result_code == CatalogResultCode.STALE_RESULT
    assert plan.members[0].access_kind == "rss"
```

断言 `catalog_digest` 与输入顺序无关，定义哈希、availability、coverage mode、access kind 和 Provider 都进入冻结快照。

- [ ] **Step 3: 写目录完整性失败测试**

```python
def test_catalog_validation_requires_identity_risk_and_chinese_conclusion():
    result = validate_catalog_entry(incomplete_source(), provider("manual"))
    assert result.code == CatalogResultCode.CATALOG_INCOMPLETE
    assert result.missing == (
        "official_identity_url",
        "risk_evidence",
        "reviewed_at",
        "readable_conclusion",
    )
```

完整来源返回 `catalog_verified`；函数不得发起 HTTP 请求。

- [ ] **Step 4: 运行定向测试确认 RED**

Run: `uv run pytest tests/test_catalog_refresh.py -q`

Expected: FAIL，模块或接口尚不存在。

- [ ] **Step 5: 实现最小纯规则类型与函数**

核心接口固定为：

```python
class CatalogRefreshLane(StrEnum):
    CONTENT = "content"
    CAPABILITY = "capability"
    CATALOG = "catalog"


class CatalogMemberState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CatalogResultCode(StrEnum):
    STALE_RESULT = "stale_result"
    NO_CONTENT = "no_content"
    INCOMPLETE_FIELDS = "incomplete_fields"
    MISSING_CREDENTIALS = "missing_credentials"
    REQUIRES_APPROVAL = "requires_approval"
    REQUIRES_PAYMENT = "requires_payment"
    MANUAL_ONLY = "manual_only"
    CATALOG_VERIFIED = "catalog_verified"
    CATALOG_INCOMPLETE = "catalog_incomplete"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    RATE_LIMITED = "rate_limited"
    UNSUPPORTED_ACCESS_KIND = "unsupported_access_kind"
    CANCELLED = "cancelled"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class CatalogRefreshMemberSnapshot:
    source_id: str
    provider_id: str
    definition_hash: str
    availability: str
    coverage_mode: str
    access_kind: str
    lane: CatalogRefreshLane
    initial_result_code: CatalogResultCode | None = None


@dataclass(frozen=True, slots=True)
class CatalogRefreshPlan:
    members: tuple[CatalogRefreshMemberSnapshot, ...]
    catalog_digest: str
    lane_counts: dict[str, int]

    @classmethod
    def from_members(
        cls, members: tuple[CatalogRefreshMemberSnapshot, ...]
    ) -> "CatalogRefreshPlan":
        ordered = tuple(sorted(members, key=lambda item: item.source_id))
        payload = [asdict(member) for member in ordered]
        digest = sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        counts = Counter(member.lane.value for member in ordered)
        return cls(ordered, digest, dict(sorted(counts.items())))


@dataclass(frozen=True, slots=True)
class CatalogValidationResult:
    code: CatalogResultCode
    missing: tuple[str, ...]
    conclusion: str
```

规划器按 `source_id` 排序后计算 SHA-256，禁止读取环境变量本身，只消费 `configured_credentials: set[str]`。

- [ ] **Step 6: 运行测试确认 GREEN**

Run: `uv run pytest tests/test_catalog_refresh.py -q`

Expected: PASS。

- [ ] **Step 7: 提交 Task 1**

```bash
git add src/newsradar/sources/catalog_refresh.py tests/test_catalog_refresh.py
git commit -m "feat: plan capability-aware catalog refresh"
```

---

### Task 2：迁移、冻结成员模型与短事务仓储

**Files:**
- Create: `migrations/versions/20260715_0017_source_catalog_refresh.py`
- Modify: `src/newsradar/db/models.py`
- Create: `src/newsradar/sources/catalog_refresh_repository.py`
- Create: `tests/test_catalog_refresh_repository.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Consumes: Task 1 的 `CatalogRefreshPlan` 和 `CatalogRefreshMemberSnapshot`。
- Produces: `SourceCatalogRefreshMemberRecord`；仓储提供创建冻结成员、读取未完成成员、标记开始、标记结束和生成汇总五类操作。

- [ ] **Step 1: 写迁移失败测试**

测试从 `20260715_0016` 升级到 `20260715_0017`，插入旧探测历史后断言：

```python
assert inspector.has_table("source_catalog_refresh_members")
assert "operation_run_id" in columns("source_probe_runs")
assert "operation_run_id" in columns("source_provider_probe_runs")
assert old_source_probe["operation_run_id"] is None
assert old_provider_probe["operation_run_id"] is None
```

SQLite 和 PostgreSQL 都必须支持升级；重复 `alembic upgrade head` 不重复创建对象。

- [ ] **Step 2: 写仓储冻结、恢复和汇总失败测试**

```python
def test_repository_freezes_members_and_resumes_only_unfinished(session, plan):
    operation = OperationRepository(session).enqueue(
        OperationType.SOURCE_CATALOG_REFRESH, {}, trigger="test"
    )
    repository = CatalogRefreshRepository(session)
    repository.create_members(operation.id, plan)
    repository.finish_member(
        operation.id,
        "open",
        state=CatalogMemberState.SUCCEEDED,
        result_code=None,
        conclusion="三轮内容探测成功",
        content_probe_run_ids=[10, 11, 12],
    )
    session.commit()
    assert [m.source_id for m in repository.unfinished_members(operation.id)] != ["open"]
    assert repository.summary(operation.id)["content_succeeded"] == 1
```

断言同一 `(operation_run_id, source_id)` 违反唯一约束；成员快照不随 SourceDefinitionRecord 更新而变化。

- [ ] **Step 3: 运行测试确认 RED**

Run: `uv run pytest tests/test_migrations.py tests/test_catalog_refresh_repository.py -q`

Expected: FAIL，迁移、模型和仓储尚不存在。

- [ ] **Step 4: 实现迁移与模型**

迁移固定：

```python
revision = "20260715_0017"
down_revision = "20260715_0016"
```

成员表至少包含：

```python
class SourceCatalogRefreshMemberRecord(Base):
    __tablename__ = "source_catalog_refresh_members"
    __table_args__ = (
        UniqueConstraint("operation_run_id", "source_id"),
        Index("ix_catalog_refresh_members_state", "operation_run_id", "state"),
    )

    id: Mapped[int]
    operation_run_id: Mapped[int]
    source_id: Mapped[str]
    provider_id: Mapped[str]
    definition_hash: Mapped[str]
    availability_snapshot: Mapped[str]
    coverage_mode_snapshot: Mapped[str]
    access_kind_snapshot: Mapped[str]
    lane: Mapped[str]
    state: Mapped[str]
    result_code: Mapped[str | None]
    conclusion: Mapped[str | None]
    content_probe_run_ids: Mapped[list[int]]
    provider_probe_run_id: Mapped[int | None]
    attempt_count: Mapped[int]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
```

`source_probe_runs.operation_run_id` 和 `source_provider_probe_runs.operation_run_id` 为可空外键并建立索引。

- [ ] **Step 5: 实现短事务仓储**

仓储方法不执行网络：

```python
class CatalogRefreshRepository:
    def create_members(self, operation_run_id: int, plan: CatalogRefreshPlan) -> None:
        records = [
            SourceCatalogRefreshMemberRecord(
                operation_run_id=operation_run_id,
                source_id=member.source_id,
                provider_id=member.provider_id,
                definition_hash=member.definition_hash,
                availability_snapshot=member.availability,
                coverage_mode_snapshot=member.coverage_mode,
                access_kind_snapshot=member.access_kind,
                lane=member.lane.value,
                state=CatalogMemberState.PENDING.value,
                result_code=(
                    member.initial_result_code.value if member.initial_result_code else None
                ),
                content_probe_run_ids=[],
                attempt_count=0,
            )
            for member in plan.members
        ]
        self.session.add_all(records)
        self.session.flush()

    def unfinished_members(
        self, operation_run_id: int
    ) -> tuple[SourceCatalogRefreshMemberRecord, ...]:
        resumable = ("pending", "running")
        return tuple(
            self.session.scalars(
                select(SourceCatalogRefreshMemberRecord)
                .where(
                    SourceCatalogRefreshMemberRecord.operation_run_id == operation_run_id,
                    SourceCatalogRefreshMemberRecord.state.in_(resumable),
                )
                .order_by(SourceCatalogRefreshMemberRecord.source_id)
            )
        )

    def start_member(self, operation_run_id: int, source_id: str) -> None:
        member = self._member(operation_run_id, source_id)
        member.state = CatalogMemberState.RUNNING.value
        member.attempt_count += 1
        member.started_at = member.started_at or utcnow()
        self.session.flush()
    def finish_member(
        self,
        operation_run_id: int,
        source_id: str,
        *,
        state: CatalogMemberState,
        result_code: CatalogResultCode | None,
        conclusion: str,
        content_probe_run_ids: list[int] | None = None,
        provider_probe_run_id: int | None = None,
    ) -> None:
        member = self._member(operation_run_id, source_id)
        member.state = state.value
        member.result_code = result_code.value if result_code else None
        member.conclusion = conclusion
        member.content_probe_run_ids = list(content_probe_run_ids or [])
        member.provider_probe_run_id = provider_probe_run_id
        member.finished_at = utcnow()
        self.session.flush()

    def summary(self, operation_run_id: int) -> dict[str, int]:
        members = self.session.scalars(
            select(SourceCatalogRefreshMemberRecord).where(
                SourceCatalogRefreshMemberRecord.operation_run_id == operation_run_id
            )
        )
        counts = Counter(f"{member.lane}_{member.state}" for member in members)
        return dict(sorted(counts.items()))

    def retryable_plan(self, operation_run_id: int) -> CatalogRefreshPlan:
        retryable_codes = {
            "timeout",
            "connection_error",
            "rate_limited",
            "deadline_exceeded",
        }
        rows = self.session.scalars(
            select(SourceCatalogRefreshMemberRecord)
            .where(
                SourceCatalogRefreshMemberRecord.operation_run_id == operation_run_id,
                SourceCatalogRefreshMemberRecord.result_code.in_(retryable_codes),
            )
            .order_by(SourceCatalogRefreshMemberRecord.source_id)
        )
        snapshots = tuple(snapshot_from_record(row) for row in rows)
        return CatalogRefreshPlan.from_members(snapshots)

    def _member(
        self, operation_run_id: int, source_id: str
    ) -> SourceCatalogRefreshMemberRecord:
        record = self.session.scalar(
            select(SourceCatalogRefreshMemberRecord).where(
                SourceCatalogRefreshMemberRecord.operation_run_id == operation_run_id,
                SourceCatalogRefreshMemberRecord.source_id == source_id,
            )
        )
        if record is None:
            raise LookupError((operation_run_id, source_id))
        return record
```

同时在 Task 1 为 `CatalogRefreshPlan` 实现类方法 `from_members`，在本模块实现记录到快照的 `snapshot_from_record`；两者都按 `source_id` 排序并重新计算 digest，不读取可变 SourceDefinitionRecord。

`unfinished_members` 只返回 `pending` 和失效的 `running`，不返回任何终态成员。允许重试的失败成员由 `retryable_plan` 明确复制到新操作，不能在原操作内无限循环。

- [ ] **Step 6: 运行测试确认 GREEN**

Run: `uv run pytest tests/test_migrations.py tests/test_catalog_refresh_repository.py -q`

Expected: PASS。

- [ ] **Step 7: 提交 Task 2**

```bash
git add migrations/versions/20260715_0017_source_catalog_refresh.py src/newsradar/db/models.py src/newsradar/sources/catalog_refresh_repository.py tests/test_migrations.py tests/test_catalog_refresh_repository.py
git commit -m "feat: persist frozen catalog refresh members"
```

---

### Task 3：批次入队、防重、取消与受控重试

**Files:**
- Modify: `src/newsradar/operations/schema.py`
- Modify: `src/newsradar/operations/commands.py`
- Modify: `tests/operations/test_commands.py`
- Modify: `tests/operations/test_schema.py`

**Interfaces:**
- Consumes: Task 1 的 `CatalogRefreshPlan`，Task 2 的 `CatalogRefreshRepository`。
- Produces: `OperationType.SOURCE_CATALOG_REFRESH`、全量刷新入队命令和仅复制可重试成员的重试命令。

- [ ] **Step 1: 写入队和防重失败测试**

```python
def test_enqueue_catalog_refresh_creates_operation_and_members_atomically(session, plan):
    operation_id = OperationCommandService(session).enqueue_source_catalog_refresh(
        plan=plan,
        trigger="web",
        global_concurrency=8,
        provider_concurrency=2,
    )
    operation = session.get(OperationRunRecord, operation_id)
    assert operation.operation_type == "source_catalog_refresh"
    assert operation.requested_scope["catalog_digest"] == plan.catalog_digest
    assert operation.progress_total == len(plan.members)
    assert count_members(session, operation_id) == len(plan.members)
```

第二个活动批次必须抛出 `active_catalog_refresh_exists`，且不能留下半创建成员。

- [ ] **Step 2: 写重试范围失败测试**

重试只复制原批次中 `timeout`、`connection_error`、`rate_limited`、`deadline_exceeded` 的失败成员。`missing_credentials`、`requires_payment`、`manual_only`、`no_content`、成功成员和目录成员不得进入重试。

- [ ] **Step 3: 运行测试确认 RED**

Run: `uv run pytest tests/operations/test_commands.py tests/operations/test_schema.py -q`

Expected: FAIL，新操作类型和命令不存在。

- [ ] **Step 4: 实现操作类型与入队事务**

新增：

```python
class OperationType(StrEnum):
    # existing values remain unchanged
    SOURCE_CATALOG_REFRESH = "source_catalog_refresh"
```

命令签名固定为：

```python
def enqueue_source_catalog_refresh(
    self,
    *,
    plan: CatalogRefreshPlan,
    trigger: str,
    global_concurrency: int = 8,
    provider_concurrency: int = 2,
    retry_of_operation_id: int | None = None,
) -> int:
    if not 1 <= global_concurrency <= 16 or not 1 <= provider_concurrency <= 8:
        raise ValueError("invalid_catalog_refresh_concurrency")
    self._lock_catalog_refresh_enqueue()
    if self._active_catalog_refresh_id() is not None:
        raise ValueError("active_catalog_refresh_exists")
    operation = OperationRepository(self.session).enqueue(
        OperationType.SOURCE_CATALOG_REFRESH,
        self._catalog_refresh_scope(
            plan,
            global_concurrency,
            provider_concurrency,
            retry_of_operation_id,
        ),
        trigger=trigger,
    )
    CatalogRefreshRepository(self.session).create_members(operation.id, plan)
    operation.progress_total = len(plan.members)
    self.session.commit()
    return operation.id

def retry_source_catalog_refresh(self, operation_id: int, *, trigger: str) -> int:
    plan = CatalogRefreshRepository(self.session).retryable_plan(operation_id)
    if not plan.members:
        raise ValueError("catalog_refresh_retry_not_allowed")
    return self.enqueue_source_catalog_refresh(
        plan=plan,
        trigger=trigger,
        retry_of_operation_id=operation_id,
    )
```

同一 Task 必须实现以下三个私有辅助边界：

```python
def _active_catalog_refresh_id(self) -> int | None:
    return self.session.scalar(
        select(OperationRunRecord.id).where(
            OperationRunRecord.operation_type == "source_catalog_refresh",
            OperationRunRecord.status.in_(("queued", "running")),
        )
    )

def _lock_catalog_refresh_enqueue(self) -> None:
    if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('newsradar:catalog-refresh-enqueue'))")
        )

def _catalog_refresh_scope(
    self,
    plan: CatalogRefreshPlan,
    global_concurrency: int,
    provider_concurrency: int,
    retry_of_operation_id: int | None,
) -> dict:
    now = self._utcnow()
    return {
        "schema_version": 1,
        "catalog_digest": plan.catalog_digest,
        "catalog_count": len(plan.members),
        "requested_lanes": sorted(plan.lane_counts),
        "global_concurrency": global_concurrency,
        "provider_concurrency": provider_concurrency,
        "deadline_at": (
            now + timedelta(seconds=self._settings.operation_timeout_seconds)
        ).isoformat(),
        **(
            {"retry_of_operation_id": retry_of_operation_id}
            if retry_of_operation_id is not None
            else {}
        ),
    }
```

校验并发范围 1–16 和 1–8，PostgreSQL 使用事务 advisory lock 防止双击并发创建。`deadline_at` 使用现有 `operation_timeout_seconds`。

- [ ] **Step 5: 运行测试确认 GREEN**

Run: `uv run pytest tests/operations/test_commands.py tests/operations/test_schema.py -q`

Expected: PASS。

- [ ] **Step 6: 提交 Task 3**

```bash
git add src/newsradar/operations/schema.py src/newsradar/operations/commands.py tests/operations/test_commands.py tests/operations/test_schema.py
git commit -m "feat: enqueue catalog refresh operations"
```

---

### Task 4：内容通道与三轮探测

**Files:**
- Create: `src/newsradar/sources/catalog_refresh_runtime.py`
- Modify: `src/newsradar/sources/repository.py`
- Modify: `src/newsradar/providers/repository.py`
- Create: `tests/operations/test_catalog_refresh_runtime.py`

**Interfaces:**
- Consumes: Tasks 1–3 的成员、仓储、操作类型，现有 `ProbeFactory`、`ProbeRunner`、`OperationDeadline`。
- Produces: `CatalogRefreshHandler` 和内容成员执行方法，并让探测记录关联 `operation_run_id`。

- [ ] **Step 1: 写内容首轮与三轮失败测试**

测试模块提供 `refresh_member`、`recording_probe` 和 `recording_provider_probe` fixture；记录器只返回调用队列中预置的 `ProbeResult`/`ProviderProbeResult`，并记录开始结束时间和最大并发，不访问真实网络。

```python
def test_content_member_runs_three_serial_probes_only_after_first_success(
    db_session, refresh_member, recording_probe
):
    probe = RecordingProbe([success(), success(), success()])
    result = handler.run_content_member(member, probe, checkpoint)
    assert probe.maximum_concurrency == 1
    assert result.state == CatalogMemberState.SUCCEEDED
    assert len(result.content_probe_run_ids) == 3
```

首轮 `no_content`、`incomplete_fields`、401、429 或超时只保存一轮；429 的成员结果包含 `rate_limited`。

- [ ] **Step 2: 写操作关联和敏感字段失败测试**

```python
record = SourceRepository(session).save_probe_result(
    result,
    operation_run_id=operation.id,
)
assert record.operation_run_id == operation.id
assert "Authorization" not in record.response_headers
assert "Cookie" not in record.response_headers
```

Provider 仓储同步增加同名可空参数，但本 Task 只验证接口兼容，能力通道在 Task 5 使用。

另写定义漂移测试：成员冻结后修改对应 SourceDefinition 的 `definition_hash`，Handler 必须以 `stale_result` 完成该成员且网络调用次数为 0。

- [ ] **Step 3: 写并发边界失败测试**

至少 6 个来源、两个 Provider；断言全局最大并发不超过配置值、同 Provider 不超过 2、同来源三轮不并发。

- [ ] **Step 4: 运行测试确认 RED**

Run: `uv run pytest tests/operations/test_catalog_refresh_runtime.py -q`

Expected: FAIL，Handler 和操作关联尚不存在。

- [ ] **Step 5: 实现内容运行时**

核心结构：

```python
class CatalogRefreshHandler:
    def __init__(self, sources, providers, create_session, probe_factory=ProbeFactory):
        self._sources = {source.id: source for source in sources}
        self._providers = {provider.id: provider for provider in providers}
        self._create_session = create_session
        self._probe_factory = probe_factory

    @classmethod
    def production(cls, sources, providers, create_session):
        return cls(sources, providers, create_session)

    def __call__(
        self,
        lease: OperationLease,
        checkpoint: Callable[[str], None],
    ) -> OperationResult:
        return asyncio.run(self._run(lease, checkpoint))
```

每轮流程固定为：短事务 `start_member` → 关闭 session → `checkpoint` → HTTP 探测 → `checkpoint` → 新短事务保存探测和成员结果。不得跨网络请求保持 SQLAlchemy Session。

开始网络前比较当前 SourceDefinition 的 `definition_hash` 与成员冻结值；不一致时保存“批次创建后来源定义已变化”的中文结论和 `stale_result`，不得使用新配置执行旧批次。

错误映射使用纯函数：

```python
def result_code_for_probe(result: ProbeResult) -> CatalogResultCode | None:
    if result.error_code == "no_content":
        return CatalogResultCode.NO_CONTENT
    if result.error_code == "incomplete_fields":
        return CatalogResultCode.INCOMPLETE_FIELDS
    if result.http_status == 429:
        return CatalogResultCode.RATE_LIMITED
    # timeout/connection/unsupported mappings follow the design enum
```

不得降低 90% 完整率门槛。

- [ ] **Step 6: 运行内容通道测试确认 GREEN**

Run: `uv run pytest tests/operations/test_catalog_refresh_runtime.py -q`

Expected: PASS 当前内容通道用例。

- [ ] **Step 7: 提交 Task 4**

```bash
git add src/newsradar/sources/catalog_refresh_runtime.py src/newsradar/sources/repository.py src/newsradar/providers/repository.py tests/operations/test_catalog_refresh_runtime.py
git commit -m "feat: run bounded catalog content probes"
```

---

### Task 5：能力、目录通道与 Worker 恢复

**Files:**
- Modify: `src/newsradar/sources/catalog_refresh_runtime.py`
- Modify: `src/newsradar/cli.py`
- Modify: `tests/operations/test_catalog_refresh_runtime.py`
- Modify: `tests/operations/test_router.py`
- Modify: `tests/operations/test_worker.py`

**Interfaces:**
- Consumes: Task 4 的 `CatalogRefreshHandler`、现有 `ProviderProbe` 和 Task 1 的目录校验函数。
- Produces: 完整三通道 Handler，并注册到生产 Worker。

- [ ] **Step 1: 写能力去重和禁止内容请求失败测试**

在同一个测试模块增加 `run_refresh` 帮助函数：创建冻结 operation 与成员、调用 Handler、重新读取成员并返回 operation 和成员元组。`forbidden_source_probe` 与 `forbidden_http_client` 一旦被调用立即抛出 AssertionError。

```python
def test_capability_lane_probes_provider_once_and_never_calls_source_probe(
    db_session, capability_members, recording_provider_probe, forbidden_source_probe
):
    result = run_refresh(
        members=[capability_member("reddit-a", "reddit"), capability_member("reddit-b", "reddit")]
    )
    assert provider_probe.calls == ["reddit"]
    assert source_probe.calls == []
    assert all(member.provider_probe_run_id for member in result.members)
```

缺凭据、审批、付费和 unavailable 生成准确结果码；能力文档 200 仍不能变成内容成功。

- [ ] **Step 2: 写目录通道无网络失败测试**

```python
def test_catalog_lane_is_pure_validation_without_network(
    db_session, catalog_member, forbidden_http_client
):
    result = run_refresh(members=[catalog_member("manual")])
    assert http_client.requests == []
    assert result.members[0].result_code in {"catalog_verified", "catalog_incomplete"}
```

- [ ] **Step 3: 写取消、截止时间和租约恢复失败测试**

验证：

- `checkpoint` 在下一网络边界取消；
- deadline 到期后不开始新请求；
- Worker 重新领取同一 operation 时跳过已完成成员；
- 已完成成员的探测记录数量不增加；
- 单成员失败后其他成员继续；
- 运行故障使批次 `partial`，权限阻塞不使批次失败。

- [ ] **Step 4: 运行测试确认 RED**

Run: `uv run pytest tests/operations/test_catalog_refresh_runtime.py tests/operations/test_router.py tests/operations/test_worker.py -q`

Expected: FAIL，能力/目录通道和 Worker 注册尚不存在。

- [ ] **Step 5: 实现能力与目录执行**

能力通道按 `provider_id` 分组：先执行一次 ProviderProbe 并保存 `operation_run_id`，再把同一 `provider_probe_run_id` 写入所有对应成员。目录通道只调用 `validate_catalog_entry`。

受控重试规则：

```python
TRANSIENT_CODES = {
    CatalogResultCode.TIMEOUT,
    CatalogResultCode.CONNECTION_ERROR,
    CatalogResultCode.RATE_LIMITED,
    CatalogResultCode.DEADLINE_EXCEEDED,
}
```

每个网络成员内部最多一次瞬时重试；429 使用 `Retry-After`，等待时间超过操作剩余时间时直接记录 `rate_limited`。

- [ ] **Step 6: 注册生产 Worker Handler**

在 `run_worker()` 加载 Provider YAML，并注册：

```python
"source_catalog_refresh": CatalogRefreshHandler.production(
    sources,
    providers,
    create_session,
),
```

不得改变 fetch、remediation 或 event handler。

- [ ] **Step 7: 运行定向测试确认 GREEN**

Run: `uv run pytest tests/operations/test_catalog_refresh_runtime.py tests/operations/test_router.py tests/operations/test_worker.py -q`

Expected: PASS。

- [ ] **Step 8: 提交 Task 5**

```bash
git add src/newsradar/sources/catalog_refresh_runtime.py src/newsradar/cli.py tests/operations/test_catalog_refresh_runtime.py tests/operations/test_router.py tests/operations/test_worker.py
git commit -m "feat: complete catalog refresh worker lanes"
```

---

### Task 6：CLI 计划、入队、状态与中文报告

**Files:**
- Create: `src/newsradar/sources/catalog_refresh_reporting.py`
- Modify: `src/newsradar/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1 的规划器，Task 2 的仓储，Task 3 的命令服务。
- Produces: `refresh-plan`、`refresh-enqueue`、`refresh-status`、`refresh-report`。

- [ ] **Step 1: 写 CLI 只读计划失败测试**

```python
result = runner.invoke(app, ["sources", "refresh-plan", "--root", str(source_root)])
assert result.exit_code == 0
assert "内容通道" in result.stdout
assert "能力通道" in result.stdout
assert "目录通道" in result.stdout
assert operation_count(session) == 0
assert network_calls == []
```

- [ ] **Step 2: 写入队、状态和报告失败测试**

断言 `refresh-enqueue` 输出 operation id；`refresh-status` 输出进度与三通道计数；`refresh-report` 只读取指定 operation，并且报告不含 `API_KEY`、Authorization、Cookie 或配置值。

- [ ] **Step 3: 运行测试确认 RED**

Run: `uv run pytest tests/test_cli.py -q`

Expected: FAIL，新命令和报告器不存在。

- [ ] **Step 4: 实现报告器**

接口：

```python
def render_catalog_refresh_report(
    operation: OperationRunRecord,
    members: Sequence[SourceCatalogRefreshMemberRecord],
) -> str:
    summary = summarize_catalog_members(members)
    sections = render_catalog_sections(operation, summary, members)
    return "\n".join(sections).rstrip() + "\n"
```

同文件必须提供返回计数字典的 `summarize_catalog_members` 和返回文本行列表的 `render_catalog_sections`；前者仅按通道、状态和结果码计数，后者按设计第 9 节的固定顺序生成标题、摘要、内容证据、能力边界、目录结论、失败和安全声明。

报告固定包含：批次 ID、目录摘要、完成度、三通道数量、结果码数量、内容三轮证据、能力解锁条件、目录缺口、失败成员和边界声明。

- [ ] **Step 5: 实现四个 CLI 命令**

```text
newsradar sources refresh-plan
newsradar sources refresh-enqueue
newsradar sources refresh-status <operation-id>
newsradar sources refresh-report <operation-id> --output reports/source-catalog-refresh-v1-4.md
```

`refresh-enqueue` 必须先严格加载 Provider/Source YAML 并同步数据库，再创建冻结批次；不得在 CLI 进程中执行探测网络。

- [ ] **Step 6: 运行测试确认 GREEN**

Run: `uv run pytest tests/test_cli.py -q`

Expected: PASS。

- [ ] **Step 7: 提交 Task 6**

```bash
git add src/newsradar/sources/catalog_refresh_reporting.py src/newsradar/cli.py tests/test_cli.py
git commit -m "feat: expose catalog refresh cli reporting"
```

---

### Task 7：中文“全量盘点”网页

**Files:**
- Create: `src/newsradar/web/source_wave_queries.py`
- Create: `src/newsradar/web/templates/source_waves.html`
- Create: `src/newsradar/web/templates/source_wave_detail.html`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/base.html`
- Modify: `src/newsradar/web/static/styles.css`
- Create: `tests/web/test_source_wave_queries.py`
- Create: `tests/web/test_source_wave_pages.py`

**Interfaces:**
- Consumes: Task 2 的批次成员，Task 3 的命令服务和现有一次性写操作 token。
- Produces: `SourceWaveQueryService` 的批次列表与筛选详情查询，以及 `/source-waves` 路由。

- [ ] **Step 1: 写查询层失败测试**

```python
detail = SourceWaveQueryService(session).detail(
    operation_id,
    lane="capability",
    provider_id="reddit",
    state="blocked",
    result_code="missing_credentials",
    page=1,
    page_size=50,
)
assert detail.summary.content_success != detail.summary.capability_confirmed
assert all(row.lane == "capability" for row in detail.members)
```

断言不存在的批次返回 `None`，非 `source_catalog_refresh` 操作不能伪装成批次详情。

- [ ] **Step 2: 写网页 GET/POST 失败测试**

必须覆盖：

- 导航显示“全量盘点”；
- GET 不发起网络；
- POST 创建操作后 303 跳转到详情；
- 缺少一次性 token、非同源或非 loopback 写请求被拒绝；
- 活动批次时按钮禁用并显示原因；
- 取消和重试使用现有安全边界；
- 内容成功、能力已确认、目录已确认和运行失败使用不同中文标签。

- [ ] **Step 3: 运行测试确认 RED**

Run: `uv run pytest tests/web/test_source_wave_queries.py tests/web/test_source_wave_pages.py -q`

Expected: FAIL，查询、模板和路由不存在。

- [ ] **Step 4: 实现查询服务**

接口：

```python
class SourceWaveQueryService:
    def __init__(self, session: Session):
        self.session = session

    def list_waves(self, *, limit: int = 20) -> tuple[SourceWaveSummary, ...]:
        records = self.session.scalars(
            select(OperationRunRecord)
            .where(OperationRunRecord.operation_type == "source_catalog_refresh")
            .order_by(OperationRunRecord.created_at.desc(), OperationRunRecord.id.desc())
            .limit(limit)
        )
        return tuple(SourceWaveSummary.from_record(record) for record in records)
    def detail(
        self,
        operation_id: int,
        *,
        lane: str | None = None,
        provider_id: str | None = None,
        availability: str | None = None,
        coverage_mode: str | None = None,
        state: str | None = None,
        result_code: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> SourceWaveDetail | None:
        operation = self.session.get(OperationRunRecord, operation_id)
        if operation is None or operation.operation_type != "source_catalog_refresh":
            return None
        page_rows, total = self._filtered_members(
            operation_id,
            lane=lane,
            provider_id=provider_id,
            availability=availability,
            coverage_mode=coverage_mode,
            state=state,
            result_code=result_code,
            page=page,
            page_size=page_size,
        )
        return SourceWaveDetail.from_records(operation, page_rows, total)
```

`SourceWaveSummary.from_record` 只读取 operation 的冻结摘要；`SourceWaveDetail.from_records` 同时接收分页成员和总数，分别计算内容成功、能力确认、目录确认、降级、运行失败五个互斥计数。`_filtered_members` 必须用一个带过滤条件的总数查询和一个带 limit/offset 的页面查询完成，不在模板循环中访问数据库。

查询必须分页且不逐行 N+1 查询。

- [ ] **Step 5: 实现模板和安全路由**

新增：

```text
GET  /source-waves
POST /source-waves
GET  /source-waves/{operation_id}
POST /source-waves/{operation_id}/cancel
POST /source-waves/{operation_id}/retry
```

POST 只调用 `OperationCommandService`，不得实例化 HTTP 客户端或探测器。详情行链接到 `/targets/{source_id}`。

- [ ] **Step 6: 运行网页测试确认 GREEN**

Run: `uv run pytest tests/web/test_source_wave_queries.py tests/web/test_source_wave_pages.py tests/web/test_security.py -q`

Expected: PASS。

- [ ] **Step 7: 提交 Task 7**

```bash
git add src/newsradar/web/source_wave_queries.py src/newsradar/web/templates/source_waves.html src/newsradar/web/templates/source_wave_detail.html src/newsradar/web/app.py src/newsradar/web/templates/base.html src/newsradar/web/static/styles.css tests/web/test_source_wave_queries.py tests/web/test_source_wave_pages.py
git commit -m "feat: add chinese catalog refresh console"
```

---

### Task 8：真实全量验收、报告与合并前审查

**Files:**
- Create: `tests/acceptance/test_source_catalog_refresh_v1_4.py`
- Create: `reports/source-catalog-refresh-v1-4.md`
- Modify only if evidence reveals an actual defect: files from Tasks 1–7 and their matching tests.

**Interfaces:**
- Consumes: Tasks 1–7 的完整系统。
- Produces: PostgreSQL、Web、Worker、真实网络和安全门禁证据。

- [ ] **Step 1: 写 PostgreSQL 端到端验收测试**

测试在未配置真实 PostgreSQL 时跳过；配置后必须：

```python
operation_id = enqueue_refresh_through_web(client)
run_worker_until_terminal(operation_id)
detail = load_wave_detail(operation_id)
assert detail.catalog_count == 187
assert detail.completed_count == 187
assert detail.content_success + detail.capability_confirmed + detail.catalog_confirmed + detail.degraded + detail.failed == 187
```

另一个用例在处理中请求取消；第三个用例模拟租约过期后恢复，断言成功成员没有重复探测。

- [ ] **Step 2: 运行新增验收测试确认代码路径**

Run: `uv run pytest tests/acceptance/test_source_catalog_refresh_v1_4.py -q`

Expected: 无 PostgreSQL 时 SKIP；本机真实 PostgreSQL 时 PASS。

- [ ] **Step 3: 升级本机数据库并确认迁移头**

加载主目录 `.env` 但不打印任何值，然后运行：

```text
uv run alembic upgrade head
uv run alembic current
```

Expected: `20260715_0017 (head)`。

- [ ] **Step 4: 同步目录并检查计划**

Run:

```text
uv run newsradar providers sync
uv run newsradar sources sync
uv run newsradar sources refresh-plan
```

Expected: 当前来源总数 187；每个来源只进入一个通道；计划不执行网络。

- [ ] **Step 5: 从网页入队并由 Worker 消费**

启动分支审查服务和 Worker，使用网页“全量盘点”创建批次。验证网页请求立即返回，网络活动只出现在 Worker。

等待批次终态时持续检查：

- 心跳更新；
- 进度单调增加；
- 无成员长期停在 `running`；
- 单来源失败不阻塞后续成员；
- 取消与恢复各完成一次受控验收。

- [ ] **Step 6: 核对真实结果边界**

至少核对：

- 7 个此前未探测来源获得最新结论；
- AP、Reuters、Bloomberg、Financial Times、WSJ 使用 RSS 新结果，不再引用旧 HTML 结果；
- GDELT 若仍超时，准确显示 `timeout`，不顺带改写协议；
- DeepMind/Hugging Face 保留 `incomplete_fields`；
- Anthropic Bluesky/Qwen3 Releases 保留 `no_content`；
- SEC EDGAR 只显示能力/审批边界；
- No Priors 未确认频道 ID 时只显示目录结论；
- 受限平台没有内容探测记录。

- [ ] **Step 7: 生成中文验收报告**

Run:

```text
uv run newsradar sources refresh-report <operation-id> --output reports/source-catalog-refresh-v1-4.md
```

报告必须写入 commit、迁移头、operation id、目录摘要、三通道和结果码计数、三轮证据、取消/恢复证据、已知限制和复现命令。不得包含任何凭据值、请求头或完整正文。

- [ ] **Step 8: 运行完整门禁**

Run:

```text
uv run pytest -q --maxfail=1
uv run ruff check .
uv run newsradar providers validate
uv run newsradar sources validate
git diff --check
```

再对 `main..HEAD` 变更文件执行敏感信息扫描，关键字至少包含 `API_KEY`、`CLIENT_SECRET`、`Authorization`、`Cookie`、`Bearer` 和数据库密码模式。允许环境变量名称，不允许实际值。

Expected: 全部退出码为 0；只有已知第三方弃用 warning。

- [ ] **Step 9: 浏览器验收**

在临时端口打开：

- `/source-waves`；
- `/source-waves/{operation_id}`；
- 一个内容成功来源；
- 一个能力阻塞来源；
- 一个目录来源；
- 一个真实运行失败来源。

确认筛选、中文标签、进度、下钻、取消/重试入口和控制台日志；浏览器不得出现错误或警告。

- [ ] **Step 10: 提交验收证据并请求合并前审查**

```bash
git add tests/acceptance/test_source_catalog_refresh_v1_4.py reports/source-catalog-refresh-v1-4.md
git commit -m "docs: accept source catalog refresh v1.4"
```

审查范围固定为设计、计划、迁移、Tasks 1–7 的实现、验收测试和报告。Critical/Important 问题修复并重新跑完整门禁后，才允许合并到 `main`。

---

## 最终完成判定

- 187 个当前来源全部进入一个冻结批次且只有一个通道。
- 7 个原未探测来源获得最新、可解释结论。
- 当前首选访问方式与最新探测证据一致，旧方法结果不会冒充当前能力。
- 内容、能力和目录成功在数据库、报告和网页中严格区分。
- 首轮内容成功来源具有三轮串行证据；其他状态不会伪造稳定性。
- 受限来源无内容请求、无 Cookie/登录态/HTML 自动回退。
- Worker 支持并发边界、心跳、取消、截止时间、租约恢复和受控重试。
- MiniMax 完全离线时批次仍可完成。
- PostgreSQL 迁移、完整测试、Ruff、YAML 校验、浏览器验收和敏感信息扫描全部通过。
- 中文验收报告已提交，分支通过合并前代码审查。
