# 来源覆盖收口 v1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不新增来源、不重写抓取器的前提下，将当前 `ready + direct` 来源中尚无成功抓取记录的目标完成分类、试抓、持久化和中文验收报告，并让现有 `/sources` 页面自动反映结果。

**Architecture:** 复用现有 YAML 注册表、`TrialDecision`、PostgreSQL、`OperationCommandService`、Worker、`FetchRun`/`RawItem` 和网页查询层。新增一个无副作用的覆盖规划器、一个只负责数据库快照与入队的运行服务、一个中文报告渲染器，以及 `newsradar sources close-coverage` CLI；默认仅查看计划，只有显式 `--execute` 才写数据库和入队。

**Tech Stack:** Python 3.12、Typer、Pydantic 2、SQLAlchemy 2、PostgreSQL、HTTPX、pytest、respx、现有 News Codex Worker。

## Global Constraints

- 工作分支固定为 `codex/source-coverage-closure-v1`，不得直接修改 `main`。
- 本里程碑只收口现有来源，不新增 Provider、Target、抓取协议、摘要、推荐、推送或后台调度功能。
- 复用现有 Worker 的租约、心跳、重试、取消和恢复机制；CLI 不直接执行网络请求。
- 默认命令必须只读；只有 `--execute` 可以同步 YAML、创建操作和生成报告文件。
- 每个试抓最多获取 5 条，命令行 `--max-items` 取值范围固定为 1–5，默认 5。
- 只有历史 `FetchRun.outcome` 为 `succeeded` 或 `no_change` 才算已覆盖；`partial`、`blocked`、`failed`、`pending` 不算已覆盖。
- 只有 `availability=ready`、`coverage_mode=direct` 且最新探测通过现有 `evaluate_trial_eligibility` 的目标才允许入队。
- 已覆盖或已有 `queued`/`running` Fetch 操作的来源不得重复入队。
- 单一来源失败不得阻止其他来源入队、等待或写入最终报告。
- OpenAI YouTube 的 Atom 主路径不再把 `engagement` 作为必需字段；互动信息仍保留在研究目标与 YouTube Data API 补充能力中。
- Qwen3 Releases 必须标记为 `availability=unavailable`、`status=degraded`；只有官方仓库产生 Release 且重新探测成功后才能解锁。
- 不使用 Cookie、浏览器登录态、验证码绕过、反爬绕过或未审核 HTML 抓取。
- MiniMax 不参与来源合规、启用、覆盖或入队决策；MiniMax 不可用不得影响本里程碑执行。
- 报告只记录来源 ID、状态、计数、稳定错误码和中文解释，不记录 API Key、Cookie、请求头、代理地址、数据库连接串或原始异常正文。
- 不新增数据库迁移；现有网页保持只读，不新增页面或写操作入口。

---

## 文件结构

- `sources/universe/universe-youtube-1.yaml`：修正 OpenAI YouTube 的主路径必需字段。
- `sources/github/qwen3-releases.yaml`：如实记录 Qwen3 Releases 当前不可用及解锁条件。
- `src/newsradar/ingestion/coverage_closure.py`：纯规则覆盖分类，禁止数据库、网络和模型依赖。
- `src/newsradar/ingestion/coverage_closure_runtime.py`：读取数据库覆盖证据、识别进行中操作、入队试抓和重建快照。
- `src/newsradar/ingestion/coverage_closure_reporting.py`：生成中文、脱敏、可审计的 Markdown 报告。
- `src/newsradar/cli.py`：增加 `sources close-coverage` 命令并复用现有等待逻辑。
- `tests/test_source_universe_catalog.py`：锁定两份 YAML 的业务口径。
- `tests/test_probes.py`：验证 YouTube Atom 在新必需字段下探测成功。
- `tests/ingestion/test_coverage_closure.py`：覆盖纯规划器的所有分类与幂等规则。
- `tests/ingestion/test_coverage_closure_runtime.py`：覆盖 SQL 查询、活跃操作去重和逐项入队。
- `tests/ingestion/test_coverage_closure_reporting.py`：覆盖中文报告结构和敏感信息隔离。
- `tests/test_coverage_closure_cli.py`：覆盖只读预览、参数校验、执行、等待和退出码。
- `reports/source-coverage-closure-v1.md`：真实 PostgreSQL 与 Worker 验收后生成的中文结果。

---

### Task 1: 修正 OpenAI YouTube 与 Qwen3 Releases 的来源事实

**Files:**
- Modify: `sources/universe/universe-youtube-1.yaml`
- Modify: `sources/github/qwen3-releases.yaml`
- Modify: `tests/test_source_universe_catalog.py`
- Modify: `tests/test_probes.py`

**Interfaces:**
- Consumes: `load_source_tree(Path) -> list[SourceDefinition]`、`ProbeFactory.create(AccessMethod)`。
- Produces: OpenAI YouTube 可由 Atom 主路径达到成功探测；Qwen3 Releases 不再进入 `ready + direct` 试抓范围。

- [ ] **Step 1: 先写目录口径失败测试**

在 `tests/test_source_universe_catalog.py` 增加：

```python
from pathlib import Path

from newsradar.providers.schema import Availability
from newsradar.sources.schema import SourceStatus
from newsradar.sources.yaml_loader import load_source_tree


def test_coverage_closure_catalog_facts_are_explicit() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}

    youtube = sources["openai-youtube"]
    assert youtube.expected_fields == [
        "title",
        "canonical_url",
        "published_at",
        "summary",
    ]
    assert "engagement" in youtube.research.wanted_information

    qwen = sources["qwen3-releases"]
    assert qwen.availability is Availability.UNAVAILABLE
    assert qwen.status is SourceStatus.DEGRADED
    assert qwen.unlock_requirements
    assert "Release" in qwen.unlock_requirements[0]
    assert qwen.official_identity_url == "https://github.com/QwenLM/Qwen3"
```

- [ ] **Step 2: 运行目录测试并确认旧 YAML 失败**

Run: `uv run pytest tests/test_source_universe_catalog.py::test_coverage_closure_catalog_facts_are_explicit -q`

Expected: FAIL；OpenAI 仍包含 `engagement`，Qwen3 仍为 `ready/candidate`。

- [ ] **Step 3: 修改两份 YAML**

将 OpenAI YouTube 的来源级字段改为：

```yaml
expected_fields: [title, canonical_url, published_at, summary]
```

研究区的 `wanted_information` 与 Data API 候选字段继续保留 `engagement`。

将 Qwen3 Releases 的身份与状态改为：

```yaml
status: degraded
availability: unavailable
official_identity_url: https://github.com/QwenLM/Qwen3
unlock_requirements:
  - Official QwenLM/Qwen3 repository publishes at least one GitHub Release and the content probe succeeds.
notes: 'The official releases endpoint currently returns no Release items. Keep catalog identity and evidence; do not substitute commits, events, HTML, cookies, or browser sessions.'
```

同时把 `research.conclusion` 改为明确说明“官方仓库身份已确认，但 Releases 端点目前没有可抓取条目”，把 `github-releases-api.sample_status` 改为 `blocked`；保留官方 REST 文档与端点证据。

- [ ] **Step 4: 写 YouTube Atom 字段完整度回归测试**

在 `tests/test_probes.py` 增加使用固定响应、禁止真实网络的测试：

```python
@pytest.mark.asyncio
async def test_openai_youtube_atom_is_successful_without_engagement_requirement() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    source = sources["openai-youtube"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                "<feed xmlns='http://www.w3.org/2005/Atom'>"
                "<entry><id>video-1</id><title>OpenAI update</title>"
                "<link href='https://www.youtube.com/watch?v=video-1'/>"
                "<published>2026-07-14T00:00:00Z</published>"
                "<summary>Official video</summary></entry></feed>"
            ),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ProbeFactory(client).create(source.access_methods[0]).probe(
            source, source.access_methods[0]
        )

    assert result.outcome is ProbeOutcome.SUCCESS
    assert result.field_completeness == 1.0
```

补充导入：

```python
from pathlib import Path
from newsradar.sources.yaml_loader import load_source_tree
```

- [ ] **Step 5: 运行目录和协议测试**

Run: `uv run pytest tests/test_source_universe_catalog.py tests/test_probes.py -q`

Expected: PASS；不得访问真实网络。

- [ ] **Step 6: 验证全部 YAML**

Run: `uv run newsradar sources validate --root sources`

Expected: 输出 `Validated 166 sources from ...`，无未知字段、枚举或 URL 错误。

- [ ] **Step 7: 提交来源事实修正**

```bash
git add sources/universe/universe-youtube-1.yaml sources/github/qwen3-releases.yaml tests/test_source_universe_catalog.py tests/test_probes.py
git commit -m "fix: align source readiness with probe evidence"
```

---

### Task 2: 实现无副作用的覆盖收口规划器

**Files:**
- Create: `src/newsradar/ingestion/coverage_closure.py`
- Create: `tests/ingestion/test_coverage_closure.py`

**Interfaces:**
- Consumes: `SourceDefinition`、`ProbeSnapshot`、`evaluate_trial_eligibility(source, probe)`。
- Produces:
  - `CoverageClosureState(StrEnum)`：`covered`、`queueable`、`blocked`。
  - `CoverageClosureEntry(source_id, name, state, code, reason)`。
  - `CoverageClosurePlan(entries)` 及 `covered`、`queueable`、`blocked` 属性。
  - `build_coverage_closure_plan(sources, snapshots, covered_source_ids, active_source_ids) -> CoverageClosurePlan`。

- [ ] **Step 1: 写规划器失败测试**

在 `tests/ingestion/test_coverage_closure.py` 建立最小 Source/Probe 工厂，并锁定以下行为：

```python
from datetime import UTC, datetime

from newsradar.ingestion.coverage_closure import (
    CoverageClosureState,
    build_coverage_closure_plan,
)
from newsradar.ingestion.trial import ProbeSnapshot
from newsradar.sources.schema import SourceDefinition
from tests.test_source_schema import valid_source


def source(source_id: str, **changes: object) -> SourceDefinition:
    values = valid_source()
    values.update(
        {
            "id": source_id,
            "name": source_id,
            "availability": "ready",
            "coverage_mode": "direct",
            **changes,
        }
    )
    return SourceDefinition.model_validate(values)


def probe(outcome: str = "success", samples: int = 1) -> ProbeSnapshot:
    return ProbeSnapshot(
        probe_run_id=1,
        outcome=outcome,
        sample_count=samples,
        field_completeness=1.0 if samples else 0.0,
        sample_fields=frozenset({"title", "canonical_url"}) if samples else frozenset(),
        finished_at=datetime(2026, 7, 14, tzinfo=UTC),
    )


def test_plan_classifies_covered_queueable_blocked_and_skips_out_of_scope() -> None:
    sources = [
        source("covered"),
        source("queueable"),
        source("active"),
        source("failed-probe"),
        source("catalog", coverage_mode="catalog_only"),
        source("unavailable", availability="unavailable"),
    ]
    snapshots = {
        item.id: probe("failed" if item.id == "failed-probe" else "success")
        for item in sources
    }

    plan = build_coverage_closure_plan(
        sources,
        snapshots,
        covered_source_ids={"covered"},
        active_source_ids={"active"},
    )

    assert [(entry.source_id, entry.state) for entry in plan.entries] == [
        ("active", CoverageClosureState.BLOCKED),
        ("covered", CoverageClosureState.COVERED),
        ("failed-probe", CoverageClosureState.BLOCKED),
        ("queueable", CoverageClosureState.QUEUEABLE),
    ]
    assert plan.by_source_id("active").code == "operation_in_progress"
    assert plan.by_source_id("failed-probe").code == "probe_not_successful"
    assert [entry.source_id for entry in plan.queueable] == ["queueable"]
```

再增加三个独立测试：输入顺序不同仍按 `source_id` 排序；无探测记录返回 `no_probe`；输入集合不被修改。

- [ ] **Step 2: 运行测试确认模块尚不存在**

Run: `uv run pytest tests/ingestion/test_coverage_closure.py -q`

Expected: FAIL with `ModuleNotFoundError: newsradar.ingestion.coverage_closure`。

- [ ] **Step 3: 实现规划器数据类型与纯函数**

在 `src/newsradar/ingestion/coverage_closure.py` 实现：

```python
from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from newsradar.ingestion.trial import (
    ProbeSnapshot,
    evaluate_trial_eligibility,
)
from newsradar.providers.schema import Availability, CoverageMode
from newsradar.sources.schema import SourceDefinition


class CoverageClosureState(StrEnum):
    COVERED = "covered"
    QUEUEABLE = "queueable"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class CoverageClosureEntry:
    source_id: str
    name: str
    state: CoverageClosureState
    code: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class CoverageClosurePlan:
    entries: tuple[CoverageClosureEntry, ...]

    @property
    def covered(self) -> tuple[CoverageClosureEntry, ...]:
        return tuple(item for item in self.entries if item.state is CoverageClosureState.COVERED)

    @property
    def queueable(self) -> tuple[CoverageClosureEntry, ...]:
        return tuple(item for item in self.entries if item.state is CoverageClosureState.QUEUEABLE)

    @property
    def blocked(self) -> tuple[CoverageClosureEntry, ...]:
        return tuple(item for item in self.entries if item.state is CoverageClosureState.BLOCKED)

    def by_source_id(self, source_id: str) -> CoverageClosureEntry:
        return next(item for item in self.entries if item.source_id == source_id)


def build_coverage_closure_plan(
    sources: Sequence[SourceDefinition],
    snapshots: Mapping[str, ProbeSnapshot],
    covered_source_ids: Collection[str],
    active_source_ids: Collection[str] = (),
) -> CoverageClosurePlan:
    covered = frozenset(covered_source_ids)
    active = frozenset(active_source_ids)
    entries: list[CoverageClosureEntry] = []
    for source in sorted(sources, key=lambda item: item.id):
        if source.availability is not Availability.READY:
            continue
        if source.coverage_mode is not CoverageMode.DIRECT:
            continue
        if source.id in covered:
            entries.append(CoverageClosureEntry(source.id, source.name, CoverageClosureState.COVERED, None, "已有成功抓取证据。"))
            continue
        if source.id in active:
            entries.append(CoverageClosureEntry(source.id, source.name, CoverageClosureState.BLOCKED, "operation_in_progress", "已有抓取任务正在排队或执行，本次不重复入队。"))
            continue
        decision = evaluate_trial_eligibility(source, snapshots.get(source.id))
        entries.append(
            CoverageClosureEntry(
                source.id,
                source.name,
                CoverageClosureState.QUEUEABLE if decision.eligible else CoverageClosureState.BLOCKED,
                decision.code,
                decision.reason,
            )
        )
    return CoverageClosurePlan(tuple(entries))
```

实现时使用 Ruff 允许的行宽拆分长表达式，不改变上述签名和决策顺序。

- [ ] **Step 4: 运行规划器测试**

Run: `uv run pytest tests/ingestion/test_coverage_closure.py -q`

Expected: PASS，至少 4 个测试通过。

- [ ] **Step 5: 运行现有 TrialDecision 回归测试**

Run: `uv run pytest tests/ingestion/test_trial.py tests/test_trial_cli.py -q`

Expected: PASS；不得放宽 0.60 完整度、公开直连、无敏感头等现有门槛。

- [ ] **Step 6: 提交纯规则规划器**

```bash
git add src/newsradar/ingestion/coverage_closure.py tests/ingestion/test_coverage_closure.py
git commit -m "feat: plan source coverage closure deterministically"
```

---

### Task 3: 实现数据库快照、幂等入队和执行证据

**Files:**
- Create: `src/newsradar/ingestion/coverage_closure_runtime.py`
- Create: `tests/ingestion/test_coverage_closure_runtime.py`

**Interfaces:**
- Consumes: Task 2 的 `CoverageClosurePlan`、`build_coverage_closure_plan`，现有 `SourceRepository.latest_probe_snapshots`、`OperationCommandService.enqueue_fetch`。
- Produces:
  - `ClosureOperation(source_id: str, operation_id: int, status: str | None)`。
  - `CoverageEvidence(source_id, latest_fetch_outcome, latest_fetch_error_code, raw_item_count)`。
  - `CoverageClosureService.plan(sources) -> CoverageClosurePlan`。
  - `CoverageClosureService.enqueue(plan, max_items, trigger) -> tuple[ClosureOperation, ...]`。
  - `CoverageClosureService.wait(operations) -> tuple[ClosureOperation, ...]`。
  - `CoverageClosureService.evidence(source_ids) -> tuple[CoverageEvidence, ...]`。

- [ ] **Step 1: 写数据库运行服务失败测试**

在 `tests/ingestion/test_coverage_closure_runtime.py` 使用现有 SQLite 测试 Session/模型工厂，覆盖：

```python
def test_service_counts_only_succeeded_and_no_change_as_covered(session) -> None:
    sources = [source("succeeded"), source("unchanged"), source("partial"), source("failed")]
    sync_sources_and_successful_probes(session, sources)
    add_fetch(session, "succeeded", "succeeded")
    add_fetch(session, "unchanged", "no_change")
    add_fetch(session, "partial", "partial")
    add_fetch(session, "failed", "failed")

    plan = CoverageClosureService(session).plan(sources)

    assert {item.source_id for item in plan.covered} == {"succeeded", "unchanged"}
    assert {item.source_id for item in plan.queueable} == {"partial", "failed"}
```

再增加：

```python
def test_service_does_not_queue_covered_blocked_or_active_sources(session, monkeypatch) -> None:
    # 构造 covered、queueable、blocked、active 四项；捕获 enqueue_fetch 调用。
    plan = CoverageClosureService(session).plan(sources)
    operations = CoverageClosureService(session).enqueue(plan, max_items=5, trigger="cli")
    assert [(item.source_id, item.operation_id) for item in operations] == [("queueable", 41)]
    assert calls == [
        {
            "source_id": "queueable",
            "max_items": 5,
            "trial": True,
            "trigger": "cli",
        }
    ]
```

第三个测试让第一个 `enqueue_fetch` 抛出稳定 `ValueError`，断言服务继续处理后续来源，并为失败来源返回 `status="enqueue_failed"`、`operation_id=0`，不包含异常正文。

- [ ] **Step 2: 运行测试确认运行服务尚不存在**

Run: `uv run pytest tests/ingestion/test_coverage_closure_runtime.py -q`

Expected: FAIL with `ModuleNotFoundError`。

- [ ] **Step 3: 实现数据库查询与数据类型**

在 `src/newsradar/ingestion/coverage_closure_runtime.py` 定义：

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsradar.db.models import FetchRunRecord, OperationRunRecord, RawItemRecord
from newsradar.ingestion.coverage_closure import CoverageClosurePlan, build_coverage_closure_plan
from newsradar.operations.commands import OperationCommandService
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import SourceDefinition

_COVERED_OUTCOMES = frozenset({"succeeded", "no_change"})
_ACTIVE_OPERATION_STATUSES = frozenset(
    {OperationStatus.QUEUED.value, OperationStatus.RUNNING.value}
)


@dataclass(frozen=True, slots=True)
class ClosureOperation:
    source_id: str
    operation_id: int
    status: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageEvidence:
    source_id: str
    latest_fetch_outcome: str | None
    latest_fetch_error_code: str | None
    raw_item_count: int
```

`CoverageClosureService.plan` 必须：

1. 查询 `FetchRunRecord.outcome.in_(_COVERED_OUTCOMES)` 的 distinct `source_id`。
2. 查询 Fetch 类型且处于 queued/running 的 `OperationRunRecord`，仅从 `requested_scope["source_id"]` 读取非空字符串。
3. 一次调用 `SourceRepository.latest_probe_snapshots` 获取所有输入来源的最近完成探测。
4. 把四组数据交给纯函数，自己不重写资格规则。

- [ ] **Step 4: 实现逐来源入队、等待和证据查询**

`enqueue` 必须逐个捕获预期的 `ValueError`，但不捕获 `KeyboardInterrupt`/`SystemExit`：

```python
def enqueue(
    self,
    plan: CoverageClosurePlan,
    *,
    max_items: int,
    trigger: str,
) -> tuple[ClosureOperation, ...]:
    if not 1 <= max_items <= 5:
        raise ValueError("max_items_must_be_between_1_and_5")
    commands = self._commands_factory(self.session)
    operations: list[ClosureOperation] = []
    for entry in plan.queueable:
        try:
            operation_id = commands.enqueue_fetch(
                source_id=entry.source_id,
                max_items=max_items,
                trial=True,
                trigger=trigger,
            )
        except ValueError:
            operations.append(ClosureOperation(entry.source_id, 0, "enqueue_failed"))
            continue
        operations.append(ClosureOperation(entry.source_id, operation_id))
    return tuple(operations)
```

`wait` 对 `operation_id > 0` 的每项调用现有 `wait_for_terminal`，逐项捕获 `LookupError`/`TimeoutError` 并转换为 `missing`/`timed_out`，继续等待其余操作；成功读取时用 `dataclasses.replace` 填充终态。

`evidence` 按来源查询最新 `FetchRunRecord` 和 `RawItemRecord` 计数，按 `source_id` 排序返回；只允许返回 `outcome` 与稳定 `error_code`，禁止返回 `error_message`、`final_url`、请求头或 payload。CLI 必须在入队前、终态后各取一次 evidence，报告用两次 RawItem 计数之差计算本轮新增量。

- [ ] **Step 5: 运行运行服务测试**

Run: `uv run pytest tests/ingestion/test_coverage_closure_runtime.py tests/operations/test_commands.py -q`

Expected: PASS；现有操作服务测试无回归。

- [ ] **Step 6: 提交运行服务**

```bash
git add src/newsradar/ingestion/coverage_closure_runtime.py tests/ingestion/test_coverage_closure_runtime.py
git commit -m "feat: orchestrate idempotent coverage trials"
```

---

### Task 4: 生成中文、脱敏的来源覆盖收口报告

**Files:**
- Create: `src/newsradar/ingestion/coverage_closure_reporting.py`
- Create: `tests/ingestion/test_coverage_closure_reporting.py`

**Interfaces:**
- Consumes: `CoverageClosurePlan`、`ClosureOperation`、`CoverageEvidence`。
- Produces:
  - `COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS`：设计文档中固定的 15 个基线缺口 ID。
  - `CatalogAdjustment(source_id, conclusion, evidence, next_action)`。
  - `render_coverage_closure_report(before, after, operations, before_evidence, after_evidence, adjustments, generated_at) -> str`。

- [ ] **Step 1: 写报告失败测试**

在 `tests/ingestion/test_coverage_closure_reporting.py` 构造 covered/queueable/blocked、成功/失败操作和 RawItem 计数：

```python
def test_report_is_chinese_auditable_and_scrubbed() -> None:
    report = render_coverage_closure_report(
        before=before_plan(),
        after=after_plan(),
        operations=(
            ClosureOperation("alpha", 11, "succeeded"),
            ClosureOperation("beta", 12, "failed"),
        ),
        before_evidence=(
            CoverageEvidence("alpha", None, None, 0),
            CoverageEvidence("beta", None, None, 0),
        ),
        after_evidence=(
            CoverageEvidence("alpha", "succeeded", None, 5),
            CoverageEvidence("beta", "failed", "rate_limited", 0),
        ),
        adjustments=(
            CatalogAdjustment(
                "qwen3-releases",
                "退出就绪直连统计",
                "官方 Releases 端点当前没有条目，HTTP 200 空数组不算内容覆盖。",
                "官方仓库出现 Release 后重新探测。",
            ),
        ),
        generated_at=datetime(2026, 7, 14, tzinfo=UTC),
    )

    assert "# 来源覆盖收口 v1 验收报告" in report
    assert "执行前" in report and "执行后" in report
    assert "alpha" in report and "beta" in report
    assert "已覆盖" in report and "仍阻塞" in report
    assert "sk-secret" not in report
    assert "DATABASE_URL" not in report
    assert "Authorization" not in report
```

再增加测试断言：

- 15 个 `COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS` 均在逐项结论中出现一次，包含已退出范围的 Qwen3。
- 结果表只包含 `来源 ID / 操作 ID / 操作状态 / 最近抓取结果 / 错误码 / 可重试 / 本轮新增 RawItem / 下一步`。
- `enqueue_failed`、`timed_out`、`rate_limited` 有固定中文说明；可重试性复用 `is_retryable_error`，不由 MiniMax 判断。
- OpenAI YouTube 的说明明确区分 Atom 必需字段和 Data API 互动量补充。
- Qwen3 的说明明确区分“HTTP 成功”与“有可用内容”。
- 结尾明确声明未使用 Cookie、浏览器会话、代理绕过或 MiniMax 决策。
- 同一输入输出字节一致。

- [ ] **Step 2: 运行测试确认报告模块尚不存在**

Run: `uv run pytest tests/ingestion/test_coverage_closure_reporting.py -q`

Expected: FAIL with `ModuleNotFoundError`。

- [ ] **Step 3: 实现固定结构 Markdown 渲染器**

报告必须按以下顺序输出：

```markdown
# 来源覆盖收口 v1 验收报告

- 生成时间：...
- 口径：仅统计 availability=ready 且 coverage_mode=direct 的来源。
- 成功口径：FetchRun 为 succeeded 或 no_change。

## 执行前

| 范围内 | 已覆盖 | 可入队 | 阻塞 |

## 本轮操作

| 来源 ID | 操作 ID | 操作状态 | 最近抓取结果 | 错误码 | 可重试 | 本轮新增 RawItem | 下一步 |

## 基线 15 项逐项结论

| 来源 ID | 执行前探测/资格 | 操作证据 | FetchRun 证据 | 本轮新增 RawItem | 最终结论 |

## 执行后

| 范围内 | 已覆盖 | 可入队 | 阻塞 |

## 仍未收口的来源

| 来源 ID | 稳定原因码 | 中文说明 |

## 两项目录口径修正

- OpenAI YouTube：Atom 负责公开发现；engagement 由需 Key 的 Data API 补充，不阻塞 Atom。
- Qwen3 Releases：当前无 Release 条目，退出 ready 统计；满足解锁条件后重新探测。

## 安全声明

- 本轮未使用 Cookie、浏览器会话、代理绕过或 MiniMax 决策。

## 结论
```

`COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS` 必须按设计文档固定为：

```python
COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS = (
    "arxiv-cs-cl",
    "arxiv-cs-lg",
    "cuda-python-releases",
    "gemini-cli-releases",
    "microsoft-research",
    "openai-youtube",
    "qwen3-releases",
    "transformers-releases",
    "universe-cnbc-1",
    "universe-hard-fork-1",
    "universe-import-ai-1",
    "universe-interconnects-1",
    "universe-mit-tech-review-1",
    "universe-techmeme-1",
    "universe-venturebeat-1",
)
```

渲染器只能读取 dataclass 的白名单字段；不得接受任意异常对象、HTTP 响应、环境变量或数据库模型作为参数。RawItem 新增量按 `max(after_count - before_count, 0)` 计算。空集合显示“无”，不得生成空表误导用户。

逐项结论按 `COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS` 顺序生成：先从 `before.entries` 读取执行前探测/资格结论，再关联 `ClosureOperation`、前后 `CoverageEvidence` 和 `after.entries`；若来源因目录修正退出范围，则必须从 `CatalogAdjustment` 取得证据和下一步。任一基线 ID 无法在 Plan 或 Adjustment 中解释时抛出 `ValueError("missing_baseline_conclusion:<source-id>")`，禁止静默漏项。

- [ ] **Step 4: 运行报告测试与 Ruff**

Run: `uv run pytest tests/ingestion/test_coverage_closure_reporting.py -q && uv run ruff check src/newsradar/ingestion/coverage_closure_reporting.py tests/ingestion/test_coverage_closure_reporting.py`

Expected: PASS，Ruff 无输出。

- [ ] **Step 5: 提交报告渲染器**

```bash
git add src/newsradar/ingestion/coverage_closure_reporting.py tests/ingestion/test_coverage_closure_reporting.py
git commit -m "feat: report source coverage closure in Chinese"
```

---

### Task 5: 增加只读预览与显式执行 CLI

**Files:**
- Modify: `src/newsradar/cli.py`
- Create: `tests/test_coverage_closure_cli.py`

**Interfaces:**
- Consumes: Task 3 的 `CoverageClosureService`，Task 4 的 `render_coverage_closure_report`，现有 `create_session` 与 `SourceRepository.sync`。
- Produces:
  - `newsradar sources close-coverage`
  - `newsradar sources close-coverage --execute --wait --max-items 5`

- [ ] **Step 1: 写默认只读和参数校验失败测试**

在 `tests/test_coverage_closure_cli.py` 使用 `typer.testing.CliRunner` 与 monkeypatch：

```python
def test_close_coverage_defaults_to_read_only(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "load_source_tree", lambda root: sources())
    monkeypatch.setattr(cli, "create_session", fake_session)
    monkeypatch.setattr(cli, "CoverageClosureService", lambda session: FakeService(calls))

    result = runner.invoke(cli.app, ["sources", "close-coverage"])

    assert result.exit_code == 0
    assert "仅预览，未写入数据库、未创建抓取任务" in result.stdout
    assert "范围内：4；已覆盖：1；可入队：2；阻塞：1" in result.stdout
    assert calls == ["plan"]
```

```python
def test_close_coverage_rejects_wait_without_execute() -> None:
    result = runner.invoke(cli.app, ["sources", "close-coverage", "--wait"])
    assert result.exit_code == 2
    assert "--wait 必须与 --execute 一起使用" in result.stdout
```

同时测试 `--max-items 0` 与 `6` 均由 Typer 返回 exit code 2。

- [ ] **Step 2: 运行 CLI 测试确认命令不存在**

Run: `uv run pytest tests/test_coverage_closure_cli.py -q`

Expected: FAIL；Typer 报告 `No such command 'close-coverage'`。

- [ ] **Step 3: 实现命令签名和只读分支**

在 `src/newsradar/cli.py` 增加导入，并在 `sources_app` 注册：

```python
@sources_app.command("close-coverage")
def close_source_coverage(
    root: RootOption = Path("sources"),
    execute: Annotated[bool, typer.Option("--execute/--no-execute")] = False,
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = False,
    max_items: Annotated[int, typer.Option("--max-items", min=1, max=5)] = 5,
    output: Annotated[Path, typer.Option("--output")] = Path(
        "reports/source-coverage-closure-v1.md"
    ),
) -> None:
```

命令开始时校验 `wait and not execute`，输出中文原因并 `raise typer.Exit(2)`。默认分支加载 YAML、打开只读 Session、调用 `service.plan(sources)`、输出四项计数后直接返回；不得调用 `sync`、`enqueue`、`wait`、`mkdir` 或 `write_text`。

- [ ] **Step 4: 写显式执行、等待和退出码测试**

增加三个测试：

1. `--execute --no-wait` 先 `SourceRepository.sync(sources)`，再调用 `enqueue(..., max_items=5, trigger="cli:coverage-closure-v1")`，只显示操作 ID，不生成“已完成”结论。
2. `--execute --wait` 在入队前查询一次 `evidence`，然后调用 `wait`、重新 `plan`、再次查询 `evidence`，并将报告写到 `--output`。
3. 即使一个操作为 `failed`，仍列出全部操作、写入报告，最后 exit code 1；`succeeded` 与 `partial` 操作终态本身可正常完成等待，但最终是否“覆盖”仍由 FetchRun 成功口径决定。

关键断言：

```python
assert calls == [
    "sync",
    "plan",
    "evidence_before",
    "enqueue",
    "wait",
    "plan",
    "evidence_after",
    "render",
]
assert "操作 11：succeeded" in result.stdout
assert "操作 12：failed" in result.stdout
assert output.read_text(encoding="utf-8").startswith("# 来源覆盖收口 v1 验收报告")
assert result.exit_code == 1
```

- [ ] **Step 5: 实现执行分支**

执行顺序固定为：

```python
with create_session() as session:
    repository = SourceRepository(session)
    repository.sync(sources)
    session.commit()
    service = CoverageClosureService(session)
    before = service.plan(sources)
    baseline_ids = COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS
    before_evidence = service.evidence(baseline_ids)
    operations = service.enqueue(
        before,
        max_items=max_items,
        trigger="cli:coverage-closure-v1",
    )
    if not wait:
        print_queued_operations(operations)
        return
    terminals = service.wait(operations)
    after = service.plan(sources)
    after_evidence = service.evidence(baseline_ids)
```

离开 Session 后再渲染报告、创建父目录、以 UTF-8 写文件。向渲染器传入固定 Qwen3 `CatalogAdjustment`；OpenAI 说明由报告固定结构生成。所有操作状态先逐项输出；若存在 `enqueue_failed`、`failed`、`cancelled`、`timed_out` 或 `missing`，在报告写完后 `raise typer.Exit(1)`。

- [ ] **Step 6: 运行 CLI 与相关回归测试**

Run: `uv run pytest tests/test_coverage_closure_cli.py tests/test_trial_cli.py tests/operations/test_worker.py -q`

Expected: PASS；Worker 现有租约、取消和终态测试无回归。

- [ ] **Step 7: 提交 CLI**

```bash
git add src/newsradar/cli.py tests/test_coverage_closure_cli.py
git commit -m "feat: execute bounded source coverage closure"
```

---

### Task 6: 验证网页自动展示，不新增第二套页面

**Files:**
- Modify: `tests/web/test_capability_queries.py`
- Modify: `tests/web/test_routes.py`

**Interfaces:**
- Consumes: 现有 `CapabilityQueryService` 对 `FetchRunRecord`/`RawItemRecord` 的查询，现有 `/sources` 路由。
- Produces: 证明收口结果无需新页面即可反映在网页的回归测试。

- [ ] **Step 1: 写页面数据更新测试**

在 `tests/web/test_capability_queries.py` 增加测试：同一 `ready + direct` 来源在无 FetchRun 时计入“未成功抓取”，插入 `succeeded` FetchRun 与 2 个 RawItem 后重新查询，断言已成功来源数增加 1、RawItem 数增加 2。

核心断言：

```python
before = service.get_capability_overview()
add_successful_fetch_with_items(session, source_id="closure-source", count=2)
after = service.get_capability_overview()

assert after.successfully_fetched_source_count == before.successfully_fetched_source_count + 1
assert after.raw_item_count == before.raw_item_count + 2
```

- [ ] **Step 2: 写 `/sources` 中文可见性测试**

在 `tests/web/test_routes.py` 增加或扩展现有 `/sources` 测试，断言响应包含当前能力、直接覆盖、成功抓取和 RawItem 数的中文标签，且不出现新的写操作按钮：

```python
response = client.get("/sources")
assert response.status_code == 200
assert "可直接抓取" in response.text
assert "已成功抓取" in response.text
assert "RawItem" in response.text
assert "close-coverage" not in response.text
```

- [ ] **Step 3: 运行网页回归测试**

Run: `uv run pytest tests/web/test_capability_queries.py tests/web/test_routes.py -q`

Expected: PASS；无需修改模板或增加路由。若现有 viewmodel 字段名不同，只调整测试使用项目中已有等价字段，不新增重复统计字段。

- [ ] **Step 4: 提交网页证据测试**

```bash
git add tests/web/test_capability_queries.py tests/web/test_routes.py
git commit -m "test: prove coverage closure updates existing dashboard"
```

---

### Task 7: 用本地 PostgreSQL 和专用 Worker 完成真实收口验收

**Files:**
- Create: `reports/source-coverage-closure-v1.md`（由 CLI 生成）
- Modify: `docs/superpowers/plans/2026-07-14-source-coverage-closure-v1.md`（勾选完成步骤与记录真实计数）

**Interfaces:**
- Consumes: 本机 `.env`、PostgreSQL、现有 Worker、Task 5 CLI。
- Produces: 可重复核验的真实操作记录、FetchRun、RawItem、中文报告和网页结果。

- [ ] **Step 1: 运行全量静态与单元验证**

Run:

```powershell
uv run ruff check .
uv run pytest -q
```

Expected: Ruff PASS；pytest 全绿，仅允许仓库基线中已知的显式 skip 和 deprecation warning。

- [ ] **Step 2: 在当前进程临时加载本地环境，不输出秘密**

从 `D:\codex_project_work\news_codex\.worktrees\local-postgresql-runtime\.env` 逐行加载非注释键值到当前 PowerShell 进程；不得执行 `Get-Content` 回显，不得把值写入日志、报告或 Git。验证只输出布尔状态：

```powershell
Write-Output ("DATABASE_URL configured: " + [bool]$env:DATABASE_URL)
Write-Output ("MINIMAX_API_KEY configured: " + [bool]$env:MINIMAX_API_KEY)
```

Expected: `DATABASE_URL configured: True`；MiniMax 是否配置不影响后续步骤。

- [ ] **Step 3: 同步目录并重新探测两个修正来源**

Run:

```powershell
uv run newsradar sources sync --root sources
uv run newsradar sources probe openai-youtube --root sources --persist
uv run newsradar sources probe qwen3-releases --root sources --persist
uv run newsradar sources close-coverage --root sources
```

Expected:

- OpenAI YouTube：`success`、样本数大于 0、完整度至少 90%。
- Qwen3 Releases：若端点仍为空则报告 blocked/无样本；其 YAML 状态仍为 unavailable/degraded，不进入可入队集合。
- 预览明确列出范围内、已覆盖、可入队、阻塞数量，且没有新 OperationRun。

- [ ] **Step 4: 避免旧工作树 Worker 消费新分支任务**

先读取 Worker PID 和完整命令行，只针对工作目录为 `.worktrees/source-failure-remediation` 的 Worker：记录启动命令与环境、请求其优雅停止，并确认 Web 进程和 PostgreSQL 仍运行。随后从当前工作树启动隐藏的专用 Worker，Worker ID 固定为 `source-coverage-closure-v1-runtime`。

验收条件：同一时刻只有这个专用 Worker 消费 Fetch 操作；不得结束 PostgreSQL、Web 或无关 Python 进程；执行完成后必须恢复原 Worker 的原始启动命令。

- [ ] **Step 5: 执行全部合格缺口并等待终态**

Run:

```powershell
uv run newsradar sources close-coverage --root sources --execute --wait --max-items 5 --output reports/source-coverage-closure-v1.md
```

Expected:

- 13 个原有合格缺口与重新探测合格的 OpenAI YouTube 逐项入队；实际数量以执行前只读计划为准。
- 每个来源最多 5 条。
- 一个来源失败不会中止其他来源等待和报告生成。
- 命令成功时 exit code 0；存在真实失败时可以 exit code 1，但报告必须完整生成并如实列出未收口项。

- [ ] **Step 6: 验证幂等、数据库证据和报告脱敏**

再次运行只读预览：

```powershell
uv run newsradar sources close-coverage --root sources
```

查询数据库并记录但不输出 payload/连接串：

- `ready + direct` 总数。
- 有 `succeeded/no_change` FetchRun 的来源数。
- 本轮 operation ID、终态、对应 FetchRun outcome。
- 各本轮来源 RawItem 数。
- 仍未覆盖的来源 ID 与稳定原因码。

Expected: 已成功来源不再出现在 queueable；无 queued/running 重复操作；报告不包含 `sk-`、`DATABASE_URL`、`Authorization`、`Cookie`、`Proxy-Authorization`。

- [ ] **Step 7: 恢复常驻 Worker 并用浏览器验收现有页面**

停止专用 Worker，按 Step 4 保存的原始命令恢复 `source-failure-remediation` Worker。确认：

- Web 仍可访问 `http://127.0.0.1:8766/sources`。
- `/sources` 显示的新成功抓取数与数据库一致。
- `/fetch-runs` 可看到本轮真实 FetchRun。
- `/raw-items` 可看到新条目；若某来源为 `no_change`，允许没有新增 RawItem。
- 页面没有执行收口或绕过审核的按钮。

- [ ] **Step 8: 提交真实验收报告**

先人工检查报告只有白名单字段，再执行：

```bash
git add reports/source-coverage-closure-v1.md docs/superpowers/plans/2026-07-14-source-coverage-closure-v1.md
git commit -m "docs: record source coverage closure evidence"
```

---

### Task 8: 最终审查、分支收口与合并准备

**Files:**
- Review: 本分支相对 `main` 的全部变更

**Interfaces:**
- Consumes: Tasks 1–7 的提交与真实报告。
- Produces: 可安全合并、无秘密、无回归的分支。

- [ ] **Step 1: 核对变更范围**

Run:

```powershell
git status --short
git diff --stat main...HEAD
git log --oneline --decorate main..HEAD
```

Expected: 只包含本计划列出的 YAML、Python、测试、计划和报告；不得包含 `.env`、`.local/postgres`、缓存、日志、数据库文件或用户的 `reports/source-intelligence.md`。

- [ ] **Step 2: 扫描秘密与高风险实现**

Run:

```powershell
rg -n "sk-[A-Za-z0-9_-]+|DATABASE_URL=|Authorization:|Cookie:|Proxy-Authorization:" sources src tests reports docs/superpowers/plans/2026-07-14-source-coverage-closure-v1.md
rg -n "requests\.get|httpx\.(get|post)|AsyncClient" src/newsradar/ingestion/coverage_closure*.py
```

Expected: 第一条无真实秘密命中（测试中的固定检测字符串可解释且不得像真实 Key）；第二条无网络客户端命中，证明 CLI/规划器未建立旁路抓取。

- [ ] **Step 3: 运行最终验证**

Run:

```powershell
uv run ruff check .
uv run pytest -q
uv run newsradar sources validate --root sources
git diff --check main...HEAD
```

Expected: 全部 PASS；`git diff --check` 无空白错误。

- [ ] **Step 4: 进行合并前代码审查**

逐项确认：

- 默认命令严格只读。
- `--execute` 只入队 `plan.queueable`。
- 历史成功与活跃操作均防重复。
- 资格判断只复用 `TrialDecision`，没有模型判断或全局放宽。
- 一个来源入队/等待失败不阻塞其他来源。
- 报告在失败情况下仍生成且最终退出码非零。
- Qwen3 不会被错误计入“可直接抓取缺口”。
- OpenAI YouTube 的 engagement 仍作为补充能力而非 Atom 必需字段。
- 网页复用现有数据库查询，没有新增第二套统计口径。

- [ ] **Step 5: 修复审查发现并重跑针对性测试**

每个发现先补失败测试，再做最小修复；运行该测试文件与最终全量命令。若没有发现，不创建空提交。

- [ ] **Step 6: 确认分支可合并但不自行覆盖 main**

Run:

```powershell
git status --short --branch
git rev-list --left-right --count main...HEAD
git merge-base --is-ancestor main HEAD
```

Expected: 工作树干净；分支只领先 `main`；`main` 是当前分支祖先。随后报告提交列表、测试结果、真实覆盖结果与仍阻塞来源，等待用户确认合并和推送。

---

## 验收结论口径

本里程碑“完成”不等于所有网络目标都强行成功，而是同时满足：

1. 当前所有 `ready + direct` 来源都被确定性归类为已覆盖、可入队或有稳定原因码的阻塞项。
2. 所有合格但未覆盖来源都通过现有 Worker 执行了一次最多 5 条的真实试抓。
3. OpenAI YouTube 的字段口径与 Atom 能力一致；Qwen3 Releases 不再虚报为 ready。
4. 重复执行不会为已覆盖或正在执行的来源创建重复任务。
5. PostgreSQL 中保存 FetchRun/RawItem 证据，中文报告与现有网页使用同一数据库事实。
6. 网络失败会被如实记录，不会卡死批次、泄露凭据或触发高风险网页回退。
7. 全量测试、Ruff、YAML 校验和合并前审查全部通过。

## 真实验收记录（2026-07-14）

- 目录同步后，当前范围为 42 个 `ready + direct` 来源；执行前 28 个已覆盖、14 个可入队、0 个阻塞。
- `openai-youtube` 重新探测成功：5 条样本、100% 字段完整度；其 Atom 主路径没有因互动量字段被阻塞。
- `qwen3-releases` 重新探测为 0 条 JSON 样本并保持 `degraded + unavailable`，退出就绪统计且未创建抓取任务。
- 专用 Worker 执行 operation 303–316；14 个 trial FetchRun 均为 `succeeded`，无活跃操作残留。
- 本轮新增 66 条 RawItem：13 个来源各 5 条，`universe-hard-fork-1` 为 1 条。
- 幂等预览结果为：范围内 42、已覆盖 42、可入队 0、阻塞 0。
- 已恢复常驻 Worker；8766 网页已重启到当前分支，页面显示就绪直连 42、实际抓取来源 42、RawItem 429。
