# Event Intelligence v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 RawItem、Operation、Worker 和中文来源感知台之上，构建过去 24 小时 AI/技术产品与研究热点的可追溯事件层和中文网页。

**Architecture:** 新建 `newsradar.events` 领域包，把相关性、实体、聚类、证据、评分、发布和 MiniMax 增强拆成可独立测试的组件。事件处理继续使用现有持久化 Operation 队列和 Worker，通过操作路由器选择 Fetch 或 Event handler；网页只读取完整发布版本并只入队受控操作，不执行网络或模型工作。

**Tech Stack:** Python 3.12、SQLAlchemy 2、Alembic、PostgreSQL、Pydantic 2、FastAPI、Jinja2、Typer、HTTPX、pytest、pytest-asyncio、Ruff、MiniMax API。

## Global Constraints

- 开始实施时必须使用 `superpowers:using-git-worktrees` 创建隔离工作树和 `codex/event-intelligence-v1` 分支，不在 `main` 直接开发。
- 复用现有 Provider、Target、RawItem、Operation、Worker、Web 安全令牌、审计和日志体系，不新建第二套队列或抓取系统。
- 范围限定为全球 AI/技术产品与研究热点；不开发推荐、推送、日报、后台定时调度器和泛科技新闻。
- 首页以过去 24 小时 10–20 个重点事件为目标；数据不足时不以低质量内容凑数。
- 正式事件至少包含一条 `official`、`research` 或 `professional_media` 证据；纯 `community`/`social` 线索只进入 `/emerging`。
- 热度、可信度和重要度分别保存并解释；聚合转载和共同引用不得重复计算独立证据。
- MiniMax 只增强候选语义判断、实体、中文标题、短说明和分歧解释，不决定来源合规、事实确认或最终发布门槛。
- 默认 MiniMax 快速模型为 `MiniMax-M2.7-highspeed`，复杂分歧解释才使用 `MiniMax-M3`。
- MiniMax 完全不可用时，规则管线和网页仍须工作；网页不得等待后台任务或显示无限加载。
- 网络或模型调用期间不得持有数据库事务；同一事件使用事件级租约，不同事件可并发。
- API Key 不进入数据库业务数据、YAML、日志、异常文本、模板或诊断包。
- 每个里程碑按 TDD 执行，完成后单独提交并进行一次范围与回归审查。

## File Structure

### 新建领域文件

- `src/newsradar/events/schema.py`：事件枚举、Pydantic 输入输出和评分结构。
- `src/newsradar/events/repository.py`：事件、候选、成员、实体、版本、评分和处理幂等持久化。
- `src/newsradar/events/relevance.py`：AI 相关性规则与可读原因。
- `src/newsradar/events/entities.py`：确定性实体提取、别名规范化和实体键。
- `src/newsradar/events/clustering.py`：候选对生成、规则相似度和候选簇形成。
- `src/newsradar/events/evidence.py`：来源角色、根证据和独立证据判定。
- `src/newsradar/events/scoring.py`：重要度、可信度、热度分项计算。
- `src/newsradar/events/publishing.py`：证据门槛、事件状态和原子版本发布。
- `src/newsradar/events/minimax.py`：事件专用结构化 MiniMax 适配器和规则回退。
- `src/newsradar/events/pipeline.py`：阶段编排、幂等键和下游 Operation 入队。
- `src/newsradar/events/runtime.py`：事件 Operation handler 和生产 Session 边界。
- `src/newsradar/operations/router.py`：按 `OperationType` 分派现有 Fetch 和事件 handler。
- `src/newsradar/web/event_queries.py`：首页、事件列表、详情和升温事件只读查询。
- `src/newsradar/web/templates/events_home.html`：过去 24 小时中文重点首页。
- `src/newsradar/web/templates/events.html`：事件列表和筛选。
- `src/newsradar/web/templates/event_detail.html`：事件时间线、证据、评分和故障降级。
- `src/newsradar/web/templates/emerging.html`：纯社交/社区升温线索。
- `migrations/versions/20260712_0007_event_intelligence_v1.py`：事件层数据库对象。
- `reports/event-intelligence-v1-acceptance.md`：三轮真实数据和浏览器验收证据。

### 修改现有文件

- `src/newsradar/db/models.py`：增加事件 ORM 记录。
- `src/newsradar/operations/schema.py`：增加事件操作类型。
- `src/newsradar/operations/commands.py`：增加统一事件入队和人工操作命令。
- `src/newsradar/operations/logging.py`：确认事件/模型错误继续走统一脱敏。
- `src/newsradar/cli.py`：Worker 使用操作路由器，并增加事件生成 CLI。
- `src/newsradar/settings.py`：增加事件窗口、阈值、模型超时和并发配置。
- `src/newsradar/ai/minimax.py`：复用结构化调用内核并支持事件适配器需要的模型选择与用量记录。
- `src/newsradar/web/app.py`：增加事件路由，把 `/` 改为事件首页，把原总览迁到 `/sources`。
- `src/newsradar/web/templates/base.html`：增加“今日重点、正在升温、事件、来源与运行”中文导航。
- `src/newsradar/web/templates/dashboard.html`：继续作为 `/sources` 来源感知台。
- `src/newsradar/web/templates/operations.html`：增加事件任务筛选和阶段信息。
- `src/newsradar/web/templates/operation_detail.html`：增加 Event/RawItem 关联下钻。
- `src/newsradar/web/static/styles.css`：增加事件卡片、证据标签、评分和降级状态样式。

---

### Task 1: Event persistence and migration

**Files:**
- Create: `migrations/versions/20260712_0007_event_intelligence_v1.py`
- Create: `src/newsradar/events/__init__.py`
- Create: `src/newsradar/events/schema.py`
- Create: `src/newsradar/events/repository.py`
- Modify: `src/newsradar/db/models.py`
- Test: `tests/events/test_schema.py`
- Test: `tests/events/test_repository.py`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Produces: all cross-task value types in `events/schema.py`: `EventStatus`, `EvidenceRole`, `EventCategory`, `EntityType`, `ProcessingStage`, `RawItemText`, `RelevanceDecision`, `ExtractedEntity`, `ClusterItem`, `ClusterDecision`, `CandidateCluster`, `EvidenceAssessment`, `EventScoreInput`, `ScoreBreakdown`, `PublicationDecision`, `EventEnrichment`, and `PublishedEvent`.
- Produces: `EventRepository.record_stage(...)`, `upsert_candidate(...)`, `replace_candidate_items(...)`, `create_or_update_event(...)`, `publish_version(...)`, `claim_event(...)`, `release_event(...)`.
- Consumes: existing `RawItemRecord`, `SourceDefinitionRecord`, `OperationRunRecord`, `ModelUsageRecord`.

- [ ] **Step 1: Add failing schema and repository tests**

```python
def test_score_breakdown_rejects_out_of_range_values():
    with pytest.raises(ValidationError):
        ScoreBreakdown(
            ai_relevance=101,
            source_coverage=0,
            source_authority=0,
            recency=0,
            engagement_velocity=0,
            novelty=0,
            importance=101,
            credibility=0,
            heat=0,
            reasons=[],
        )


def test_stage_record_is_idempotent(db_session, raw_item):
    repository = EventRepository(db_session)
    first = repository.record_stage(raw_item.id, ProcessingStage.RELEVANCE, "relevance-v1")
    second = repository.record_stage(raw_item.id, ProcessingStage.RELEVANCE, "relevance-v1")
    db_session.commit()
    assert first.id == second.id
```

- [ ] **Step 2: Run the focused tests and verify the red state**

Run: `uv run pytest tests/events/test_schema.py tests/events/test_repository.py -q`

Expected: collection fails because `newsradar.events` and event tables do not exist.

- [ ] **Step 3: Add the domain enums, ORM records, migration and repository**

Create these stable public types in `schema.py`:

```python
class EventStatus(StrEnum):
    EMERGING = "emerging"
    CONFIRMED = "confirmed"
    DEVELOPING = "developing"
    DISPUTED = "disputed"
    STALE = "stale"
    REJECTED = "rejected"


class EvidenceRole(StrEnum):
    OFFICIAL = "official"
    PROFESSIONAL_MEDIA = "professional_media"
    RESEARCH = "research"
    COMMUNITY = "community"
    SOCIAL = "social"
    AGGREGATOR = "aggregator"


class ProcessingStage(StrEnum):
    RELEVANCE = "relevance"
    ENTITIES = "entities"
    CLUSTER = "cluster"
    ENRICH = "enrich"
    SCORE = "score"
    PUBLISH = "publish"


class EventCategory(StrEnum):
    PRODUCT_MODEL = "product_model"
    RESEARCH = "research"
    DEVELOPER_TOOL = "developer_tool"
    COMPANY = "company"


class EntityType(StrEnum):
    ORGANIZATION = "organization"
    PERSON = "person"
    PRODUCT = "product"
    MODEL = "model"
    PAPER = "paper"
    DATASET = "dataset"
    PROJECT = "project"


class RawItemText(BaseModel):
    raw_item_id: int | None = None
    title: str = ""
    summary: str = ""
    content: str = ""
    item_kind: str | None = None
    publisher_name: str | None = None


class RelevanceDecision(BaseModel):
    is_relevant: bool
    score: int = Field(ge=0, le=100)
    topics: tuple[str, ...]
    reasons: tuple[str, ...]


class EventEnrichment(BaseModel):
    zh_title: str
    zh_summary: str
    why_it_matters: str
    limitations: tuple[str, ...] = ()
    origin: Literal["model", "previous_version", "rule_fallback"]
    confidence: float = Field(ge=0, le=1)
```

Migration `20260712_0007` creates `raw_item_processing`, `event_candidates`, `event_candidate_items`, `events`, `event_versions`, `event_items`, `entities`, `event_entities`, `event_scores`, and `event_model_runs`. Add unique constraints for `(raw_item_id, stage, algorithm_version)`, `(candidate_key, algorithm_version)`, `(event_id, version_number)`, `(event_id, raw_item_id, added_version_number)`, and `(canonical_key, entity_type)`. Add indexes for event status/time, score ranking, candidate state and active membership. Downgrade drops only these new objects in reverse FK order.

`EventRepository.claim_event(event_id, operation_id, lease_until)` must use a conditional `UPDATE` that succeeds only when no live event lease exists; network/model work runs after the transaction commits.

- [ ] **Step 4: Verify migration round-trip, repository idempotency and existing compatibility**

Run:

```powershell
uv run pytest tests/events/test_schema.py tests/events/test_repository.py tests/test_migrations.py -q
uv run alembic upgrade head
uv run alembic downgrade 20260712_0006
uv run alembic upgrade head
```

Expected: all tests pass; final Alembic revision is `20260712_0007 (head)`; existing RawItem and Operation rows remain unchanged.

- [ ] **Step 5: Commit the persistence milestone**

```powershell
git add migrations/versions/20260712_0007_event_intelligence_v1.py src/newsradar/db/models.py src/newsradar/events tests/events tests/test_migrations.py
git commit -m "feat: add event intelligence persistence"
```

### Task 2: Deterministic relevance and entity extraction

**Files:**
- Create: `src/newsradar/events/relevance.py`
- Create: `src/newsradar/events/entities.py`
- Test: `tests/events/test_relevance.py`
- Test: `tests/events/test_entities.py`

**Interfaces:**
- Consumes: normalized `RawItemRecord.title`, `summary`, `content`, `item_kind`, `publisher_name` and source topics.
- Produces: `RelevanceDecision(is_relevant: bool, score: int, topics: tuple[str, ...], reasons: tuple[str, ...])`.
- Produces: `extract_entities(item: RawItemText) -> tuple[ExtractedEntity, ...]` and `canonical_entity_key(name: str, entity_type: EntityType) -> str`.

- [ ] **Step 1: Add fixed positive, negative and boundary samples**

```python
@pytest.mark.parametrize("title", [
    "New multimodal model API released",
    "Agent framework adds tool calling",
    "Benchmark evaluates long-context reasoning",
])
def test_ai_relevance_positive_samples(title):
    assert evaluate_relevance(RawItemText(title=title, summary="", content="")).is_relevant


def test_ai_relevance_rejects_generic_business_news():
    result = evaluate_relevance(
        RawItemText(title="Company reports quarterly revenue", summary="", content="")
    )
    assert result.is_relevant is False
    assert "no_ai_signal" in result.reasons


def test_entity_aliases_share_a_canonical_key():
    assert canonical_entity_key("Hugging Face", EntityType.ORGANIZATION) == canonical_entity_key(
        "huggingface", EntityType.ORGANIZATION
    )
```

- [ ] **Step 2: Run focused tests and verify missing implementation failures**

Run: `uv run pytest tests/events/test_relevance.py tests/events/test_entities.py -q`

Expected: tests fail because deterministic classifiers are not implemented.

- [ ] **Step 3: Implement versioned rules without network or model calls**

Use explicit, testable rule groups:

```python
RELEVANCE_RULE_VERSION = "relevance-v1"
AI_TERMS = {"llm", "model", "inference", "agent", "multimodal", "benchmark", "api"}
RESEARCH_TERMS = {"paper", "arxiv", "dataset", "evaluation", "benchmark"}
PRODUCT_TERMS = {"release", "launch", "available", "api", "sdk", "preview"}


def evaluate_relevance(item: RawItemText) -> RelevanceDecision:
    text = normalize_text(" ".join(filter(None, (item.title, item.summary, item.content))))
    matched = sorted(term for term in AI_TERMS if term in text)
    score = min(100, len(matched) * 25)
    return RelevanceDecision(
        is_relevant=score >= 25,
        score=score,
        topics=tuple(infer_rule_topics(text)),
        reasons=tuple(f"matched:{term}" for term in matched) or ("no_ai_signal",),
    )
```

Entity extraction must preserve the original mention, normalize aliases, avoid treating common AI terms as organizations, and return stable ordering for deterministic replay.

- [ ] **Step 4: Run focused tests and deterministic replay**

Run: `uv run pytest tests/events/test_relevance.py tests/events/test_entities.py -q`

Expected: all samples pass; running the same sample twice yields byte-equivalent serialized decisions.

- [ ] **Step 5: Commit the rule milestone**

```powershell
git add src/newsradar/events/relevance.py src/newsradar/events/entities.py tests/events/test_relevance.py tests/events/test_entities.py
git commit -m "feat: classify ai relevance and entities"
```

### Task 3: Candidate clustering and evidence attribution

**Files:**
- Create: `src/newsradar/events/clustering.py`
- Create: `src/newsradar/events/evidence.py`
- Test: `tests/events/test_clustering.py`
- Test: `tests/events/test_evidence.py`

**Interfaces:**
- Consumes: relevant RawItems, normalized URLs, title fingerprints, entities, source nature/roles/provider category, publish time and discovery/origin URLs.
- Produces: `ClusterDecision(matched: bool, score: float, reasons: tuple[str, ...])`.
- Produces: `CandidateCluster(candidate_key: str, raw_item_ids: tuple[int, ...], reasons: tuple[str, ...])`.
- Produces: `EvidenceAssessment(role: EvidenceRole, root_evidence_key: str, independent: bool, limitations: tuple[str, ...])`.

- [ ] **Step 1: Add merge, non-merge and evidence-root tests**

```python
def test_same_canonical_url_is_a_strong_match():
    decision = compare_items(item(canonical_url="https://example.com/a"), item(canonical_url="https://example.com/a"))
    assert decision.matched
    assert "same_canonical_url" in decision.reasons


def test_same_company_different_actions_do_not_merge():
    left = item(title="Acme launches Model X", entities=("acme", "model-x"))
    right = item(title="Acme acquires DataCo", entities=("acme", "dataco"))
    assert compare_items(left, right).matched is False


def test_aggregator_and_original_share_one_root_evidence():
    original = evidence_item(canonical_url="https://publisher.test/story")
    aggregate = evidence_item(
        canonical_url="https://news.google.test/item",
        original_url="https://publisher.test/story",
    )
    assessments = assess_evidence((original, aggregate))
    assert len({row.root_evidence_key for row in assessments}) == 1
```

- [ ] **Step 2: Run focused tests and verify the red state**

Run: `uv run pytest tests/events/test_clustering.py tests/events/test_evidence.py -q`

Expected: tests fail because clustering and evidence attribution do not exist.

- [ ] **Step 3: Implement bounded candidate generation and union grouping**

Only compare items within the configured 48-hour candidate window and require at least one blocking key: canonical URL hash, title fingerprint, shared non-generic entity, repository/paper ID, or common original URL. Compute rule score from URL, title, entity/action and time evidence; do not compare every RawItem pair globally.

```python
CLUSTER_RULE_VERSION = "cluster-v1"


def compare_items(left: ClusterItem, right: ClusterItem) -> ClusterDecision:
    reasons: list[str] = []
    score = 0.0
    if left.canonical_url_hash and left.canonical_url_hash == right.canonical_url_hash:
        reasons.append("same_canonical_url")
        score += 1.0
    if left.title_fingerprint and left.title_fingerprint == right.title_fingerprint:
        reasons.append("same_title_fingerprint")
        score += 0.8
    score += entity_action_similarity(left, right, reasons)
    score += time_similarity(left, right, reasons)
    return ClusterDecision(matched=score >= 1.0, score=min(score, 1.0), reasons=tuple(reasons))
```

Evidence role derives from audited source metadata, never from MiniMax. `root_evidence_key` prefers resolved original URL, then canonical URL, then publisher plus title fingerprint. Research preprints receive limitation `not_peer_reviewed` when source/item metadata indicates arXiv or preprint.

- [ ] **Step 4: Run clustering tests including false-positive protection**

Run: `uv run pytest tests/events/test_clustering.py tests/events/test_evidence.py tests/ingestion/test_attribution.py -q`

Expected: all tests pass; different actions from the same company stay separate; aggregator copies do not increase independent evidence count.

- [ ] **Step 5: Commit the clustering milestone**

```powershell
git add src/newsradar/events/clustering.py src/newsradar/events/evidence.py tests/events/test_clustering.py tests/events/test_evidence.py
git commit -m "feat: cluster event candidates and evidence"
```

### Task 4: Scoring, status and atomic publishing

**Files:**
- Create: `src/newsradar/events/scoring.py`
- Create: `src/newsradar/events/publishing.py`
- Modify: `src/newsradar/events/repository.py`
- Test: `tests/events/test_scoring.py`
- Test: `tests/events/test_publishing.py`

**Interfaces:**
- Consumes: `CandidateCluster`, `EvidenceAssessment`, engagement values, source authority and timestamps.
- Produces: `score_event(input: EventScoreInput) -> ScoreBreakdown`.
- Produces: `PublicationDecision(status: EventStatus, publish_to_top: bool, reasons: tuple[str, ...])`.
- Produces: `EventPublisher.publish(candidate_id: int, operation_id: int) -> PublishedEvent`.

- [ ] **Step 1: Add exact weight, threshold and atomic-read tests**

```python
def test_importance_uses_versioned_weights():
    score = score_event(full_score_input())
    assert score.importance == 92
    assert score.rule_version == "score-v1"


def test_social_only_candidate_is_emerging_not_confirmed():
    decision = decide_publication(candidate_with_roles(EvidenceRole.SOCIAL, EvidenceRole.COMMUNITY))
    assert decision.status is EventStatus.EMERGING
    assert decision.publish_to_top is False


def test_reader_sees_only_complete_version(db_session, candidate):
    publisher = EventPublisher(EventRepository(db_session))
    published = publisher.publish(candidate.id, operation_id=1)
    assert EventRepository(db_session).get_current_event(published.event_id).version_number == 1
```

- [ ] **Step 2: Run focused tests and verify failure before implementation**

Run: `uv run pytest tests/events/test_scoring.py tests/events/test_publishing.py -q`

Expected: missing scoring and publishing functions cause failures.

- [ ] **Step 3: Implement transparent scores and publication gate**

```python
IMPORTANCE_WEIGHTS = {
    "ai_relevance": 0.25,
    "source_coverage": 0.20,
    "source_authority": 0.20,
    "recency": 0.15,
    "engagement_velocity": 0.10,
    "novelty": 0.10,
}


def weighted_importance(parts: Mapping[str, int]) -> int:
    return round(sum(parts[name] * weight for name, weight in IMPORTANCE_WEIGHTS.items()))
```

Credibility must cap social/community-only candidates below the confirmation threshold. A candidate with an official source may be confirmed; two independent professional-media roots may also be confirmed. Conflicting assertions set `disputed`. Publishing writes EventVersion, EventItem memberships, EventScore and `events.current_version_number` in one short transaction after all computation is complete.

- [ ] **Step 4: Verify deterministic scoring and rollback safety**

Run: `uv run pytest tests/events/test_scoring.py tests/events/test_publishing.py tests/events/test_repository.py -q`

Expected: all tests pass; injected failure before current-version switch leaves the previous published version readable.

- [ ] **Step 5: Commit the scoring and publishing milestone**

```powershell
git add src/newsradar/events/scoring.py src/newsradar/events/publishing.py src/newsradar/events/repository.py tests/events/test_scoring.py tests/events/test_publishing.py
git commit -m "feat: score and publish evidence-backed events"
```

### Task 5: MiniMax event enrichment with hard fallback

**Files:**
- Create: `src/newsradar/events/minimax.py`
- Modify: `src/newsradar/ai/minimax.py`
- Modify: `src/newsradar/settings.py`
- Test: `tests/events/test_minimax.py`
- Modify: `tests/test_minimax.py`

**Interfaces:**
- Consumes: bounded untrusted candidate item excerpts and deterministic candidate facts.
- Produces: `EventEnrichment`, `PairSemanticDecision`, `EntitySuggestions`, `ConflictExplanation`.
- Produces: `EventMiniMaxAdapter.enrich_event(...)`, `compare_candidate_pair(...)`, `suggest_entities(...)`, `explain_conflict(...)`.
- Writes: `event_model_runs` and existing `model_usage` through a sink; never secrets or full environment data.

- [ ] **Step 1: Add success, invalid JSON, timeout, 429 and no-key tests**

```python
@pytest.mark.asyncio
async def test_no_key_returns_rule_fallback_without_http_call(settings_without_key, http):
    adapter = EventMiniMaxAdapter(settings_without_key, http)
    result = await adapter.enrich_event(candidate_context(), rule_fallback())
    assert result.origin == "rule_fallback"
    assert http.request_count == 0


@pytest.mark.asyncio
async def test_invalid_json_repairs_once_then_falls_back(adapter, respx_mock):
    route = respx_mock.post("https://api.minimax.io/v1/text/chatcompletion_v2").mock(
        side_effect=[Response(200, json=invalid_payload()), Response(200, json=invalid_payload())]
    )
    result = await adapter.enrich_event(candidate_context(), rule_fallback())
    assert route.call_count == 2
    assert result.origin == "rule_fallback"
```

- [ ] **Step 2: Run tests and verify event methods are absent**

Run: `uv run pytest tests/events/test_minimax.py tests/test_minimax.py -q`

Expected: tests fail because the event adapter and response schemas do not exist.

- [ ] **Step 3: Extract a reusable structured-call boundary and add event schemas**

Keep `UNTRUSTED_PREAMBLE`, `tools: []`, `tool_choice: none`, temperature `0.1`, one repair retry and Pydantic validation. Add settings:

```python
event_window_hours: int = 24
event_candidate_window_hours: int = 48
event_model_timeout_seconds: float = 45
event_model_max_concurrency: int = 2
event_top_limit: int = 20
```

`EventEnrichment` contains `zh_title`, `zh_summary`, `why_it_matters`, `limitations`, `origin`, and `confidence`. The adapter uses the fast model for pair comparison, entity suggestions and ordinary enrichment; `explain_conflict` alone uses the deep model. Persist only bounded error class/code after passing through existing `redact()`.

- [ ] **Step 4: Verify MiniMax is optional and never blocks rule output**

Run: `uv run pytest tests/events/test_minimax.py tests/test_minimax.py tests/operations/test_logging.py -q`

Expected: all tests pass; no-key, timeout, 429, 5xx and invalid structures return a valid rule fallback and record a bounded failure outcome.

- [ ] **Step 5: Commit the MiniMax milestone**

```powershell
git add src/newsradar/events/minimax.py src/newsradar/ai/minimax.py src/newsradar/settings.py tests/events/test_minimax.py tests/test_minimax.py
git commit -m "feat: add optional minimax event enrichment"
```

### Task 6: Event pipeline on the durable Worker

**Files:**
- Create: `src/newsradar/events/pipeline.py`
- Create: `src/newsradar/events/runtime.py`
- Create: `src/newsradar/operations/router.py`
- Modify: `src/newsradar/operations/schema.py`
- Modify: `src/newsradar/operations/commands.py`
- Modify: `src/newsradar/cli.py`
- Test: `tests/events/test_pipeline.py`
- Test: `tests/events/test_runtime.py`
- Test: `tests/operations/test_router.py`
- Modify: `tests/operations/test_commands.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/acceptance/test_nonblocking_web.py`
- Modify: `tests/acceptance/test_worker_recovery.py`

**Interfaces:**
- Adds operation types: `EVENT_PIPELINE`, `EVENT_RECLUSTER`, `EVENT_ENRICH`, `EVENT_MERGE`, `EVENT_SPLIT`, `EVENT_EXCLUDE`.
- Produces: `OperationRouter.register(operation_type, handler)` and `OperationRouter.__call__(lease, checkpoint)`.
- Produces: `OperationCommandService.enqueue_event_pipeline(window_hours, trigger)`, `enqueue_event_action(action, event_id, payload, trigger)`.
- Produces CLI: `newsradar events build --hours 24`, `newsradar events list`, `newsradar events show <event-id>`.

- [ ] **Step 1: Add router, nonblocking, idempotency, cancellation and recovery tests**

```python
def test_router_dispatches_fetch_and_event_handlers():
    router = OperationRouter({"fetch": fetch_handler, "event_pipeline": event_handler})
    assert router(lease(operation_type="event_pipeline"), checkpoint).status is OperationStatus.SUCCEEDED


def test_pipeline_replay_does_not_duplicate_versions(db_session, raw_items):
    pipeline = EventPipeline.production(db_session)
    first = pipeline.run(window_hours=24, operation_id=1, checkpoint=lambda _: None)
    second = pipeline.run(window_hours=24, operation_id=2, checkpoint=lambda _: None)
    assert second.created_event_versions == 0
    assert second.current_event_ids == first.current_event_ids
```

- [ ] **Step 2: Run focused operation tests and verify the red state**

Run: `uv run pytest tests/events/test_pipeline.py tests/events/test_runtime.py tests/operations/test_router.py tests/operations/test_commands.py tests/test_cli.py -q`

Expected: missing event Operation types, router and pipeline commands cause failures.

- [ ] **Step 3: Implement operation routing and short-stage orchestration**

The Worker continues to call one handler, but that handler becomes `OperationRouter`. `FetchOperationHandler` remains unchanged and registered for `fetch`. Event runtime creates and closes its own Session per bounded stage, releases transactions before MiniMax, checks cancellation between stages, renews the existing Operation lease through the existing monitor, and returns `OperationResult` with counts and event IDs.

```python
class OperationRouter:
    def __init__(self, handlers: Mapping[str, Handler]) -> None:
        self._handlers = dict(handlers)

    def __call__(self, lease: OperationLease, checkpoint: Callable[[str], None]) -> OperationResult:
        handler = self._handlers.get(lease.operation_type)
        if handler is None:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="unsupported_operation_type",
                error_message=f"No worker handler is registered for {lease.operation_type}",
                retryable=False,
            )
        return handler(lease, checkpoint)
```

`enqueue_event_pipeline` includes `window_hours`, `algorithm_versions`, `deadline_at` and an idempotency key derived from window end plus versions. Web and CLI only enqueue; the Worker performs processing.

- [ ] **Step 4: Verify Worker reliability and existing fetch compatibility**

Run:

```powershell
uv run pytest tests/events/test_pipeline.py tests/events/test_runtime.py tests/operations tests/acceptance/test_nonblocking_web.py tests/acceptance/test_worker_recovery.py tests/ingestion/test_service.py -q
```

Expected: event cancellation, retry, expired-lease recovery and replay pass; existing fetch operations still execute through the same Worker.

- [ ] **Step 5: Commit the Worker integration milestone**

```powershell
git add src/newsradar/events/pipeline.py src/newsradar/events/runtime.py src/newsradar/operations src/newsradar/cli.py tests/events/test_pipeline.py tests/events/test_runtime.py tests/operations tests/test_cli.py tests/acceptance
git commit -m "feat: run event pipeline on durable worker"
```

### Task 7: Chinese event web experience and audited actions

**Files:**
- Create: `src/newsradar/web/event_queries.py`
- Create: `src/newsradar/web/templates/events_home.html`
- Create: `src/newsradar/web/templates/events.html`
- Create: `src/newsradar/web/templates/event_detail.html`
- Create: `src/newsradar/web/templates/emerging.html`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/base.html`
- Modify: `src/newsradar/web/templates/dashboard.html`
- Modify: `src/newsradar/web/templates/operations.html`
- Modify: `src/newsradar/web/templates/operation_detail.html`
- Modify: `src/newsradar/web/static/styles.css`
- Test: `tests/web/test_event_queries.py`
- Test: `tests/web/test_event_routes.py`
- Modify: `tests/web/test_routes.py`
- Modify: `tests/web/test_security.py`

**Interfaces:**
- Produces: `EventQueryService.home(window_hours=24, limit=20) -> EventHomeView`.
- Produces: `EventQueryService.list_events(filters) -> EventPage`, `get_event(event_id) -> EventDetailView | None`, `list_emerging(...)`.
- Adds POST routes: `/events/build`, `/events/{id}/recluster`, `/events/{id}/enrich`, `/events/{id}/exclude`, `/events/merge`, `/events/{id}/split`.
- Consumes: existing `require_safe_action`, `OperationCommandService`, `OperationQueryService`, `build_system_health`.

- [ ] **Step 1: Add query, route, navigation, security and degradation tests**

```python
def test_home_shows_confirmed_events_and_not_social_only(client, confirmed_event, emerging_event):
    response = client.get("/")
    assert response.status_code == 200
    assert confirmed_event.zh_title in response.text
    assert emerging_event.zh_title not in response.text


def test_emerging_page_labels_unconfirmed_social_signal(client, emerging_event):
    response = client.get("/emerging")
    assert "仅线索" in response.text
    assert emerging_event.zh_title in response.text


def test_recluster_post_only_enqueues_operation(client, event_record, action_token):
    response = client.post(
        f"/events/{event_record.id}/recluster",
        data={"action_token": action_token},
        headers={"Origin": "http://127.0.0.1"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert queued_operation_type() == "event_recluster"
    assert no_model_or_network_call_was_made()
```

- [ ] **Step 2: Run focused web tests and verify missing pages**

Run: `uv run pytest tests/web/test_event_queries.py tests/web/test_event_routes.py tests/web/test_routes.py tests/web/test_security.py -q`

Expected: event queries, templates and routes are absent; `/` still renders the source dashboard.

- [ ] **Step 3: Implement read-only views and A-style templates**

`/` reads only complete versions in the last 24 hours, sorts by importance with stable tie-breakers, caps at 20, and displays fewer when evidence is insufficient. `/sources` renders the unchanged source dashboard. Event detail displays timelines, evidence roles, root/independence status, original links, score reasons, algorithm/model versions, and a nonblocking MiniMax degradation banner.

All write routes call `require_safe_action` and `OperationCommandService`; they never instantiate HTTPX or MiniMax clients. Merge and split payloads validate integer IDs, reject self-merge/empty membership, and record actor `web` in requested scope.

- [ ] **Step 4: Run web tests and a browser acceptance pass**

Run:

```powershell
uv run pytest tests/web -q
uv run newsradar serve
```

Browser acceptance at the configured loopback URL must verify: event home, confirmed/unconfirmed separation, event detail evidence, score explanation, source dashboard at `/sources`, operation enqueue/detail, MiniMax degraded banner, mobile width, and no indefinite loading state.

Expected: all web tests pass; actions create queued Operations; only Worker consumption changes event data.

- [ ] **Step 5: Commit the web milestone**

```powershell
git add src/newsradar/web src/newsradar/operations/commands.py tests/web
git commit -m "feat: add chinese event intelligence web"
```

### Task 8: Three-round real-data acceptance and final review

**Files:**
- Create: `tests/acceptance/test_event_web_worker_flow.py`
- Create: `tests/acceptance/test_event_postgres_contention.py`
- Create: `tests/acceptance/test_event_model_degradation.py`
- Create: `reports/event-intelligence-v1-acceptance.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: local PostgreSQL, existing RawItems, Web enqueue route, Worker router, EventQueryService and optional real MiniMax configuration.
- Produces: reproducible acceptance commands, three run IDs, event counts, category coverage, failure/degradation evidence and browser checklist.

- [ ] **Step 1: Add end-to-end acceptance tests before running real data**

```python
def test_web_enqueue_worker_publish_and_event_detail(postgres_engine, client):
    operation_id = enqueue_event_build(client, hours=24)
    run_worker_until_terminal(operation_id)
    operation = load_operation(operation_id)
    assert operation.status in {"succeeded", "partial"}
    event_id = operation.result_summary["published_event_ids"][0]
    detail = client.get(f"/events/{event_id}")
    assert detail.status_code == 200
    assert "证据与原文" in detail.text


def test_minimax_offline_does_not_block_publication(postgres_engine, settings_without_minimax):
    result = run_event_pipeline(settings_without_minimax)
    assert result.rule_events_published >= 1
    assert result.model_failures == 0
```

- [ ] **Step 2: Run the full automated gate**

Run:

```powershell
uv run alembic upgrade head
uv run pytest -q
uv run ruff check .
uv run alembic current
```

Expected: zero test failures, zero Ruff violations, Alembic current is `20260712_0007 (head)`.

- [ ] **Step 3: Run three real event builds and capture evidence**

Keep `uv run newsradar serve` running in terminal A. In terminal B, run the following pair three times and preserve the returned Operation IDs:

```powershell
uv run newsradar fetch --wait
uv run newsradar events build --hours 24 --wait
```

For each round record: RawItems considered, relevant items, candidates, published events, emerging events, confirmed events, disputed events, category counts, duplicate-root suppression count, MiniMax calls/fallbacks, duration, retries and failures. At least one round must run with `MINIMAX_API_KEY` unset to prove hard fallback. If the 24-hour dataset does not contain all four target categories, extend only the acceptance input window to 7 days and label that category-coverage check separately; do not change the product’s 24-hour homepage window.

- [ ] **Step 4: Complete browser and contention acceptance, then write the report**

Run:

```powershell
uv run pytest tests/acceptance/test_event_web_worker_flow.py tests/acceptance/test_event_postgres_contention.py tests/acceptance/test_event_model_degradation.py -q
uv run newsradar serve
```

`reports/event-intelligence-v1-acceptance.md` must include exact commit, migration revision, commands, run IDs, counts, representative event IDs, confirmed/emerging separation, original-link traceability, model-off evidence, lock/lease recovery evidence, browser routes checked, known gaps and screenshots or textual browser evidence. Do not include API keys, complete environment dumps or unredacted error URLs.

- [ ] **Step 5: Request code review, fix findings, rerun the complete gate and commit**

Use `superpowers:requesting-code-review`, review against `docs/superpowers/specs/2026-07-12-event-intelligence-v1-design.md`, then run:

```powershell
uv run pytest -q
uv run ruff check .
uv run alembic current
git diff --check
```

Expected: zero failures/violations, migration head `20260712_0007`, no whitespace errors, no unresolved high/medium review findings.

Commit:

```powershell
git add tests/acceptance reports/event-intelligence-v1-acceptance.md README.md
git commit -m "test: accept event intelligence v1"
```

After verification, use `superpowers:finishing-a-development-branch` to present merge/PR choices. Do not merge or push without the user’s explicit instruction.

## Milestone Review Gates

- Gate A after Tasks 1–2: migration, idempotency, relevance and entity rules are reviewable without clustering or UI.
- Gate B after Tasks 3–4: deterministic event formation, evidence roots, scoring and atomic publication are complete without MiniMax.
- Gate C after Tasks 5–6: MiniMax degradation and durable Worker execution are complete; existing fetch behavior remains compatible.
- Gate D after Task 7: Chinese event web and audited actions are browser-reviewable.
- Gate E after Task 8: three-round evidence, full regression, final code review and merge decision.
