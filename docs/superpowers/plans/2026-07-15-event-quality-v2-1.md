# News Codex 事件质量 v2.1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Only use `superpowers:subagent-driven-development` if the user explicitly requests subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Event Intelligence v2 上完成热点、线索和噪声三层收口，把多入口报道聚合为可演进事件，并提供可信的中文热点首页。

**Architecture:** 保留现有 `RawItem → EventCandidate → Event → EventVersion` 主链路，在相关性之后增加新闻价值判断，在聚类中增加可审计候选对和有限 MiniMax 边界辅助，在发布时物化 `display_tier` 与 `rank_score`。网页只读完整版本并创建 Operation，Worker 继续承担网络、模型、重试、取消和恢复。

**Tech Stack:** Python 3.12、Pydantic 2、SQLAlchemy 2、Alembic、PostgreSQL/SQLite 测试、FastAPI/Jinja2、HTTPX、MiniMax、pytest、ruff。

## 全局约束

- 不使用 Docker，不新增来源平台或 Target。
- 不创建第二套事件表或第二条事件管线。
- MiniMax 不得决定来源合规、证据独立性、事件确认状态、评分输入或排名权重。
- 模型并发上限为 2；模型不可用时规则管线必须完成。
- 所有网络和模型调用均由 Worker 执行，网页只入队。
- 不删除 RawItem、旧事件、版本、证据、模型记录或人工审核记录。
- 不记录 API Key、Cookie、Authorization、数据库连接串、提示全文或敏感 URL 查询参数。
- 不修改或提交 `main` 中用户未提交的来源报告。
- 不删除包含 `.env`、`.local/postgres` 或未提交报告的既有工作树。
- 不强制推送；每个里程碑独立提交。
- 完整测试环境使用 `uv sync --all-extras`，测试使用工作树 `.venv` 的 Python 3.12。

## 文件职责图

- `src/newsradar/events/schema.py`：v2.1 稳定枚举和跨模块值对象。
- `src/newsradar/events/newsworthiness.py`：新闻价值与事件动作纯规则。
- `src/newsradar/events/clustering.py`：有界候选对、确定性规则分数和并查集聚类。
- `src/newsradar/events/pairing.py`：边界候选模型辅助编排与最终判定。
- `src/newsradar/events/ranking.py`：展示层级和排名纯函数。
- `src/newsradar/events/minimax.py`：受限上下文的候选对与中文增强适配器。
- `src/newsradar/events/pipeline.py`：阶段编排、检查点、短事务和统计。
- `src/newsradar/events/repository.py`：事件、候选对、模型用量和版本的持久化边界。
- `src/newsradar/events/reporting.py`：v2.1 只读中文质量报告。
- `src/newsradar/web/event_queries.py`：热点、分类栏目、线索和详情只读查询。
- `src/newsradar/web/templates/`：中文首页、列表和详情展示。
- `migrations/versions/20260715_0015_event_quality_v2_1.py`：展示层级、排名和候选对审计迁移。

---

## Milestone 1：数据契约、迁移与持久化

**Files:**

- Create: `migrations/versions/20260715_0015_event_quality_v2_1.py`
- Modify: `src/newsradar/db/models.py`
- Modify: `src/newsradar/events/schema.py`
- Modify: `src/newsradar/events/repository.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/events/test_schema.py`
- Modify: `tests/events/test_repository.py`

**Interfaces:**

- Produces: `EventTier`, `PairDecisionKind`, `PairRuleDecision`, `PairFinalDecision`, `TierDecision`。
- Produces: `EventPairDecisionRecord`、`EventRecord.display_tier`、`EventRecord.rank_score`、
  `EventModelRunRecord.pair_decision_id`。
- Produces: `EventRepository.get_pair_decision(...)`、`record_pair_decision(...)` 与
  `record_pair_model_run(...)`。

- [ ] **Step 1: 写失败的 Schema 与迁移测试**

在 `tests/events/test_schema.py` 增加：

```python
from newsradar.events.schema import EventTier, PairDecisionKind, PairFinalDecision


def test_event_quality_v2_1_enums_are_stable() -> None:
    assert tuple(EventTier) == (
        EventTier.HOTSPOT,
        EventTier.SIGNAL,
        EventTier.AUDIT_ONLY,
    )
    assert tuple(PairDecisionKind) == (
        PairDecisionKind.DIRECT_MERGE,
        PairDecisionKind.DIRECT_SEPARATE,
        PairDecisionKind.MODEL_BOUNDARY,
    )
    decision = PairFinalDecision(
        left_raw_item_id=1,
        right_raw_item_id=2,
        input_fingerprint="a" * 64,
        rule_score=0.61,
        rule_reasons=("shared_object_entity",),
        decision="separate",
        model_same_event=False,
        model_confidence=0.0,
    )
    assert decision.left_raw_item_id < decision.right_raw_item_id
```

在 `tests/test_migrations.py` 的迁移链测试中断言：

```python
event_columns = inspector.get_columns("events")
assert {column["name"] for column in event_columns} >= {"display_tier", "rank_score"}
assert "event_pair_decisions" in inspector.get_table_names()
pair_indexes = inspector.get_indexes("event_pair_decisions")
assert any(index["name"] == "ix_event_pair_decisions_lookup" for index in pair_indexes)
model_run_columns = inspector.get_columns("event_model_runs")
assert "pair_decision_id" in {column["name"] for column in model_run_columns}
```

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/events/test_schema.py tests/test_migrations.py -q
```

预期：因枚举、字段和表尚不存在而失败。

- [ ] **Step 2: 实现稳定值对象和 ORM 模型**

在 `schema.py` 增加：

```python
class EventTier(StrEnum):
    HOTSPOT = "hotspot"
    SIGNAL = "signal"
    AUDIT_ONLY = "audit_only"


class PairDecisionKind(StrEnum):
    DIRECT_MERGE = "direct_merge"
    DIRECT_SEPARATE = "direct_separate"
    MODEL_BOUNDARY = "model_boundary"


class PairRuleDecision(_Schema):
    left_raw_item_id: int
    right_raw_item_id: int
    score: float = Field(ge=0, le=1)
    reasons: tuple[str, ...]
    structural_anchor: bool
    kind: PairDecisionKind


class PairFinalDecision(_Schema):
    left_raw_item_id: int
    right_raw_item_id: int
    input_fingerprint: str = Field(min_length=64, max_length=64)
    rule_score: float = Field(ge=0, le=1)
    rule_reasons: tuple[str, ...]
    decision: Literal["merge", "separate", "undetermined"]
    model_same_event: bool | None = None
    model_confidence: float | None = Field(default=None, ge=0, le=1)


class TierDecision(_Schema):
    tier: EventTier
    rank_score: float = Field(ge=0, le=100)
    reasons: tuple[str, ...]
```

在 `models.py` 为 `EventRecord` 增加：

```python
display_tier: Mapped[str] = mapped_column(
    String(16), nullable=False, default="signal", server_default="signal"
)
rank_score: Mapped[float] = mapped_column(
    Float, nullable=False, default=0, server_default="0"
)
```

并新增：

```python
class EventPairDecisionRecord(Base):
    __tablename__ = "event_pair_decisions"
    __table_args__ = (
        UniqueConstraint(
            "left_raw_item_id",
            "right_raw_item_id",
            "algorithm_version",
            "input_fingerprint",
            name="uq_event_pair_decision_input",
        ),
        Index(
            "ix_event_pair_decisions_lookup",
            "left_raw_item_id",
            "right_raw_item_id",
            "algorithm_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    left_raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    right_raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(120), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_score: Mapped[float] = mapped_column(Float, nullable=False)
    rule_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    model_same_event: Mapped[bool | None] = mapped_column(Boolean)
    model_confidence: Mapped[float | None] = mapped_column(Float)
    final_decision: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

`EventModelRunRecord` 增加 `pair_decision_id` 外键。`left_raw_item_id < right_raw_item_id` 同时由数据库约束和仓储入口校验。

- [ ] **Step 3: 实现 Alembic 迁移**

迁移必须：

```python
revision = "20260715_0015"
down_revision = "20260714_0014"


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("display_tier", sa.String(16), nullable=False, server_default="signal"),
    )
    op.add_column(
        "events",
        sa.Column("rank_score", sa.Float(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE events SET display_tier = CASE "
        "WHEN visibility = 'legacy' OR status = 'rejected' THEN 'audit_only' "
        "WHEN status = 'confirmed' THEN 'hotspot' ELSE 'signal' END"
    )
    op.execute(
        "UPDATE events SET rank_score = COALESCE((SELECT heat FROM event_scores "
        "WHERE event_scores.event_id = events.id "
        "AND event_scores.version_number = events.current_version_number), 0)"
    )
    op.create_index(
        "ix_events_tier_rank_occurred_at",
        "events",
        ["visibility", "display_tier", "rank_score", "occurred_at"],
    )
    op.create_table(
        "event_pair_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("left_raw_item_id", sa.Integer(), sa.ForeignKey("raw_items.id"), nullable=False),
        sa.Column("right_raw_item_id", sa.Integer(), sa.ForeignKey("raw_items.id"), nullable=False),
        sa.Column("algorithm_version", sa.String(120), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("rule_score", sa.Float(), nullable=False),
        sa.Column("rule_reasons", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("model_same_event", sa.Boolean()),
        sa.Column("model_confidence", sa.Float()),
        sa.Column("final_decision", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("left_raw_item_id < right_raw_item_id", name="ck_event_pair_order"),
        sa.UniqueConstraint(
            "left_raw_item_id",
            "right_raw_item_id",
            "algorithm_version",
            "input_fingerprint",
            name="uq_event_pair_decision_input",
        ),
    )
    op.create_index(
        "ix_event_pair_decisions_lookup",
        "event_pair_decisions",
        ["left_raw_item_id", "right_raw_item_id", "algorithm_version"],
    )
    op.add_column(
        "event_model_runs",
        sa.Column("pair_decision_id", sa.Integer(), sa.ForeignKey("event_pair_decisions.id")),
    )
    op.create_index(
        "ix_event_model_runs_pair_decision_id",
        "event_model_runs",
        ["pair_decision_id"],
    )
```

`downgrade()` 逆序删除模型关联索引与字段、候选对索引与表、事件索引和字段，不修改其他对象。

- [ ] **Step 4: 实现幂等候选对仓储并测试**

测试同一输入重复写入只产生一行，不同指纹保留新审计行；错误的左右顺序被拒绝。仓储接口固定为：

```python
def get_pair_decision(
    self,
    left_raw_item_id: int,
    right_raw_item_id: int,
    algorithm_version: str,
    input_fingerprint: str,
) -> EventPairDecisionRecord | None:
    left, right = sorted((left_raw_item_id, right_raw_item_id))
    return self.session.scalar(
        select(EventPairDecisionRecord).where(
            EventPairDecisionRecord.left_raw_item_id == left,
            EventPairDecisionRecord.right_raw_item_id == right,
            EventPairDecisionRecord.algorithm_version == algorithm_version,
            EventPairDecisionRecord.input_fingerprint == input_fingerprint,
        )
    )
```

`record_pair_decision()` 使用数据库方言对应的 `ON CONFLICT DO NOTHING`，随后读取并返回唯一记录。
`record_pair_model_run(pair_decision_id, usage)` 复用 `ModelUsageRecord` 的安全字段约束，并写入
`EventModelRunRecord(pair_decision_id=..., event_id=None, raw_item_id=None)`；一次结构修复重试的每个尝试均写一行。

把现有模型用量构造提取为仓储私有方法，避免事件增强与候选对增强产生两套清洗规则：

```python
def _add_model_usage(self, usage: ModelUsage) -> ModelUsageRecord:
    record = ModelUsageRecord(
        purpose=usage.purpose,
        model=usage.model,
        input_tokens=max(0, usage.input_tokens),
        output_tokens=max(0, usage.output_tokens),
        latency_ms=usage.latency_ms,
        outcome=usage.outcome,
        error=usage.error[:1_000] if usage.error else None,
    )
    self.session.add(record)
    self.session.flush()
    return record


def record_pair_model_run(self, pair_decision_id: int, usage: ModelUsage) -> None:
    model_usage = self._add_model_usage(usage)
    self.session.add(
        EventModelRunRecord(
            pair_decision_id=pair_decision_id,
            model_usage_id=model_usage.id,
            stage=usage.purpose,
            algorithm_version=usage.model,
        )
    )
```

- [ ] **Step 5: 验证并提交 Milestone 1**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/events/test_schema.py tests/events/test_repository.py tests/test_migrations.py -q
.\.venv\Scripts\ruff.exe check src/newsradar/db/models.py src/newsradar/events/schema.py src/newsradar/events/repository.py migrations/versions/20260715_0015_event_quality_v2_1.py
git diff --check
git add migrations/versions/20260715_0015_event_quality_v2_1.py src/newsradar/db/models.py src/newsradar/events/schema.py src/newsradar/events/repository.py tests/test_migrations.py tests/events/test_schema.py tests/events/test_repository.py
git commit -m "feat: add event quality v2.1 persistence"
```

---

## Milestone 2：新闻价值过滤与完整处理审计

**Files:**

- Create: `src/newsradar/events/newsworthiness.py`
- Modify: `src/newsradar/events/schema.py`
- Modify: `src/newsradar/events/versions.py`
- Modify: `src/newsradar/events/pipeline.py`
- Create: `tests/events/test_newsworthiness.py`
- Modify: `tests/events/test_pipeline.py`

**Interfaces:**

- Produces: `NewsworthinessDecision`。
- Produces: `evaluate_newsworthiness(item: RawItemText) -> NewsworthinessDecision`。
- Extends: `ProcessingStage.NEWSWORTHINESS` 与版本 `newsworthiness-v1`。

- [ ] **Step 1: 写正反样本失败测试**

`tests/events/test_newsworthiness.py` 至少覆盖：

```python
@pytest.mark.parametrize(
    "title",
    (
        "OpenAI releases GPT-6 API",
        "Anthropic raises $5B in new funding",
        "New benchmark finds reasoning gains in small language models",
        "Critical vulnerability disclosed in an AI inference server",
    ),
)
def test_explicit_ai_events_are_newsworthy(title: str) -> None:
    result = evaluate_newsworthiness(RawItemText(title=title))
    assert result.outcome == "included"
    assert result.action is not None


@pytest.mark.parametrize(
    "title",
    (
        "Subscribe for the best AI deals",
        "#AI #LLM https://example.com",
        "SpaceX stock sinks for a second day",
        "Agent 64 game patch notes",
    ),
)
def test_non_events_and_off_topic_items_are_audit_only(title: str) -> None:
    result = evaluate_newsworthiness(RawItemText(title=title))
    assert result.outcome == "excluded"
    assert result.reason_codes
```

运行并确认因模块不存在而失败。

- [ ] **Step 2: 实现纯规则判断**

在 `schema.py` 增加：

```python
class NewsworthinessDecision(_Schema):
    outcome: Literal["included", "excluded"]
    score: int = Field(ge=0, le=100)
    action: str | None = None
    reason_codes: tuple[str, ...]
```

`newsworthiness.py` 必须把动作词归一为稳定动作族，并返回确定结果：

```python
NEWSWORTHINESS_RULE_VERSION = "newsworthiness-v1"
ACTION_GROUPS = {
    "release": frozenset({"announce", "launch", "release", "publish", "unveil", "open source"}),
    "funding": frozenset({"funding", "raises", "raised", "investment"}),
    "acquisition": frozenset({"acquire", "acquires", "acquired", "acquisition"}),
    "research_result": frozenset({"benchmark", "study", "paper", "finds", "achieves"}),
    "security": frozenset({"breach", "vulnerability", "exploit", "incident"}),
    "policy": frozenset({"regulation", "policy", "ban", "law", "executive order"}),
    "pricing": frozenset({"price", "pricing", "cost", "subscription"}),
    "outage": frozenset({"outage", "downtime", "disruption"}),
    "partnership": frozenset({"partner", "partnership", "collaboration"}),
}


def evaluate_newsworthiness(item: RawItemText) -> NewsworthinessDecision:
    text = normalize_text(" ".join((item.title, item.summary, item.content[:1_000])))
    if not text.strip():
        return NewsworthinessDecision(
            outcome="excluded", score=0, reason_codes=("insufficient_text",)
        )
    if _looks_like_link_only_repost(text):
        return NewsworthinessDecision(
            outcome="excluded", score=10, reason_codes=("auto_repost_without_claim",)
        )
    action = _event_action(text)
    if action is None:
        return NewsworthinessDecision(
            outcome="excluded", score=35, reason_codes=("no_event_action",)
        )
    return NewsworthinessDecision(
        outcome="included", score=80, action=action, reason_codes=("event_action", action)
    )
```

广告、订阅、招聘和非目标主题沿用 `relevance-v2` 的已有排除原因，不复制第二套冲突词表。

- [ ] **Step 3: 接入 Pipeline 并批量持久化**

`SelectionResult` 增加新闻价值决定；Pipeline 流程变为：相关性通过后再执行新闻价值判断，只有两者均通过才生成 `ClusterItem`。
为每个 72 小时窗口 RawItem 写入唯一 `newsworthiness-v1` 处理记录。Operation 结果增加：

```python
newsworthy_item_count: int
non_newsworthy_item_count: int
newsworthiness_reasons: dict[str, int]
```

检查点增加 `after_event_newsworthiness`。单条规则异常记录 `newsworthiness_rule_failed` 并排除该条，不中断批次。

- [ ] **Step 4: 验证覆盖、幂等和故障隔离**

增加 Pipeline 测试断言：选择数量等于相关性纳入、相关性排除和新闻价值排除之和；相同 Operation 重放不产生重复处理记录；一条异常不影响其他条目。

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/events/test_newsworthiness.py tests/events/test_pipeline.py tests/events/test_runtime.py -q
.\.venv\Scripts\ruff.exe check src/newsradar/events/newsworthiness.py src/newsradar/events/schema.py src/newsradar/events/versions.py src/newsradar/events/pipeline.py
```

- [ ] **Step 5: 提交 Milestone 2**

```powershell
git add src/newsradar/events/newsworthiness.py src/newsradar/events/schema.py src/newsradar/events/versions.py src/newsradar/events/pipeline.py tests/events/test_newsworthiness.py tests/events/test_pipeline.py tests/events/test_runtime.py
git commit -m "feat: filter event candidates by newsworthiness"
```

---

## Milestone 3：可审计混合聚类与 MiniMax 边界辅助

**Files:**

- Create: `src/newsradar/events/pairing.py`
- Modify: `src/newsradar/events/clustering.py`
- Modify: `src/newsradar/events/minimax.py`
- Modify: `src/newsradar/events/pipeline.py`
- Modify: `src/newsradar/events/repository.py`
- Create: `tests/events/test_pairing.py`
- Modify: `tests/events/test_clustering.py`
- Modify: `tests/events/test_minimax.py`
- Modify: `tests/events/test_pipeline.py`

**Interfaces:**

- Produces: `candidate_pairs(items) -> tuple[tuple[ClusterItem, ClusterItem], ...]`。
- Produces: `evaluate_pair_rules(left, right) -> PairRuleDecision`。
- Produces: `EventPipeline._resolve_pair_decisions(...) -> dict[tuple[int, int], PairFinalDecision]`。
- Extends: `cluster_candidates(items, pair_decisions) -> tuple[CandidateCluster, ...]`。

- [ ] **Step 1: 写阈值、结构锚点和缓存失败测试**

必须覆盖：精确根直接合并；分数 `>=0.80` 且有锚点直接合并；`<=0.45` 直接分开；边界区调用模型；模型置信度不足或无锚点时分开；同一输入指纹复用审计结果。

核心测试：

```python
def test_model_cannot_merge_without_structural_anchor() -> None:
    rule = PairRuleDecision(
        left_raw_item_id=1,
        right_raw_item_id=2,
        score=0.62,
        reasons=("within_72_hours",),
        structural_anchor=False,
        kind=PairDecisionKind.MODEL_BOUNDARY,
    )
    semantic = PairSemanticDecision(
        same_event=True,
        confidence=0.99,
        rationale="similar topic",
        origin="model",
    )
    final = finalize_pair_decision(rule, semantic, "a" * 64)
    assert final.decision == "separate"


def test_high_confidence_model_can_confirm_anchored_boundary_pair() -> None:
    rule = PairRuleDecision(
        left_raw_item_id=1,
        right_raw_item_id=2,
        score=0.68,
        reasons=("shared_object_entity", "same_action"),
        structural_anchor=True,
        kind=PairDecisionKind.MODEL_BOUNDARY,
    )
    semantic = PairSemanticDecision(
        same_event=True,
        confidence=0.91,
        rationale="same release",
        origin="model",
    )
    assert finalize_pair_decision(rule, semantic, "b" * 64).decision == "merge"
```

- [ ] **Step 2: 拆分候选生成和规则判定**

在 `clustering.py` 导出有界候选对，不允许全量两两比较。`evaluate_pair_rules()` 固定使用设计阈值：

```python
def evaluate_pair_rules(left: ClusterItem, right: ClusterItem) -> PairRuleDecision:
    compared = compare_items(left, right)
    structural_anchor = bool(
        {"same_evidence_root", "same_canonical_url", "same_repository_id", "same_paper_id",
         "shared_object_entity", "same_action"}
        & set(compared.reasons)
    )
    if compared.score >= 0.80 and structural_anchor:
        kind = PairDecisionKind.DIRECT_MERGE
    elif compared.score <= 0.45 or not structural_anchor:
        kind = PairDecisionKind.DIRECT_SEPARATE
    else:
        kind = PairDecisionKind.MODEL_BOUNDARY
    return PairRuleDecision(
        left_raw_item_id=min(left.raw_item_id, right.raw_item_id),
        right_raw_item_id=max(left.raw_item_id, right.raw_item_id),
        score=compared.score,
        reasons=compared.reasons,
        structural_anchor=structural_anchor,
        kind=kind,
    )
```

普通窗口改为 72 小时；7 天持续发展窗口只在相同核心对象和相同动作族时进入候选。

- [ ] **Step 3: 实现安全输入指纹与最终判定**

`pairing.py` 的指纹只包含规范化安全字段：

```python
def pair_input_fingerprint(left: ClusterItem, right: ClusterItem) -> str:
    ordered = sorted((left, right), key=lambda item: item.raw_item_id)
    payload = [
        {
            "id": item.raw_item_id,
            "title": item.title[:500],
            "entities": sorted(item.entities),
            "published_hour": item.published_at.isoformat(timespec="hours")
            if item.published_at else None,
            "root": safe_root_identity(item),
        }
        for item in ordered
    ]
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
```

同文件定义安全根标识、单条候选上下文和最终判定：

```python
def safe_root_identity(item: ClusterItem) -> str | None:
    for value in (item.original_url, item.canonical_url):
        if not value:
            continue
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.hostname.casefold()}{port}{parsed.path or '/'}"[:1_000]
    return None


def pair_candidate(item: ClusterItem) -> CandidateCluster:
    return CandidateCluster(
        candidate_key=f"pair-item:{item.raw_item_id}",
        title=item.title,
        items=(item,),
        raw_item_ids=(item.raw_item_id,),
        occurred_at=item.published_at,
    )


def finalize_pair_decision(
    rule: PairRuleDecision,
    semantic: PairSemanticDecision | None,
    input_fingerprint: str,
) -> PairFinalDecision:
    if rule.kind == PairDecisionKind.DIRECT_MERGE:
        final = "merge"
    elif rule.kind == PairDecisionKind.DIRECT_SEPARATE:
        final = "separate"
    elif (
        rule.structural_anchor
        and semantic is not None
        and semantic.origin == "model"
        and semantic.same_event
        and semantic.confidence >= 0.85
    ):
        final = "merge"
    else:
        final = "separate"
    return PairFinalDecision(
        left_raw_item_id=rule.left_raw_item_id,
        right_raw_item_id=rule.right_raw_item_id,
        input_fingerprint=input_fingerprint,
        rule_score=rule.score,
        rule_reasons=rule.reasons,
        decision=final,
        model_same_event=semantic.same_event if semantic else None,
        model_confidence=semantic.confidence if semantic else None,
    )
```

- [ ] **Step 4: 接入 MiniMax、缓存、短事务和并发**

Pipeline 先读取现有 `event_pair_decisions`，只对未命中的边界候选调用
`EventMiniMaxAdapter.compare_candidate_pair(pair_candidate(left), pair_candidate(right))`。每个调用使用独立的
`runs: list[EventModelRun]` sink 收集全部尝试；调用结束后用一个短事务写入候选对决定，并通过
`record_pair_model_run()` 关联全部尝试。HTTP 期间不得持有 Session。任一模型尝试无法持久化时抛出
`EventModelAuditError`，Operation 可重试且不会发布缺少审计的事件。并发上限复用
`event_model_max_concurrency`，硬上限仍为 2。

直接合并、直接分开和模型边界三类候选对都必须写入 `event_pair_decisions`；只有模型边界且缓存未命中时才产生
`event_model_runs`。缓存命中必须跳过模型调用并增加 Operation 的 `pair_cache_hit_count`。

`cluster_candidates()` 接收最终决定映射，只 union `decision == "merge"` 的候选对，并把原因写入候选元数据：

```python
metadata = {
    "_core_identity": _core_identity(members),
    "pair_decision_ids": sorted(pair_decision_ids),
    "merge_origins": sorted(merge_origins),
}
```

Operation 结果增加规则直接合并、模型辅助合并、分开、无法判断、缓存命中和模型错误计数。

- [ ] **Step 5: 验证并提交 Milestone 3**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/events/test_pairing.py tests/events/test_clustering.py tests/events/test_minimax.py tests/events/test_pipeline.py tests/events/test_pipeline_provenance.py -q
.\.venv\Scripts\ruff.exe check src/newsradar/events/pairing.py src/newsradar/events/clustering.py src/newsradar/events/minimax.py src/newsradar/events/pipeline.py src/newsradar/events/repository.py
git diff --check
git add src/newsradar/events/pairing.py src/newsradar/events/clustering.py src/newsradar/events/minimax.py src/newsradar/events/pipeline.py src/newsradar/events/repository.py tests/events/test_pairing.py tests/events/test_clustering.py tests/events/test_minimax.py tests/events/test_pipeline.py tests/events/test_pipeline_provenance.py
git commit -m "feat: cluster events with audited model boundaries"
```

---

## Milestone 4：热点分层、排名与重点中文增强

**Files:**

- Create: `src/newsradar/events/ranking.py`
- Modify: `src/newsradar/events/schema.py`
- Modify: `src/newsradar/events/scoring.py`
- Modify: `src/newsradar/events/publishing.py`
- Modify: `src/newsradar/events/pipeline.py`
- Modify: `src/newsradar/events/repository.py`
- Modify: `src/newsradar/events/runtime.py`
- Create: `tests/events/test_ranking.py`
- Modify: `tests/events/test_scoring.py`
- Modify: `tests/events/test_publishing.py`
- Modify: `tests/events/test_pipeline.py`
- Modify: `tests/events/test_runtime.py`

**Interfaces:**

- Produces: `rank_event(score: ScoreBreakdown) -> float`。
- Produces: `decide_event_tier(candidate, score, evidence) -> TierDecision`。
- Extends: `PublishedEvent` 包含 `display_tier` 和 `rank_score`。

- [ ] **Step 1: 写分层和排名失败测试**

必须覆盖官方单根热点、双专业媒体热点、单专业媒体线索、社交/社区线索、预印本线索、拒绝事件审计层。

```python
def test_rank_formula_uses_only_deterministic_snapshot() -> None:
    score = score_breakdown(
        credibility=90,
        importance=80,
        recency=70,
        source_coverage=60,
        engagement_velocity=50,
    )
    assert rank_event(score) == 76.5


def test_official_single_root_can_be_hotspot() -> None:
    decision = decide_event_tier(
        official_candidate(),
        score_breakdown(ai_relevance=90, credibility=90),
        (official_evidence(independent=True),),
    )
    assert decision.tier == EventTier.HOTSPOT


def test_preprint_stays_signal_without_independent_confirmation() -> None:
    decision = decide_event_tier(
        preprint_candidate(),
        score_breakdown(ai_relevance=90),
        (research_evidence(),),
    )
    assert decision.tier == EventTier.SIGNAL
    assert "preprint_not_peer_reviewed" in decision.reasons
```

- [ ] **Step 2: 实现纯排名与分层函数**

`ranking.py`：

```python
def rank_event(score: ScoreBreakdown) -> float:
    value = (
        0.30 * score.credibility
        + 0.25 * score.importance
        + 0.20 * score.recency
        + 0.15 * score.source_coverage
        + 0.10 * score.engagement_velocity
    )
    return round(max(0.0, min(100.0, value)), 1)
```

`decide_event_tier()` 首先排除 `rejected`、AI 相关性低于 70、缺少明确动作或版本不完整的事件；然后应用官方单根、
双专业媒体和研究/社交限制。原因代码必须稳定且可翻译。

- [ ] **Step 3: 持久化版本快照和当前物化字段**

`PublishedEvent` 增加：

```python
display_tier: EventTier = EventTier.SIGNAL
rank_score: float = Field(default=0, ge=0, le=100)
```

`EventPublisher.publish_snapshot()` 在规则评分后计算 TierDecision。`publish_complete_event()` 必须先写完整
EventVersion/Score/ModelRun，再一次性切换：

```python
record.display_tier = event.display_tier.value
record.rank_score = event.rank_score
record.current_version_number = next_version
```

版本 payload 的 `publication` 固定包含 `tier`、`rank_score` 和 `reasons`。

- [ ] **Step 4: 只自动增强热点和高价值线索**

Pipeline 在模型调用前先计算规则评分和 TierDecision：`hotspot` 全部自动增强，`signal` 仅在
`rank_score >= 60` 时自动增强，其他候选使用规则回退但不写 `no_api_key` 模型记录，因为它们没有发起模型任务。
人工“补充摘要”保持现有行为。

同一事件、提示版本、输入指纹已有成功增强时复用当前模型结果；事件成员或重要事实发生变化时产生新增强记录。

- [ ] **Step 5: 验证并提交 Milestone 4**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/events/test_ranking.py tests/events/test_scoring.py tests/events/test_publishing.py tests/events/test_pipeline.py tests/events/test_runtime.py tests/acceptance/test_event_model_degradation.py tests/acceptance/test_event_postgres_contention.py -q
.\.venv\Scripts\ruff.exe check src/newsradar/events
git diff --check
git add src/newsradar/events tests/events/test_ranking.py tests/events/test_scoring.py tests/events/test_publishing.py tests/events/test_pipeline.py tests/events/test_runtime.py tests/acceptance/test_event_model_degradation.py tests/acceptance/test_event_postgres_contention.py
git commit -m "feat: publish ranked hotspot and signal tiers"
```

---

## Milestone 5：中文热点首页、分类栏目与可解释详情

**Files:**

- Modify: `src/newsradar/web/event_queries.py`
- Modify: `src/newsradar/web/capability_queries.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/i18n.py`
- Modify: `src/newsradar/web/templates/events_home.html`
- Modify: `src/newsradar/web/templates/events.html`
- Modify: `src/newsradar/web/templates/event_detail.html`
- Modify: `src/newsradar/web/static/style.css`
- Modify: `tests/web/test_event_queries.py`
- Modify: `tests/web/test_event_routes.py`
- Modify: `tests/web/test_event_quality_pages.py`
- Modify: `tests/web/test_capability_queries.py`

**Interfaces:**

- Extends: `EventRow` 包含 `display_tier`、`rank_score`、`tier_reasons`。
- Produces: `EventSection(title: str, category: str, events: tuple[EventRow, ...])`。
- Extends: `EventHomeView` 包含 `hotspots`、`sections`、`signal_count`、`audit_count`。

`EventSection` 使用与现有 ViewModel 一致的冻结 dataclass：

```python
@dataclass(frozen=True)
class EventSection:
    title: str
    category: str
    events: tuple[EventRow, ...]
```

- [ ] **Step 1: 写首页、栏目和详情失败测试**

```python
def test_home_returns_ranked_hotspots_and_category_sections(db_session) -> None:
    product = seed_event(db_session, tier="hotspot", category="product_model", rank=90)
    research = seed_event(db_session, tier="hotspot", category="research", rank=75)
    seed_event(db_session, tier="signal", category="product_model", rank=99)
    view = EventQueryService(db_session).home(now=NOW)
    assert [row.event_id for row in view.hotspots] == [product.id, research.id]
    assert {section.category for section in view.sections} == {"product_model", "research"}


def test_model_latency_is_rendered_as_readable_duration(client) -> None:
    response = client.get("/events/274")
    assert "22.5 秒" in response.text
    assert "22538.233499974012 毫秒" not in response.text
```

同时断言 `audit_only` 和 `legacy` 不出现在首页，线索页不与热点混排，页面不泄漏敏感字段。

- [ ] **Step 2: 实现集合查询和分类保留位**

查询按 `visibility=current`、`display_tier=hotspot`、完整版本过滤，使用数据库字段 `rank_score DESC, occurred_at DESC, id DESC`。
取最多 20 条；当合格集合包含某分类时，综合热点为该分类保留最多两条，其余按全局排名填充，不用低质量事件补位。

禁止逐事件 N+1 查询；评分、版本和成员计数使用集合查询或现有快照查询。

- [ ] **Step 3: 实现中文首页和列表**

首页顺序固定为：运行概览、综合热点、四个分类栏目、新兴线索入口、来源能力入口。卡片显示中文标题、摘要、关注理由、
确认标签、独立证据根、分类、rank、可信度、热度和模型/回退状态。

`/events?tier=hotspot` 和 `/events?tier=signal` 使用明确中文筛选；`visibility=legacy` 保持历史入口。

- [ ] **Step 4: 实现可解释详情和易读耗时**

详情页按官方、专业媒体、研究、社区、社交、聚合顺序展示证据。加入“合并依据”和“确认依据”区块，读取版本快照中的
稳定原因代码。耗时格式函数固定为：

```python
def format_duration_ms(value: float | None) -> str:
    if value is None or value < 0:
        return "未知"
    if value < 1_000:
        return f"{round(value)} 毫秒"
    return f"{value / 1_000:.1f} 秒"
```

所有外部 URL 继续经过现有安全展示函数；错误原文和提示全文不进入模板。

- [ ] **Step 5: 验证并提交 Milestone 5**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/web/test_event_queries.py tests/web/test_event_routes.py tests/web/test_event_quality_pages.py tests/web/test_capability_queries.py -q
.\.venv\Scripts\ruff.exe check src/newsradar/web
git diff --check
git add src/newsradar/web tests/web
git commit -m "feat: present ranked event intelligence in Chinese"
```

---

## Milestone 6：质量报告、真实数据验收与最终审查

**Files:**

- Modify: `src/newsradar/events/reporting.py`
- Modify: `src/newsradar/cli.py`
- Modify: `tests/events/test_reporting.py`
- Modify: `tests/test_cli.py`
- Create: `tests/acceptance/test_event_quality_v2_1.py`
- Create: `tests/fixtures/events/pair_labels_v2_1.yaml`
- Generate: `reports/event-quality-v2-1.md`
- Modify: `README.md`

**Interfaces:**

- Extends: `newsradar events quality-report --window-hours 72 --output <path>`。
- Produces: v2.1 热点、线索、审计、候选对、模型和人工标注指标。

- [ ] **Step 1: 建立人工标注回归集和失败测试**

`pair_labels_v2_1.yaml` 固定至少 50 个正例和 50 个反例，每项包含本地 fixture ID、预期结论和中文理由，不依赖实时网络。
测试计算：正例召回率不低于 85%，反例误合并数必须为 0。

```python
assert positive_merged / positive_total >= 0.85
assert negative_merged == 0
```

- [ ] **Step 2: 扩展中文报告和 CLI**

报告必须包含：

- 72 小时 RawItem 总数、相关性覆盖和新闻价值覆盖；
- 热点、线索、审计数量；
- 单成员与多成员事件分布；
- 独立证据根分布；
- 规则直接合并、模型辅助合并、分开、无法判断和缓存命中；
- MiniMax 成功、回退、错误码和 token 汇总；
- 首页前 20 条人工抽检结论；
- 剩余问题与下一步建议。

CLI 只读数据库并写用户指定报告，不触发抓取、事件构建或模型调用。

- [ ] **Step 3: 运行完整自动化验证**

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

预期：全部测试通过，仅允许项目已有且已知的依赖弃用警告。

- [ ] **Step 4: 升级本地 PostgreSQL 并执行一次真实 72 小时构建**

从用户授权的未跟踪 `.env` 只注入所需环境变量，不打印值：

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\newsradar.exe db status
.\.venv\Scripts\newsradar.exe events build --hours 72 --wait
```

记录 Operation ID，核对：Worker 心跳、检查点、最终状态、处理恒等式、候选对统计、模型统计和安全错误码。

- [ ] **Step 5: 生成报告并进行网页验收**

```powershell
.\.venv\Scripts\newsradar.exe events quality-report --window-hours 72 --output reports/event-quality-v2-1.md
```

在 `http://127.0.0.1:8766/`、`/events?tier=hotspot`、`/events?tier=signal`、一个多源热点详情、一个研究线索详情、
`/operations/<id>` 和能力总览页完成浏览器验收。核对首页前 20 条准确率不低于 90%，并验证网页补充摘要、重新聚类、
取消和失败定位链路。

- [ ] **Step 6: 安全审查、代码审查和最终提交**

检查 Git 差异、数据库模型审计字段、日志、报告和 HTML，不得出现密钥值、连接串、Cookie、Authorization、提示全文或敏感查询参数。
修复所有 Critical/Important 审查问题后重新执行完整测试。

```powershell
git add src/newsradar/events/reporting.py src/newsradar/cli.py tests/events/test_reporting.py tests/test_cli.py tests/acceptance/test_event_quality_v2_1.py tests/fixtures/events/pair_labels_v2_1.yaml reports/event-quality-v2-1.md README.md
git commit -m "docs: record event quality v2.1 acceptance"
```

## 最终完成标准

- 最近 72 小时 RawItem 的相关性和新闻价值处理覆盖率均为 100%。
- 50 个以上正例对的合并召回率不低于 85%，50 个以上反例对无误合并。
- 同一事实的官网、媒体、聚合和社交样本能够聚合到一个事件并保留不同证据角色。
- 首页只展示合格 `hotspot`，最多 20 条，人工抽检准确率不低于 90%。
- `signal` 明确展示证据不足或未经同行评审，不与热点混排。
- `audit_only` 与旧数据仍可审计，但不进入主要阅读流。
- 至少一个热点和一个高价值线索完成真实 MiniMax 中文增强。
- MiniMax 完全不可用时，同一批事件仍能完成规则发布。
- Worker 的重试、取消、心跳、租约恢复和单候选故障隔离通过验证。
- 中文网页和报告能够解释合并、确认、分层、排名和模型降级。
- 完整测试、ruff、差异检查、安全扫描和最终代码审查全部通过。
- 合并时不覆盖 `main` 的用户报告，不删除既有本地运行工作树，不强制推送。
