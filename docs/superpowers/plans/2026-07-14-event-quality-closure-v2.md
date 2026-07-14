# Event Intelligence v2 事件质量收口实施计划

> **供自动化执行者使用：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实现。每个步骤使用复选框追踪。

**目标：** 在不删除旧事件和 RawItem 的前提下，把最近 72 小时原始信息稳定转换为少量、可信、可解释、中文优先的当前 AI/技术事件。

**架构：** 复用现有 PostgreSQL、Operation、Worker 和 Event Intelligence v1，在原有事件表上增加 current/legacy 可见性，在 RawItem 处理记录中保存 v2 相关性结论。规则负责过滤、证据、聚类、评分和发布；MiniMax 只对已通过规则的候选做中文编辑增强，并能完全降级。

**技术栈：** Python 3.12、SQLAlchemy 2、Alembic、Pydantic 2、Typer、HTTPX、FastAPI/Jinja2、PostgreSQL、pytest、MiniMax API。

## 全局约束

- 不删除或覆盖现有 72 个事件、75 个版本、81 个成员关系和 75 个评分快照。
- 不修改来源 YAML、来源合规结论或来源启用状态。
- 所有实现必须测试先行；每项行为先看到预期失败，再写最小实现。
- v2 算法版本固定为 `relevance-v2`、`entities-v2`、`cluster-v2`、`score-v2`。
- 72 小时选择窗口使用 `coalesce(published_at, fetched_at)`。
- 社交、社区和聚合器不能单独确认新闻事实。
- MiniMax 不参与相关性、评分、证据独立性、确认状态和来源合规决策。
- API Key 只通过当前进程环境或未跟踪 `.env` 读取，不得进入 Git、数据库、报告、日志或 HTML。
- 互联网原文在模型提示中始终标记为不可信输入。
- 不实现新来源、推荐、日报、推送和调度器。

---

## 文件结构

**新增文件**

- `migrations/versions/20260714_0014_event_quality_closure_v2.py`：追加式数据库迁移和旧事件 legacy 回填。
- `src/newsradar/events/quality.py`：相关性结论持久化结构、事件评分输入计算和质量统计的纯函数。
- `src/newsradar/events/reporting.py`：中文事件质量验收报告。
- `tests/events/test_quality.py`：评分输入和处理统计测试。
- `tests/acceptance/test_event_quality_closure.py`：SQLite/PostgreSQL 兼容的端到端质量验收。
- `tests/web/test_event_quality_pages.py`：current/legacy、评分和处理覆盖网页测试。
- `reports/event-quality-closure-v2.md`：真实 72 小时回填完成后生成的验收证据。

**修改文件**

- `src/newsradar/db/models.py`：事件可见性和 RawItem 处理结论字段。
- `src/newsradar/events/schema.py`：`EventVisibility`、处理结论和质量统计模型。
- `src/newsradar/events/relevance.py`：相关性 v2。
- `src/newsradar/events/entities.py`：v2 版本和明确 AI 对象实体。
- `src/newsradar/events/clustering.py`：聚类 v2 的对象/动作门槛。
- `src/newsradar/events/evidence.py`：独立证据根继续去重并提供评分输入。
- `src/newsradar/events/scoring.py`：score-v2 和真实分项计算入口。
- `src/newsradar/events/repository.py`：处理结论、visibility 和统计查询。
- `src/newsradar/events/pipeline.py`：72 小时全覆盖、v2 候选、规则预筛和有界模型增强。
- `src/newsradar/events/minimax.py`：有界并发调用与可审计降级结果。
- `src/newsradar/events/publishing.py`：发布 current 事件和 score-v2 快照。
- `src/newsradar/events/runtime.py`：Operation 结果统计和检查点。
- `src/newsradar/operations/commands.py`：v2 算法版本和幂等键。
- `src/newsradar/web/event_queries.py`：current 默认查询、legacy 查询和质量视图。
- `src/newsradar/web/app.py`：事件可见性筛选和质量报告路由。
- `src/newsradar/web/templates/events_home.html`：当前事件首页指标。
- `src/newsradar/web/templates/events.html`：current/legacy 切换。
- `src/newsradar/web/templates/event_detail.html`：版本、六项评分、证据和模型状态。
- `src/newsradar/web/templates/capability_overview.html`：72 小时事件处理覆盖。
- `src/newsradar/web/i18n.py`：新增状态和原因中文映射。
- `src/newsradar/cli.py`：事件质量报告命令。
- 现有 `tests/events/`、`tests/web/`、`tests/test_migrations.py`：兼容和回归测试。

---

### 任务 1：追加式迁移、旧事件保护和 current/legacy 查询边界

**文件：**

- 新建：`migrations/versions/20260714_0014_event_quality_closure_v2.py`
- 修改：`src/newsradar/db/models.py`
- 修改：`src/newsradar/events/schema.py`
- 修改：`src/newsradar/events/repository.py`
- 修改：`src/newsradar/web/event_queries.py`
- 测试：`tests/test_migrations.py`
- 测试：`tests/events/test_repository.py`
- 测试：`tests/web/test_event_queries.py`

**接口：**

- 产生：`EventVisibility(StrEnum)`，值为 `CURRENT="current"`、`LEGACY="legacy"`。
- 产生：`EventRecord.visibility: str`，数据库非空并建立 `(visibility, status, occurred_at)` 索引。
- 扩展：`RawItemProcessingRecord.outcome`、`score`、`reason_codes`、`details`。
- 扩展：`EventRepository.record_stage(..., outcome, score, reason_codes, details)`。
- 扩展：`EventQueryService.list_events(..., visibility="current")`。

- [ ] **步骤 1：写迁移保护失败测试**

在 `tests/test_migrations.py` 新增真实升级测试，先构造 v1 事件数据，再升级到 head：

```python
def test_event_quality_v2_migration_preserves_history_and_marks_it_legacy(tmp_path) -> None:
    database_url = _sqlite_url(tmp_path / "event-quality.db")
    _upgrade(database_url, "20260713_0013")
    counts_before = _seed_event_history(database_url)

    _upgrade(database_url, "head")

    with create_engine(database_url).connect() as connection:
        assert connection.execute(text("select count(*) from events")).scalar_one() == counts_before["events"]
        assert connection.execute(text("select count(*) from event_versions")).scalar_one() == counts_before["versions"]
        assert connection.execute(text("select count(*) from event_items")).scalar_one() == counts_before["items"]
        assert connection.execute(text("select count(*) from event_scores")).scalar_one() == counts_before["scores"]
        assert connection.execute(text("select distinct visibility from events")).scalars().all() == ["legacy"]
```

- [ ] **步骤 2：运行迁移测试并确认因字段不存在而失败**

运行：

```powershell
uv run python -m pytest tests/test_migrations.py::test_event_quality_v2_migration_preserves_history_and_marks_it_legacy -q
```

预期：失败，提示 `visibility` 字段或 `20260714_0014` 迁移不存在。

- [ ] **步骤 3：实现追加式迁移和 ORM 字段**

迁移必须使用以下确定字段：

```python
revision = "20260714_0014"
down_revision = "20260713_0013"

def upgrade() -> None:
    op.add_column("events", sa.Column("visibility", sa.String(16), nullable=True))
    op.execute("UPDATE events SET visibility = 'legacy' WHERE visibility IS NULL")
    op.alter_column(
        "events", "visibility", nullable=False, server_default=sa.text("'current'")
    )
    op.create_index(
        "ix_events_visibility_status_occurred_at",
        "events",
        ["visibility", "status", "occurred_at"],
    )
    op.add_column("raw_item_processing", sa.Column("outcome", sa.String(16)))
    op.add_column("raw_item_processing", sa.Column("score", sa.Integer()))
    op.add_column(
        "raw_item_processing",
        sa.Column("reason_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "raw_item_processing",
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
```

`downgrade()` 只移除新增索引和字段，不删除原有数据表。

- [ ] **步骤 4：写 repository 和网页可见性失败测试**

```python
def test_event_query_defaults_to_current_and_can_show_legacy(db_session) -> None:
    current = seed_event(db_session, visibility="current", title="当前事件")
    legacy = seed_event(db_session, visibility="legacy", title="旧版事件")

    assert [row.event_id for row in EventQueryService(db_session).list_events().events] == [current.id]
    assert [row.event_id for row in EventQueryService(db_session).list_events({"visibility": "legacy"}).events] == [legacy.id]
```

同时验证 `record_stage()` 对相同 `(raw_item_id, stage, algorithm_version)` 更新同一结论而不插入重复行。

- [ ] **步骤 5：实现模型、repository 和查询边界**

`EventRepository.record_stage` 使用明确签名：

```python
def record_stage(
    self,
    raw_item_id: int,
    stage: ProcessingStage,
    algorithm_version: str,
    *,
    outcome: str | None = None,
    score: int | None = None,
    reason_codes: tuple[str, ...] = (),
    details: dict[str, object] | None = None,
) -> RawItemProcessingRecord:
```

`details` 只允许布尔、数字和稳定枚举；禁止保存正文、完整 URL 或请求头。

- [ ] **步骤 6：运行任务 1 测试**

```powershell
uv run python -m pytest tests/test_migrations.py tests/events/test_repository.py tests/web/test_event_queries.py -q
uv run ruff check migrations/versions/20260714_0014_event_quality_closure_v2.py src/newsradar/db/models.py src/newsradar/events/schema.py src/newsradar/events/repository.py src/newsradar/web/event_queries.py
```

预期：全部通过。

- [ ] **步骤 7：提交任务 1**

```powershell
git add migrations/versions/20260714_0014_event_quality_closure_v2.py src/newsradar/db/models.py src/newsradar/events/schema.py src/newsradar/events/repository.py src/newsradar/web/event_queries.py tests/test_migrations.py tests/events/test_repository.py tests/web/test_event_queries.py
git commit -m "feat: preserve legacy events and processing decisions"
```

---

### 任务 2：相关性 v2、明确排除原因和 72 小时全覆盖

**文件：**

- 修改：`src/newsradar/events/relevance.py`
- 修改：`src/newsradar/events/schema.py`
- 修改：`src/newsradar/events/pipeline.py`
- 修改：`src/newsradar/events/repository.py`
- 测试：`tests/events/test_relevance.py`
- 测试：`tests/events/test_pipeline.py`

**接口：**

- 产生：`RELEVANCE_RULE_VERSION = "relevance-v2"`。
- 扩展：`RelevanceDecision.outcome: Literal["included", "excluded"]`。
- 产生：`EventPipeline._select_and_classify_items(window_hours) -> SelectionResult`。
- `SelectionResult` 包含 `selected_count`、`included`、`excluded_count`、`exclusion_reasons`。

- [ ] **步骤 1：写误报和有效样本失败测试**

在 `tests/events/test_relevance.py` 用真实问题样本固定行为：

```python
@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("Agent 64 is the GoldenEye successor arriving next month", "game_or_entertainment"),
        ("Model railway exhibition opens this weekend", "ambiguous_term_only"),
        ("Subscribe now for weekly technology deals", "advertisement_or_subscription"),
        ("Agent under fire", "ambiguous_term_only"),
    ],
)
def test_relevance_v2_rejects_ambiguous_non_ai_items(title: str, reason: str) -> None:
    result = evaluate_relevance(RawItemText(title=title, source_topics=("ai",)))
    assert result.is_relevant is False
    assert result.outcome == "excluded"
    assert reason in result.reasons

@pytest.mark.parametrize(
    "title",
    [
        "OpenAI launches a new multimodal model API",
        "Anthropic releases an AI coding agent SDK",
        "Benchmark evaluates inference efficiency for LLMs",
    ],
)
def test_relevance_v2_keeps_explicit_ai_events(title: str) -> None:
    result = evaluate_relevance(RawItemText(title=title))
    assert result.is_relevant is True
    assert result.outcome == "included"
    assert result.score >= 60
```

- [ ] **步骤 2：运行测试并确认旧版宽松规则失败**

```powershell
uv run python -m pytest tests/events/test_relevance.py -q
```

预期：失败，旧规则会接受 `agent`/`model` 单词且没有 `outcome`。

- [ ] **步骤 3：实现相关性 v2 纯规则**

实现固定信号组和原因代码。评分规则保持可解释：

```python
score = min(
    100,
    60 * bool(strong_matches)
    + 20 * bool(ai_entities)
    + 20 * bool(event_actions),
)
is_relevant = not exclusion_reasons and score >= 60
```

来源主题只能在已有歧义词且存在明确动作时增加上下文，不能直接贡献 60 分。正文输入在归一化前截断到固定长度，避免超大 RawItem 阻塞规则处理。

- [ ] **步骤 4：写 72 小时全覆盖失败测试**

```python
def test_pipeline_records_included_and_excluded_items_using_published_or_fetched_time(db_session) -> None:
    included = seed_raw_item(db_session, title="OpenAI launches AI model", published_at=NOW)
    excluded = seed_raw_item(db_session, title="Agent 64 game review", published_at=NOW)
    missing_date = seed_raw_item(db_session, title="Generic company update", published_at=None, fetched_at=NOW)

    result = EventPipeline.production(db_session).run(
        window_hours=72,
        operation_id=1,
        checkpoint=lambda _: None,
    )

    assert result.selected_item_count == 3
    assert result.included_item_count == 1
    assert result.excluded_item_count == 2
    assert processing_outcome(db_session, included.id, "relevance-v2") == "included"
    assert processing_outcome(db_session, excluded.id, "relevance-v2") == "excluded"
    assert processing_outcome(db_session, missing_date.id, "relevance-v2") == "excluded"
```

- [ ] **步骤 5：实现分类与短事务持久化**

选择查询使用：

```python
event_time = func.coalesce(RawItemRecord.published_at, RawItemRecord.fetched_at)
statement = statement.where(event_time >= cutoff).order_by(RawItemRecord.id)
```

先在内存执行纯规则，再用一个短事务批量 upsert 处理结论。只把 `included` 项传给实体和聚类阶段。

- [ ] **步骤 6：运行任务 2 测试并提交**

```powershell
uv run python -m pytest tests/events/test_relevance.py tests/events/test_pipeline.py -q
uv run ruff check src/newsradar/events/relevance.py src/newsradar/events/schema.py src/newsradar/events/pipeline.py src/newsradar/events/repository.py
git add src/newsradar/events/relevance.py src/newsradar/events/schema.py src/newsradar/events/pipeline.py src/newsradar/events/repository.py tests/events/test_relevance.py tests/events/test_pipeline.py
git commit -m "feat: classify every recent raw item with relevance v2"
```

---

### 任务 3：聚类 v2、独立证据根和真实评分输入

**文件：**

- 新建：`src/newsradar/events/quality.py`
- 修改：`src/newsradar/events/entities.py`
- 修改：`src/newsradar/events/clustering.py`
- 修改：`src/newsradar/events/evidence.py`
- 修改：`src/newsradar/events/scoring.py`
- 修改：`src/newsradar/events/publishing.py`
- 修改：`src/newsradar/events/pipeline.py`
- 新建：`tests/events/test_quality.py`
- 修改：`tests/events/test_clustering.py`
- 修改：`tests/events/test_evidence.py`
- 修改：`tests/events/test_scoring.py`
- 修改：`tests/events/test_publishing.py`

**接口：**

- 产生：`ENTITY_RULE_VERSION = "entities-v2"`、`CLUSTER_RULE_VERSION = "cluster-v2"`、`SCORE_RULE_VERSION = "score-v2"`。
- 产生：`build_score_input(candidate, evidence, relevance_by_item, now, prior_event_exists) -> EventScoreInput`。
- 产生：`QualityInputs`，只包含规则评分所需的安全数值。

- [ ] **步骤 1：写聚类边界失败测试**

```python
def test_cluster_v2_does_not_merge_shared_company_without_same_object_and_action() -> None:
    left = cluster_item(1, "OpenAI launches Orion model", entities=("organization:openai", "model:orion"))
    right = cluster_item(2, "OpenAI acquires Example Corp", entities=("organization:openai", "organization:example"))
    assert compare_items(left, right).matched is False

def test_cluster_v2_merges_same_object_action_within_48_hours() -> None:
    left = cluster_item(1, "OpenAI launches Orion model", entities=("model:orion",), published_at=NOW)
    right = cluster_item(2, "Orion model released by OpenAI", entities=("model:orion",), published_at=NOW + timedelta(hours=3))
    assert compare_items(left, right).matched is True
```

先运行 `tests/events/test_clustering.py`，确认旧版组织共享得分或版本常量不满足 v2。

- [ ] **步骤 2：实现实体动作门槛和 v2 身份**

只有共享 `product/model/paper/dataset/project` 对象，并且动作组一致，才允许实体相似度达到聚类阈值。共享组织仅作为 blocking key，不贡献足够合并分。候选 key 使用 v2 版本前缀，旧候选和当前候选不复用身份。

- [ ] **步骤 3：写六项评分输入失败测试**

```python
def test_build_score_input_uses_real_relevance_roots_authority_recency_engagement_and_novelty() -> None:
    result = build_score_input(
        candidate=quality_candidate(),
        evidence=(official_root(), professional_root()),
        relevance_by_item={1: 100, 2: 80},
        authority_by_item={1: 5, 2: 4},
        engagement_by_item={1: {"score": 120}, 2: {"comments": 25}},
        now=NOW,
        prior_event_exists=False,
    )
    assert result.ai_relevance == 90
    assert result.source_coverage == 70
    assert result.source_authority == 90
    assert result.recency == 100
    assert result.engagement_velocity > 0
    assert result.novelty == 100
```

另加无互动字段、单一根、72 小时边界和纯重复事件测试。

- [ ] **步骤 4：实现 `quality.py` 纯函数**

函数必须严格采用规格公式。互动分使用：

```python
engagement_velocity = min(100, round(25 * log10(1 + normalized_total)))
```

`normalized_total` 只累计数值型、非负互动字段；无字段为 0 并在评分原因加入 `engagement_unavailable`。时效以 Operation 的固定 `window_end` 作为 `now`，保证同一 Operation 重放得到同一分数。

- [ ] **步骤 5：让发布器持久化真实 score-v2 和 current 可见性**

`EventPublisher.publish()` 接收已计算的 `EventScoreInput`，不再从空 `metadata["score_input"]` 默认构造全 0。`publish_complete_event()` 新建或更新事件时写入 `visibility="current"`。

- [ ] **步骤 6：运行任务 3 测试并提交**

```powershell
uv run python -m pytest tests/events/test_quality.py tests/events/test_clustering.py tests/events/test_evidence.py tests/events/test_scoring.py tests/events/test_publishing.py -q
uv run ruff check src/newsradar/events/quality.py src/newsradar/events/entities.py src/newsradar/events/clustering.py src/newsradar/events/evidence.py src/newsradar/events/scoring.py src/newsradar/events/publishing.py src/newsradar/events/pipeline.py
git add src/newsradar/events tests/events
git commit -m "feat: score event candidates from real quality signals"
```

---

### 任务 4：MiniMax 有界中文增强、降级审计和 Worker 结果统计

**文件：**

- 修改：`src/newsradar/events/minimax.py`
- 修改：`src/newsradar/events/pipeline.py`
- 修改：`src/newsradar/events/repository.py`
- 修改：`src/newsradar/events/runtime.py`
- 修改：`src/newsradar/operations/commands.py`
- 修改：`tests/events/test_minimax.py`
- 修改：`tests/events/test_pipeline.py`
- 修改：`tests/events/test_pipeline_provenance.py`
- 修改：`tests/events/test_runtime.py`
- 修改：`tests/acceptance/test_event_model_degradation.py`
- 修改：`tests/acceptance/test_event_postgres_contention.py`

**接口：**

- 产生：`EventEnrichmentBatch.enrich(candidates) -> dict[str, EventEnrichmentResult]`。
- 扩展：`PipelineResult` 包含 `selected_item_count`、`included_item_count`、`excluded_item_count`、`exclusion_reasons`、`model_success_count`、`model_fallback_count`。
- `enqueue_event_pipeline()` 的版本和幂等键使用全部 v2 版本与固定 `window_end`。

- [ ] **步骤 1：写模型有界调用失败测试**

```python
@pytest.mark.asyncio
async def test_enrichment_batch_limits_concurrency_and_skips_excluded_items() -> None:
    tracker = ConcurrencyTracker()
    batch = EventEnrichmentBatch(adapter=tracked_adapter(tracker), max_concurrency=2)
    results = await batch.enrich(tuple(candidate(index) for index in range(5)))
    assert len(results) == 5
    assert tracker.maximum == 2
```

同时覆盖非法 JSON 只修复一次、429、超时、5xx、无 Key 和单候选失败不影响其他候选。

- [ ] **步骤 2：实现候选级有界并发与安全上下文**

只对已经形成事件候选且将发布 current 版本的候选调用 `M2.7-highspeed`。每候选最多 5 条证据、每标题最多 500 字符，不发送正文、payload、URL 查询参数或环境变量。M3 只在规则已经标记 `disputed` 时调用。

- [ ] **步骤 3：写模型审计和短事务失败测试**

验证每个模型尝试均产生 `model_usage` 和关联 `event_model_runs`；无 Key 时记录安全的 `no_api_key` 降级。使用现有 TrackingSession 测试确认调用期间没有打开的事务和事件租约。

- [ ] **步骤 4：实现审计、Operation 汇总和 v2 幂等键**

Operation 结果必须包含：

```python
{
    "selected_item_count": result.selected_item_count,
    "included_item_count": result.included_item_count,
    "excluded_item_count": result.excluded_item_count,
    "exclusion_reasons": result.exclusion_reasons,
    "candidate_count": result.candidate_count,
    "created_event_versions": result.created_event_versions,
    "model_success_count": result.model_success_count,
    "model_fallback_count": result.model_fallback_count,
}
```

检查点至少记录 `after_event_selection`、`after_event_relevance`、`after_event_cluster`、`after_event_enrichment` 和 `after_event_publish`。

- [ ] **步骤 5：运行 Worker、超时和并发测试**

```powershell
uv run python -m pytest tests/events/test_minimax.py tests/events/test_pipeline.py tests/events/test_pipeline_provenance.py tests/events/test_runtime.py tests/acceptance/test_event_model_degradation.py tests/acceptance/test_event_postgres_contention.py -q
uv run ruff check src/newsradar/events/minimax.py src/newsradar/events/pipeline.py src/newsradar/events/repository.py src/newsradar/events/runtime.py src/newsradar/operations/commands.py
```

- [ ] **步骤 6：提交任务 4**

```powershell
git add src/newsradar/events src/newsradar/operations/commands.py tests/events tests/acceptance/test_event_model_degradation.py tests/acceptance/test_event_postgres_contention.py
git commit -m "feat: enrich event candidates with bounded MiniMax fallback"
```

---

### 任务 5：中文事件网页、历史入口和处理覆盖

**文件：**

- 修改：`src/newsradar/web/event_queries.py`
- 修改：`src/newsradar/web/capability_queries.py`
- 修改：`src/newsradar/web/app.py`
- 修改：`src/newsradar/web/i18n.py`
- 修改：`src/newsradar/web/templates/events_home.html`
- 修改：`src/newsradar/web/templates/events.html`
- 修改：`src/newsradar/web/templates/event_detail.html`
- 修改：`src/newsradar/web/templates/capability_overview.html`
- 新建：`tests/web/test_event_quality_pages.py`
- 修改：`tests/web/test_event_queries.py`
- 修改：`tests/web/test_event_routes.py`
- 修改：`tests/web/test_capability_queries.py`

**接口：**

- 扩展：`EventRow` 包含 `visibility`、`importance`、`credibility`、`independent_root_count`、`enrichment_origin`。
- 扩展：`EventDetailView` 包含六项评分、关注理由、限制和模型运行摘要。
- 产生：`EventQualityCoverageView`，包含 72 小时处理覆盖和排除原因分布。

- [ ] **步骤 1：写 current/legacy 和首页门槛失败测试**

```python
def test_home_only_shows_current_confirmed_complete_events_from_last_24_hours(db_session) -> None:
    current = seed_complete_event(db_session, visibility="current", status="confirmed", ai_relevance=80)
    seed_complete_event(db_session, visibility="legacy", status="confirmed", ai_relevance=100)
    seed_complete_event(db_session, visibility="current", status="emerging", ai_relevance=90)
    assert [row.event_id for row in EventQueryService(db_session).home(now=NOW).events] == [current.id]
```

网页路由测试验证 `/events` 默认 current，`/events?visibility=legacy` 显示旧版警告。

- [ ] **步骤 2：写评分、证据和模型状态页面失败测试**

详情页必须出现“AI 相关性、来源覆盖、来源权威性、时效、互动热度、新颖性”，显示独立证据根数量，并只显示模型名称、purpose、outcome 和延迟。测试断言响应不包含 `Authorization`、`Cookie`、`MINIMAX_API_KEY`、查询参数密钥和提示全文。

- [ ] **步骤 3：实现只读查询模型**

查询只读取已发布完整版本。处理覆盖使用集合查询，不按 RawItem 循环查询。72 小时窗口和 v2 算法版本集中在查询服务常量中。

- [ ] **步骤 4：实现 A 风格中文页面**

首页首屏显示：当前确认事件、当前新兴线索、72 小时已处理/总数、排除数和最后完成时间。事件卡片显示中文标题、说明、关注理由、状态、独立证据数和三个核心分数。legacy 只在历史入口展示。

- [ ] **步骤 5：运行网页与查询测试**

```powershell
uv run python -m pytest tests/web/test_event_quality_pages.py tests/web/test_event_queries.py tests/web/test_event_routes.py tests/web/test_capability_queries.py -q
uv run ruff check src/newsradar/web
```

- [ ] **步骤 6：提交任务 5**

```powershell
git add src/newsradar/web tests/web
git commit -m "feat: explain current event quality in Chinese dashboard"
```

---

### 任务 6：中文报告、真实 PostgreSQL 回填和最终验收

**文件：**

- 新建：`src/newsradar/events/reporting.py`
- 修改：`src/newsradar/cli.py`
- 新建：`tests/events/test_reporting.py`
- 修改：`tests/test_cli.py`
- 新建：`tests/acceptance/test_event_quality_closure.py`
- 生成：`reports/event-quality-closure-v2.md`

**接口：**

- 产生命令：`newsradar events quality-report --window-hours 72 --output reports/event-quality-closure-v2.md`。
- 报告包含输入、included/excluded、原因分布、候选、current/legacy、状态、评分、MiniMax 和剩余问题。

- [ ] **步骤 1：写报告和 CLI 失败测试**

```python
def test_quality_report_is_chinese_auditable_and_secret_free() -> None:
    report = render_event_quality_report(sample_quality_view())
    assert "# Event Intelligence v2 事件质量验收报告" in report
    assert "72 小时 RawItem" in report
    assert "排除原因" in report
    assert "MiniMax 降级" in report
    assert "secret-value" not in report
    assert "?key=" not in report
```

- [ ] **步骤 2：实现只读报告与 CLI**

CLI 只读取 PostgreSQL 并写用户指定 Markdown 文件；不得触发抓取、事件构建或模型调用。输出路径外的文件不得修改。

- [ ] **步骤 3：运行完整自动化测试**

```powershell
uv run ruff check .
uv run python -m pytest -q
git diff --check
```

预期：772 项现有测试加新增测试全部通过；允许已有依赖弃用警告，不允许失败或收集错误。

- [ ] **步骤 4：准备真实运行环境但不持久复制密钥**

从用户已授权的本地未跟踪配置读取 PostgreSQL 和 MiniMax Key，只注入当前 Worker 进程环境。执行前只输出布尔状态：`database_configured=True`、`minimax_configured=True`，不得输出值。

先升级数据库：

```powershell
uv run alembic upgrade head
```

记录迁移前后四项历史数量，确认不减少。

- [ ] **步骤 5：执行一次 72 小时受控回填**

通过网页或 CLI 入队一个 `event_pipeline` Operation，`window_hours=72`。由独立 Worker 消费，观察心跳、检查点、超时和终态；不在网页请求线程执行管线。

完成后验证：

```text
selected_item_count = 最近 72 小时 RawItem 数
included_item_count + excluded_item_count = selected_item_count
所有选择项存在 relevance-v2 唯一结论
旧事件数量、版本、成员和评分不减少
current 事件没有未命名标题和空摘要
至少一个模型调用为 success；否则报告明确的安全错误码并证明规则降级完成
```

- [ ] **步骤 6：生成报告并进行浏览器验收**

```powershell
uv run newsradar events quality-report --window-hours 72 --output reports/event-quality-closure-v2.md
```

在本地网页验收 `/`、`/events`、`/events?visibility=legacy`、一个 current 详情和项目能力页。确认 `Agent 64` 不在 current 结果、旧事件仍可查看、评分非零、中文增强状态明确。

- [ ] **步骤 7：安全扫描和最终审查**

扫描已跟踪差异、报告、数据库模型记录和网页响应，确认没有 Key、Authorization、Cookie、数据库连接串或敏感查询参数。请求独立代码审查，修复全部 Critical 和 Important 问题后重跑完整测试。

- [ ] **步骤 8：提交验收证据**

```powershell
git add src/newsradar/events/reporting.py src/newsradar/cli.py tests/events/test_reporting.py tests/test_cli.py tests/acceptance/test_event_quality_closure.py reports/event-quality-closure-v2.md
git commit -m "docs: record event quality closure v2 acceptance"
```

---

## 最终完成标准

- 数据迁移无损保留全部旧事件数据，并默认隐藏 legacy。
- 最近 72 小时 RawItem 的 relevance-v2 处理覆盖率为 100%。
- 已知游戏、广告、泛科技和自动转发误报被排除。
- current 事件六项评分来自真实输入，不再全部为 0。
- 社交/社区/聚合内容无法单独成为 confirmed。
- 至少一个真实候选完成 MiniMax 中文增强；MiniMax 不可用时规则流程仍成功。
- 首页只显示 current、confirmed、24 小时内且完整发布的事件。
- 网页和中文报告能够解释覆盖、排除、评分、证据和模型降级。
- 完整测试、Ruff、差异检查、安全扫描和独立代码审查全部通过。
- 合并时不覆盖 `main` 的未提交报告，不强制推送，不删除包含 `.env` 或 `.local` 的工作树。
