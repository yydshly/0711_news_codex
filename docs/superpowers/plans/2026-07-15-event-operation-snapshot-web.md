# 最新 Operation 事件快照网页实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让事件首页、全部事件、新兴线索和事件详情默认使用最新成功 `event_pipeline` Operation 的精确版本快照，同时保留全局 current 与 legacy 目录。

**Architecture:** 新增一个只读 Operation 快照选择模块，集中校验算法版本、窗口和 `(event_id, version_number)` 引用；事件查询层基于精确版本批量投影列表和详情。网页默认使用快照视图，历史目录继续调用现有 current/legacy 查询，不修改任何事件或 Operation 数据。

**Tech Stack:** Python 3.12、SQLAlchemy 2、FastAPI、Jinja2、Pydantic 2、pytest、Starlette TestClient、现有浏览器验收工具。

## Global Constraints

- 不自动修改 `EventRecord.visibility`，不删除或退役历史事件。
- 默认快照必须来自 `status=succeeded` 且算法版本精确等于 `EVENT_ALGORITHM_VERSIONS` 的 `event_pipeline` Operation。
- 列表、详情、评分和证据必须使用同一个 `version_number`。
- 时间筛选相对 Operation 的 `window_end`，不能使用页面请求时钟替代快照时钟。
- Operation JSON 作为不可信数据处理；拒绝重复、布尔值伪装整数、超限和缺失版本。
- 无合法快照时显示中文阻塞说明，不静默回退到全局 current。
- MiniMax 不参与快照选择、合规判断或页面口径。
- 不开发摘要、推荐、推送、调度或新的来源抓取能力。

---

## 文件职责映射

- 新建 `src/newsradar/events/operation_snapshots.py`：校验并选择完整 Operation 快照，提供稳定只读接口。
- 修改 `src/newsradar/events/reporting.py`：复用同一快照选择器，保证质量报告和网页不会再次漂移。
- 修改 `src/newsradar/web/event_queries.py`：批量投影指定事件版本、精确详情和快照页面元数据。
- 修改 `src/newsradar/web/app.py`：增加 `scope`、`operation`、`version` 路由语义。
- 修改 `src/newsradar/web/templates/events_home.html`、`events.html`、`emerging.html`、`event_detail.html`：展示快照来源、口径提示和固定详情链接。
- 新建 `tests/events/test_operation_snapshots.py`：快照选择和不可信 JSON 测试。
- 修改 `tests/events/test_reporting.py`：证明报告复用相同 Operation。
- 修改 `tests/web/test_event_queries.py`、`tests/web/test_event_routes.py`：查询、路由与模板行为。
- 修改 `tests/acceptance/test_event_web_worker_flow.py`：端到端固定版本验收。
- 更新 `reports/event-evidence-gap-v2-1.md`：记录网页口径收口后的真实结果。

---

### Task 1: 建立共享 Operation 快照选择器

**Files:**
- Create: `src/newsradar/events/operation_snapshots.py`
- Modify: `src/newsradar/events/reporting.py`
- Create: `tests/events/test_operation_snapshots.py`
- Modify: `tests/events/test_reporting.py`

**Interfaces:**
- Consumes: `OperationRunRecord`、`EventVersionRecord`、`EventScoreRecord`、`EVENT_ALGORITHM_VERSIONS`。
- Produces: `EventVersionRef`、`OperationSnapshotRef`、`latest_complete_event_snapshot(session, now)`、`event_snapshot_by_id(session, operation_id, now)`。

- [ ] **Step 1: 写失败测试，固定合法、跳过和拒绝规则**

在 `tests/events/test_operation_snapshots.py` 创建测试辅助函数并覆盖四个核心场景：

```python
from datetime import UTC, datetime

from newsradar.events.operation_snapshots import latest_complete_event_snapshot


NOW = datetime(2026, 7, 15, 6, 0, tzinfo=UTC)


def test_latest_complete_snapshot_skips_newer_incomplete_operation(db_session):
    complete = seed_pipeline_operation(
        db_session,
        operation_id=10,
        status="succeeded",
        window_end=NOW,
        event_versions=((41, 1),),
        persist_event_versions=True,
    )
    seed_pipeline_operation(
        db_session,
        operation_id=11,
        status="succeeded",
        window_end=NOW,
        event_versions=((99, 1),),
        persist_event_versions=False,
    )

    snapshot = latest_complete_event_snapshot(db_session, now=NOW)

    assert snapshot is not None
    assert snapshot.operation_id == complete.id
    assert snapshot.skipped_newer_count == 1
    assert snapshot.event_versions == (EventVersionRef(41, 1),)


def test_snapshot_rejects_duplicate_boolean_and_old_algorithm_refs(db_session):
    seed_pipeline_operation(db_session, operation_id=20, event_versions=((41, 1), (41, 1)))
    seed_pipeline_operation(db_session, operation_id=21, raw_event_versions=[{"event_id": True, "version_number": 1}])
    seed_pipeline_operation(db_session, operation_id=22, algorithm_versions={"cluster": "cluster-v1"})

    assert latest_complete_event_snapshot(db_session, now=NOW) is None
```

同时增加：failed/running 不可选、未来 `window_end` 不可选、超过 `MAX_SNAPSHOT_EVENTS` 不可选、版本或评分缺失时回退上一条完整 Operation。

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/events/test_operation_snapshots.py -q --tb=short
```

Expected: collection 失败，提示 `newsradar.events.operation_snapshots` 不存在。

- [ ] **Step 3: 实现最小共享选择器**

在 `src/newsradar/events/operation_snapshots.py` 实现以下公开结构和边界：

```python
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import MappingProxyType

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    EventScoreRecord,
    EventVersionRecord,
    OperationRunRecord,
)
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS

MAX_SNAPSHOT_EVENTS = 1_000


@dataclass(frozen=True, slots=True, order=True)
class EventVersionRef:
    event_id: int
    version_number: int


@dataclass(frozen=True, slots=True)
class OperationSnapshotRef:
    operation_id: int
    window_hours: int
    window_end: datetime
    finished_at: datetime
    algorithm_versions: MappingProxyType[str, str]
    event_versions: tuple[EventVersionRef, ...]
    skipped_newer_count: int = 0


def latest_complete_event_snapshot(
    session: Session, *, now: datetime | None = None
) -> OperationSnapshotRef | None:
    checked_at = _aware_utc(now or datetime.now(UTC))
    skipped = 0
    operations = session.scalars(
        select(OperationRunRecord)
        .where(
            OperationRunRecord.operation_type == "event_pipeline",
            OperationRunRecord.status == "succeeded",
            OperationRunRecord.created_at <= checked_at,
        )
        .order_by(OperationRunRecord.id.desc())
        .execution_options(yield_per=100)
    )
    for operation in operations:
        candidate = _validated_snapshot(session, operation, now=checked_at)
        if candidate is not None:
            return replace(candidate, skipped_newer_count=skipped)
        skipped += 1
    return None
```

`_validated_snapshot` 必须逐项验证：

```python
def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _event_refs(value: object) -> tuple[EventVersionRef, ...] | None:
    if not isinstance(value, list) or len(value) > MAX_SNAPSHOT_EVENTS:
        return None
    refs = []
    for row in value:
        if not isinstance(row, dict):
            return None
        event_id = _positive_int(row.get("event_id"))
        version = _positive_int(row.get("version_number"))
        if event_id is None or version is None:
            return None
        refs.append(EventVersionRef(event_id, version))
    return tuple(refs) if len(set(refs)) == len(refs) else None
```

再用两个集合查询确认所有 `EventVersionRecord` 和同版本 `EventScoreRecord` 存在；空事件列表允许作为完整的“无事件快照”。

- [ ] **Step 4: 让报告层复用选择器**

修改 `src/newsradar/events/reporting.py`：

- `_latest_pipeline_operation` 改为调用 `latest_complete_event_snapshot`；
- 使用返回的 `operation_id` 加载 `OperationRunRecord`；
- 删除重复的算法版本、事件引用和完整性选择逻辑；
- 保持 `render_event_quality_report` 文本与公开 dataclass 不变。

在 `tests/events/test_reporting.py` 增加：较新的损坏 Operation 与较旧完整 Operation 并存时，报告和共享选择器返回同一个 Operation ID。

- [ ] **Step 5: 运行定向测试并提交**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/events/test_operation_snapshots.py tests/events/test_reporting.py -q
.venv\Scripts\ruff.exe check src/newsradar/events/operation_snapshots.py src/newsradar/events/reporting.py tests/events/test_operation_snapshots.py tests/events/test_reporting.py
git diff --check
```

Expected: 全部 PASS，Ruff 与 diff check 为 exit 0。

Commit:

```powershell
git add src/newsradar/events/operation_snapshots.py src/newsradar/events/reporting.py tests/events/test_operation_snapshots.py tests/events/test_reporting.py
git commit -m "feat: select complete event operation snapshots"
```

---

### Task 2: 实现精确版本列表与详情查询

**Files:**
- Modify: `src/newsradar/web/event_queries.py`
- Modify: `tests/web/test_event_queries.py`

**Interfaces:**
- Consumes: `OperationSnapshotRef`、`EventVersionRef`、现有 `EventRow`、`EventDetailView`。
- Produces: `OperationEventPage`、`EventQueryService.latest_operation_page()`、`latest_operation_home()`、`get_operation_event()`；`EventRow.detail_href`。

- [ ] **Step 1: 写失败测试，证明查询固定到指定版本**

在 `tests/web/test_event_queries.py` 增加：

```python
def test_latest_operation_page_uses_exact_version_not_current_pointer(db_session):
    event = seed_event_with_versions(
        db_session,
        event_id=41,
        current_version=2,
        versions={1: "Operation 标题", 2: "后来更新的标题"},
    )
    seed_pipeline_snapshot(db_session, operation_id=81, refs=((event.id, 1),))

    page = EventQueryService(db_session).latest_operation_page(now=NOW)

    assert page is not None
    assert page.snapshot.operation_id == 81
    assert [row.zh_title for row in page.events] == ["Operation 标题"]
    assert page.events[0].detail_href == "/events/41?operation=81&version=1"


def test_operation_detail_rejects_event_not_in_operation(db_session):
    seed_event_with_versions(db_session, event_id=41, current_version=1)
    seed_pipeline_snapshot(db_session, operation_id=81, refs=())

    assert EventQueryService(db_session).get_operation_event(41, 81, 1, now=NOW) is None
```

增加筛选测试：status/category/tier 来自版本 payload；`hours=24` 以 `snapshot.window_end` 计算；同一个事件 current 指针变化后结果不变；证据成员按指定版本边界读取。

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/web/test_event_queries.py -k "operation or exact_version" -q --tb=short
```

Expected: FAIL，提示 `latest_operation_page`、`get_operation_event` 或 `detail_href` 不存在。

- [ ] **Step 3: 扩展只读视图对象**

在 `src/newsradar/web/event_queries.py` 增加：

```python
@dataclass(frozen=True, slots=True)
class SnapshotBannerView:
    operation_id: int
    window_hours: int
    window_end: datetime
    finished_at: datetime
    algorithm_versions: tuple[tuple[str, str], ...]
    skipped_newer_count: int


@dataclass(frozen=True, slots=True)
class OperationEventPage:
    events: tuple[EventRow, ...]
    filters: dict[str, object]
    snapshot: SnapshotBannerView
    tier_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class EventRow:
    # 保留现有字段
    detail_href: str
```

现有 current/legacy `_event_row` 将 `detail_href` 设置为 `f"/events/{event.id}"`；快照投影设置为带 Operation 和版本参数的安全内部 URL。

- [ ] **Step 4: 批量投影快照列表**

实现：

```python
def latest_operation_page(
    self,
    filters: dict[str, object] | None = None,
    *,
    now: datetime | None = None,
) -> OperationEventPage | None:
    snapshot = latest_complete_event_snapshot(self.session, now=now)
    if snapshot is None:
        return None
    rows = self._operation_rows(snapshot)
    filtered = self._filter_operation_rows(rows, filters or {}, snapshot.window_end)
    return OperationEventPage(
        events=filtered[:100],
        filters=dict(filters or {}),
        snapshot=_banner(snapshot),
        tier_counts=tuple(sorted(Counter(row.display_tier for row in rows).items())),
    )
```

`_operation_rows` 使用一次 join 查询 EventRecord、指定 EventVersionRecord 和同版本 EventScoreRecord。不能先读取 `current_version_number` 再查版本。`_filter_operation_rows` 仅接受已知状态、类别、层级与正整数小时。

- [ ] **Step 5: 实现固定版本详情**

新增：

```python
def get_operation_event(
    self,
    event_id: int,
    operation_id: int,
    version_number: int,
    *,
    now: datetime | None = None,
) -> EventDetailView | None:
    snapshot = event_snapshot_by_id(self.session, operation_id, now=now)
    expected = EventVersionRef(event_id, version_number)
    if snapshot is None or expected not in snapshot.event_versions:
        return None
    return self._detail_for_version(event_id, version_number, snapshot=_banner(snapshot))
```

把现有 `get_event` 的详情组装提取为 `_detail_for_version`，证据成员条件必须是：

```python
EventItemRecord.added_version_number <= version_number,
or_(
    EventItemRecord.removed_version_number.is_(None),
    EventItemRecord.removed_version_number > version_number,
)
```

- [ ] **Step 6: 运行定向测试并提交**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/web/test_event_queries.py -q
.venv\Scripts\ruff.exe check src/newsradar/web/event_queries.py tests/web/test_event_queries.py
git diff --check
```

Commit:

```powershell
git add src/newsradar/web/event_queries.py tests/web/test_event_queries.py
git commit -m "feat: query exact operation event versions"
```

---

### Task 3: 将网页路由和模板切换到快照默认口径

**Files:**
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/events.html`
- Modify: `src/newsradar/web/templates/event_detail.html`
- Modify: `tests/web/test_event_routes.py`

**Interfaces:**
- Consumes: Task 2 的 `latest_operation_page()`、`get_operation_event()`、`EventRow.detail_href`。
- Produces: `/events?scope=latest|current_catalog|catalog` 和固定版本详情路由行为。

- [ ] **Step 1: 写失败路由测试**

更新 `tests/web/test_event_routes.py` 的默认事件测试：

```python
def test_events_defaults_to_latest_operation_and_keeps_catalog_entry(db_session, monkeypatch):
    _add_event(db_session, 43, title="最新快照事件")
    _add_event(db_session, 44, title="旧 current 事件")
    _add_pipeline_snapshot(db_session, operation_id=81, refs=((43, 1),))
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        latest = client.get("/events")
        catalog = client.get("/events?scope=current_catalog")

    assert "Operation #81" in latest.text
    assert "最新快照事件" in latest.text
    assert "旧 current 事件" not in latest.text
    assert "/events/43?operation=81&amp;version=1" in latest.text
    assert "全局 current 目录" in catalog.text
    assert "旧 current 事件" in catalog.text
```

增加：无合法快照显示阻塞说明；只传 operation 或 version 返回 422/400；不属于 Operation 的组合返回 404；legacy 入口保持可用；HTML 不包含不可信 Operation 错误和密钥。

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/web/test_event_routes.py -q --tb=short
```

Expected: 默认页面仍显示全局 current，Operation 标识和固定详情链接断言失败。

- [ ] **Step 3: 修改路由**

在 `src/newsradar/web/app.py` 定义：

```python
EventScopeMode = Literal["latest", "current_catalog", "catalog"]
```

`/events` 路由：

```python
if scope == "latest" and visibility == "current":
    event_page = EventQueryService(session).latest_operation_page(filters)
else:
    event_page = EventQueryService(session).list_events(filters, visibility=visibility)
```

不要在 `event_page is None` 时调用 `list_events`；模板接收 `snapshot_unavailable=True` 并显示阻塞说明。

详情路由同时接收可选 `operation`、`version`。两者必须同时出现：

```python
if (operation is None) != (version is None):
    raise HTTPException(status_code=400, detail="operation_and_version_required")
detail = (
    service.get_operation_event(event_id, operation, version)
    if operation is not None and version is not None
    else service.get_event(event_id)
)
```

- [ ] **Step 4: 修改事件列表与详情模板**

`events.html`：

- 默认标题改为“最新运行事件”；
- 顶部展示 Operation、窗口、完成时间、算法版本和层级计数；
- `skipped_newer_count > 0` 时显示“已使用最近完整快照”；
- 筛选表保留 `scope=latest`；
- 所有事件链接使用 `{{ event.detail_href }}`；
- 提供“全局 current 目录”和“legacy 历史”入口；
- catalog 页面显示不同口径警告。

`event_detail.html`：

- 快照详情显示 Operation 与版本号；
- current 详情显示“全局 current 详情，不是固定 Operation 快照”。

- [ ] **Step 5: 运行路由测试并提交**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/web/test_event_routes.py tests/web/test_event_quality_pages.py -q
.venv\Scripts\ruff.exe check src/newsradar/web/app.py tests/web/test_event_routes.py
git diff --check
```

Commit:

```powershell
git add src/newsradar/web/app.py src/newsradar/web/templates/events.html src/newsradar/web/templates/event_detail.html tests/web/test_event_routes.py
git commit -m "feat: default event pages to operation snapshots"
```

---

### Task 4: 统一事件首页、新兴线索和端到端流程

**Files:**
- Modify: `src/newsradar/web/event_queries.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/events_home.html`
- Modify: `src/newsradar/web/templates/emerging.html`
- Modify: `tests/web/test_event_routes.py`
- Modify: `tests/acceptance/test_event_web_worker_flow.py`

**Interfaces:**
- Consumes: Task 2/3 的快照页面、固定详情链接和 banner。
- Produces: 所有事件主页面使用同一最新 Operation。

- [ ] **Step 1: 写失败测试，证明三个入口口径一致**

```python
def test_home_events_and_emerging_share_latest_operation(db_session, monkeypatch):
    seed_event(db_session, 41, status="confirmed", tier="hotspot")
    seed_event(db_session, 42, status="emerging", tier="signal")
    seed_event(db_session, 43, status="emerging", tier="signal")
    seed_pipeline_snapshot(db_session, operation_id=81, refs=((41, 1), (42, 1)))
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        home = client.get("/")
        events = client.get("/events")
        emerging = client.get("/emerging")

    for response in (home, events, emerging):
        assert "Operation #81" in response.text
    assert "43" not in events.text
    assert "42" in emerging.text
```

端到端测试在 Worker 成功构建事件后读取 Operation ID，验证 `/events` 默认选中该 Operation，点击固定详情仍能看到原始证据 URL。

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/web/test_event_routes.py tests/acceptance/test_event_web_worker_flow.py -q --tb=short
```

Expected: 首页和 emerging 仍读取全局 current，Operation 断言失败。

- [ ] **Step 3: 实现首页与 emerging 快照投影**

`EventQueryService.latest_operation_home()` 从同一个 `OperationEventPage` 构造：

- `hotspots`：tier 为 hotspot；
- `sections`：按 category 分组；
- confirmed/emerging/signal/audit 计数来自完整快照而不是列表截断结果；
- 首页最多展示 20 条，但统计基于完整快照。

`/emerging` 调用 `latest_operation_page({"status": "emerging", "limit": 50})`。

模板统一使用 `event.detail_href`，显示 Operation banner；无快照时显示与 `/events` 相同的阻塞入口。

- [ ] **Step 4: 运行网页与验收测试并提交**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/web tests/acceptance/test_event_web_worker_flow.py -q
.venv\Scripts\ruff.exe check src/newsradar/web tests/web tests/acceptance/test_event_web_worker_flow.py
git diff --check
```

Commit:

```powershell
git add src/newsradar/web/event_queries.py src/newsradar/web/app.py src/newsradar/web/templates/events_home.html src/newsradar/web/templates/emerging.html tests/web/test_event_routes.py tests/acceptance/test_event_web_worker_flow.py
git commit -m "feat: align event web surfaces to one snapshot"
```

---

### Task 5: 全量验证、真实数据库验收与中文报告

**Files:**
- Modify: `reports/event-evidence-gap-v2-1.md`
- Modify only if generated: `reports/event-quality-v2-1.md`

**Interfaces:**
- Consumes: 最新成功 Operation 和已实现网页。
- Produces: 可复现的测试、浏览器和中文验收证据。

- [ ] **Step 1: 运行完整自动化门禁**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check .
git diff --check
```

Expected: pytest exit 0；仅允许已有的环境 skip 和依赖弃用 warning；Ruff、diff check exit 0。

- [ ] **Step 2: 运行本地真实数据库只读验收**

使用 `local-postgresql-runtime/.env` 启动最新分支网页，不重新抓取、不调用 MiniMax。记录：

- 最新完整 Operation ID；
- `result_summary.event_version_snapshots` 数量；
- `/events` 页面事件数；
- hotspot/signal/audit_only 数量；
- `/events?scope=current_catalog` 数量。

Expected: 默认网页计数与 Operation 快照完全一致；catalog 可以不同但有明确提示。

- [ ] **Step 3: 浏览器验收固定详情**

在 `http://127.0.0.1:8767/` 验证：

1. 首页、全部事件、新兴线索显示同一 Operation；
2. `/events` 显示 Operation 781 对应的 86 条（如果数据库最新 Operation 已变化，以最新完整 Operation 为准）；
3. 随机打开至少 5 条详情，URL 包含 operation/version；
4. 详情的版本、独立证据数和评分与数据库快照相同；
5. catalog 页面显示“不同于最新运行快照”的中文提示；
6. 浏览页面不触发抓取或模型调用。

- [ ] **Step 4: 更新中文验收报告**

在 `reports/event-evidence-gap-v2-1.md` 增加“网页快照口径已收口”章节，写入真实 Operation ID、网页计数、catalog 差异和剩余证据覆盖缺口。不得写入数据库连接串、API Key、Cookie、代理配置或原始异常。

- [ ] **Step 5: 密钥扫描、最终状态和提交**

Run:

```powershell
$content = (git diff --no-ext-diff | Out-String)
$matches = [regex]::Matches(
  $content,
  'sk-[A-Za-z0-9_-]{20,}|(?im)^\s*(MINIMAX_API_KEY|GITHUB_TOKEN|YOUTUBE_API_KEY|REDDIT_CLIENT_SECRET)\s*=\s*\S+'
).Count
if ($matches -ne 0) { throw "secret pattern detected" }
git status --short
```

Expected: secret matches 为 0；只有本计划内文件发生变化。

Commit:

```powershell
git add reports/event-evidence-gap-v2-1.md reports/event-quality-v2-1.md
git commit -m "docs: record operation snapshot web acceptance"
```

如果 `event-quality-v2-1.md` 内容未变化，不要为了制造提交而改写它。

---

## 最终完成门禁

- [ ] 默认事件网页与最新完整 Operation 使用相同事件 ID 和版本号集合。
- [ ] 首页、全部事件、新兴线索和详情页显示同一 Operation 上下文。
- [ ] 全局 current 与 legacy 目录仍可访问并有口径提示。
- [ ] 无任何事件或 Operation 被自动修改、删除或退役。
- [ ] 无合法快照时不会静默展示其他口径。
- [ ] 全量 pytest、Ruff、diff check 和密钥扫描通过。
- [ ] 真实浏览器至少验证 5 个固定版本详情。
- [ ] 中文验收报告已记录剩余的双独立证据和热点缺口。
