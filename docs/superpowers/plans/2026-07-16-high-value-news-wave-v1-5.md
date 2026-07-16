# News Codex v1.5 高价值真实热点波次实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从现有来源目录中冻结一批高价值 AI/技术入口，复用 RawItem 与 EventPipeline，产出最近 24 小时已确认热点、早期信号和 7 天趋势。

**Architecture:** 新增可审计的 Wave Profile 与 `high_value_news_wave` Operation，成员抓取复用现有 IngestionService，事件阶段复用现有 EventPipeline。来源角色、证据确认、综合热度和趋势都写入不可变事件版本；网页只读取 manifest 完整且通过校验的终态快照，MiniMax 不可用时回退规则结果。

**Tech Stack:** Python 3.12、SQLAlchemy 2、Alembic、Pydantic 2、Typer、FastAPI/Jinja2、HTTPX、PostgreSQL、pytest、MiniMax API。

## Global Constraints

- 暂不使用 Docker；本机 PostgreSQL、Python 与 Worker 直接运行。
- 首轮只引用现有来源 ID，不增加大量账号、频道或媒体栏目。
- 默认窗口为最近 24 小时，趋势窗口为 7 天。
- 社区、社交和聚合来源不能独立确认新闻事实。
- 官方一手来源可确认自身发布；非官方事实需要两家独立专业媒体，或一家独立专业媒体加可核验一手材料。
- 早期信号与已确认热点分区展示，不能依靠互动量越过证据门槛。
- MiniMax 不决定来源合规、事实确认或基础热度分；完全不可用时流程仍能完成。
- 不使用 Cookie、登录态、验证码破解、代理绕过或 HTML 自动回退。
- 网络请求不得跨 SQLAlchemy Session 事务；所有写操作继续使用 claim fencing、deadline、取消和安全优先恢复。
- API Key、Authorization、Cookie、数据库连接和完整正文不得进入日志、网页、报告或 Git。
- 第一阶段只提供人工入队与 `enqueue-due` 计算，不直接启用无人值守系统定时任务。

---

### Task 1：高价值 Wave Profile、严格校验与纯计划

**Files:**
- Create: `wave_profiles/high-value-ai-tech.yaml`
- Create: `src/newsradar/waves/schema.py`
- Create: `src/newsradar/waves/loader.py`
- Create: `src/newsradar/waves/planning.py`
- Create: `src/newsradar/waves/__init__.py`
- Modify: `src/newsradar/cli.py`
- Create: `tests/waves/test_profile.py`
- Create: `tests/waves/test_planning.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces `WaveProfile`, `WaveMemberSnapshot`, `WavePlan`、`load_wave_profile(path)`、`build_wave_plan(profile, sources, latest_probes, configured_credentials)`。
- 后续 Task 2 只消费冻结的 `WavePlan`，不重新读取 YAML 或环境变量值。

- [ ] **Step 1: 写严格 Profile 与计划失败测试**

```python
def test_high_value_profile_has_bounded_existing_targets(source_catalog):
    profile = load_wave_profile(Path("wave_profiles/high-value-ai-tech.yaml"))
    assert profile.id == "high-value-ai-tech"
    assert 30 <= len(profile.source_ids) <= 50
    assert set(profile.source_ids) <= {source.id for source in source_catalog}
    assert {"discovery", "engagement", "evidence", "context"} <= set(profile.required_roles)


def test_plan_separates_fetchable_and_blocked_without_reading_credentials(
    profile, source_catalog, latest_probes
):
    plan = build_wave_plan(
        profile,
        source_catalog,
        latest_probes,
        configured_credentials={"YOUTUBE_API_KEY"},
    )
    assert plan.fetchable
    assert all(member.definition_hash for member in plan.members)
    assert all(member.source_id not in plan.fetchable_ids for member in plan.blocked)
```

Profile 固定引用以下 35 个现有目标：

```yaml
id: high-value-ai-tech
name: AI/技术高价值真实热点
window_hours: 24
trend_days: 7
required_roles: [discovery, engagement, evidence, context]
source_ids:
  - hackernews-top
  - hackernews-new
  - hackernews-best
  - reddit-localllama
  - reddit-machinelearning
  - reddit-artificial
  - mastodon-ai-tag
  - mastodon-machinelearning-tag
  - mastodon-llm-tag
  - bluesky-bsky
  - anthropic-bluesky
  - huggingface-bluesky
  - simon-willison-bluesky
  - techcrunch-bluesky
  - the-verge-bluesky
  - openai-youtube
  - anthropic-youtube
  - google-deepmind-youtube
  - huggingface-youtube
  - techmeme-feed
  - google-news-ai
  - google-news-research
  - google-news-business
  - google-news-chips-compute
  - google-news-policy-safety
  - gdelt-ai
  - universe-reuters-2
  - universe-ap-2
  - universe-bbc-1
  - universe-guardian-1
  - universe-techcrunch-1
  - universe-the-verge-1
  - universe-ars-technica-1
  - openai-news
  - anthropic-newsroom
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/waves/test_profile.py tests/waves/test_planning.py tests/test_cli.py -q`

Expected: FAIL，`newsradar.waves` 与 `waves plan` 尚不存在。

- [ ] **Step 3: 实现冻结类型、校验和纯计划**

```python
class WaveProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    window_hours: int = Field(ge=1, le=168)
    trend_days: int = Field(ge=1, le=30)
    required_roles: tuple[str, ...]
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WaveMemberSnapshot:
    source_id: str
    provider_id: str
    definition_hash: str
    roles: tuple[str, ...]
    availability: str
    access_kind: str
    fetchable: bool
    blocked_reason: str | None


@dataclass(frozen=True, slots=True)
class WavePlan:
    profile_id: str
    members: tuple[WaveMemberSnapshot, ...]
    digest: str
    window_hours: int
    trend_days: int
```

计划器按 `source_id` 排序计算 SHA-256；仅 `ready`、直接/间接内容接入、最新探测方式一致且所需凭据已配置的目标进入 `fetchable`。不得读取环境变量值，只消费 `configured_credentials: set[str]`。

- [ ] **Step 4: 增加只读 CLI**

```text
newsradar waves validate --profile wave_profiles/high-value-ai-tech.yaml
newsradar waves plan --profile wave_profiles/high-value-ai-tech.yaml
```

`plan` 输出总数、可抓取、凭据/审批/付费阻塞和角色覆盖；不连接网络、不创建 Operation。

- [ ] **Step 5: 运行测试确认 GREEN**

Run: `uv run pytest tests/waves/test_profile.py tests/waves/test_planning.py tests/test_cli.py -q`

Expected: PASS。

- [ ] **Step 6: 提交 Task 1**

```bash
git add wave_profiles src/newsradar/waves src/newsradar/cli.py tests/waves tests/test_cli.py
git commit -m "feat: plan high-value news waves"
```

---

### Task 2：冻结 Wave Operation、成员模型与原子入队

**Files:**
- Create: `migrations/versions/20260716_0020_high_value_news_wave.py`
- Modify: `src/newsradar/db/models.py`
- Modify: `src/newsradar/operations/schema.py`
- Modify: `src/newsradar/operations/commands.py`
- Create: `src/newsradar/waves/repository.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/operations/test_schema.py`
- Modify: `tests/operations/test_commands.py`
- Create: `tests/waves/test_repository.py`

**Interfaces:**
- Consumes `WavePlan`。
- Produces `OperationType.HIGH_VALUE_NEWS_WAVE`、`HighValueWaveMemberRecord`、`WaveRepository`、`OperationCommandService.enqueue_high_value_wave(plan, trigger)`。

- [ ] **Step 1: 写迁移、冻结和防重失败测试**

```python
def test_enqueue_wave_freezes_plan_atomically(session, wave_plan):
    operation_id = OperationCommandService(session).enqueue_high_value_wave(
        plan=wave_plan, trigger="web"
    )
    operation = session.get(OperationRunRecord, operation_id)
    members = WaveRepository(session).members(operation_id)
    assert operation.operation_type == "high_value_news_wave"
    assert operation.progress_total == len(wave_plan.members)
    assert operation.requested_scope["profile_digest"] == wave_plan.digest
    assert tuple(row.source_id for row in members) == tuple(
        row.source_id for row in wave_plan.members
    )
```

另测活动批次防重、同一 operation/source 唯一约束、旧记录迁移保留和 PostgreSQL advisory lock。

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/test_migrations.py tests/waves/test_repository.py tests/operations/test_commands.py tests/operations/test_schema.py -q`

Expected: FAIL，0020、模型与操作类型不存在。

- [ ] **Step 3: 实现 0020 与冻结成员**

```python
class HighValueWaveMemberRecord(Base):
    __tablename__ = "high_value_wave_members"
    __table_args__ = (
        UniqueConstraint("operation_run_id", "source_id"),
        Index("ix_high_value_wave_member_state", "operation_run_id", "state"),
    )
    id: Mapped[int]
    operation_run_id: Mapped[int]
    source_id: Mapped[str]
    provider_id: Mapped[str]
    definition_hash: Mapped[str]
    roles_snapshot: Mapped[list[str]]
    availability_snapshot: Mapped[str]
    access_kind_snapshot: Mapped[str]
    fetchable: Mapped[bool]
    state: Mapped[str]
    fetch_run_id: Mapped[int | None]
    result_code: Mapped[str | None]
    conclusion: Mapped[str | None]
    claim_attempt_id: Mapped[int | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
```

迁移：`revision = "20260716_0020"`，`down_revision = "20260716_0019"`。

- [ ] **Step 4: 实现原子入队与成员仓储**

```python
def enqueue_high_value_wave(self, *, plan: WavePlan, trigger: str) -> int:
    window_end = self._utcnow()
    with self.session.begin():
        self._lock_high_value_wave_enqueue()
        if self._active_high_value_wave_id() is not None:
            raise ValueError("active_high_value_wave_exists")
        operation = OperationRepository(self.session).enqueue(
            OperationType.HIGH_VALUE_NEWS_WAVE,
            {
                "schema_version": 1,
                "profile_id": plan.profile_id,
                "profile_digest": plan.digest,
                "member_count": len(plan.members),
                "window_hours": plan.window_hours,
                "trend_days": plan.trend_days,
                "window_end": window_end.isoformat(),
                "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
                "deadline_at": (
                    window_end
                    + timedelta(seconds=self._settings.operation_timeout_seconds)
                ).isoformat(),
            },
            trigger=trigger,
            in_transaction=True,
        )
        WaveRepository(self.session).create_members(operation.id, plan)
        operation.progress_total = len(plan.members)
        operation_id = operation.id
    return operation_id
```

`_lock_high_value_wave_enqueue()` 与 `_active_high_value_wave_id()` 沿用现有 catalog refresh 的 PostgreSQL advisory-lock/活动批次防重写法。`WaveRepository.claim_member()`、`finish_member()` 复用 v1.4 的 attempt fencing 语义；blocked 成员在 Worker 中零网络完成。`window_end`、`algorithm_versions` 与 `deadline_at` 必须在入队时冻结，不能由 Worker 重新生成。

- [ ] **Step 5: 运行测试确认 GREEN**

Run: `uv run pytest tests/test_migrations.py tests/waves/test_repository.py tests/operations/test_commands.py tests/operations/test_schema.py -q`

Expected: PASS。

- [ ] **Step 6: 提交 Task 2**

```bash
git add migrations/versions/20260716_0020_high_value_news_wave.py src/newsradar/db/models.py src/newsradar/operations src/newsradar/waves/repository.py tests
git commit -m "feat: persist frozen high-value waves"
```

---

### Task 3：Wave 抓取运行时与 RawItem 幂等证据

**Files:**
- Create: `src/newsradar/waves/runtime.py`
- Modify: `src/newsradar/operations/fetch_runtime.py`
- Modify: `src/newsradar/cli.py`
- Create: `tests/waves/test_runtime.py`
- Modify: `tests/operations/test_fetch_runtime.py`
- Modify: `tests/operations/test_router.py`
- Modify: `tests/operations/test_worker.py`

**Interfaces:**
- Produces `HighValueWaveHandler`、公开的 `execute_production_fetch(source, operation_id, checkpoint, scope)`。
- Task 6 的网页只入队；真实网络仅在本 Handler 中发生。

- [ ] **Step 1: 写成员抓取、阻塞与 claim fencing 失败测试**

```python
def test_wave_fetches_only_claimed_fetchable_members(handler, lease, recorder):
    result = handler(lease, recorder.checkpoint)
    assert recorder.fetched_source_ids == ["hackernews-top", "techmeme-feed"]
    assert result.result_summary["fetch_succeeded"] == 2
    assert result.result_summary["blocked"] == 1


def test_stale_definition_finishes_without_network(handler, changed_source, recorder):
    result = handler.run_member(operation_id=1, source_id=changed_source.id)
    assert result.result_code == "stale_result"
    assert recorder.network_calls == []
```

覆盖：单成员失败继续、claim 失败零 I/O、取消、deadline、429、旧 Worker 不能覆盖新 attempt、全局并发 6、Provider 并发 2。

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/waves/test_runtime.py tests/operations/test_fetch_runtime.py tests/operations/test_router.py tests/operations/test_worker.py -q`

Expected: FAIL，Handler 和 Worker 路由不存在。

- [ ] **Step 3: 提取可复用生产抓取执行器**

将 `_execute_production_fetch` 重命名为 `execute_production_fetch`；`FetchOperationHandler.production()` 与 `HighValueWaveHandler.production()` 使用同一函数。不得复制 HTTP、eligibility 或 IngestionService 逻辑。

- [ ] **Step 4: 实现 Wave Handler**

```python
class HighValueWaveHandler:
    def __call__(self, lease: OperationLease, checkpoint: Callable[[str], None]) -> OperationResult:
        return asyncio.run(self._run(lease, checkpoint))

    async def _run(self, lease, checkpoint):
        members = self._unfinished_members(lease.operation_id)
        outcomes = await self._run_bounded_members(
            members,
            lease=lease,
            checkpoint=checkpoint,
            global_limit=6,
            provider_limit=2,
        )
        return self._operation_result(lease.operation_id, outcomes)
```

每个成员固定顺序：短事务 claim → 关闭 session → checkpoint → 网络抓取 → checkpoint → 短事务保存 fetch_run_id 与成员终态。阻塞成员写中文原因并零网络完成。

- [ ] **Step 5: 注册 Worker 并验证 GREEN**

Run: `uv run pytest tests/waves/test_runtime.py tests/operations/test_fetch_runtime.py tests/operations/test_router.py tests/operations/test_worker.py -q`

Expected: PASS。

- [ ] **Step 6: 提交 Task 3**

```bash
git add src/newsradar/waves/runtime.py src/newsradar/operations/fetch_runtime.py src/newsradar/cli.py tests/waves tests/operations
git commit -m "feat: ingest high-value wave members"
```

---

### Task 4：来源角色、独立证据根与现有确认状态收口

**Files:**
- Modify: `src/newsradar/events/evidence.py`
- Modify: `src/newsradar/events/scoring.py`
- Modify: `src/newsradar/events/pipeline.py`
- Modify: `src/newsradar/events/schema.py`
- Modify: `tests/events/test_evidence.py`
- Modify: `tests/events/test_scoring.py`
- Modify: `tests/events/test_pipeline.py`

**Interfaces:**
- 复用现有 `EventStatus`、`EvidenceAssessment.root_evidence_key`、`decide_publication()` 和 `decide_event_tier()`，不再建立第二套事件状态或证据类型。
- Task 5 的趋势与 Task 7 的网页读取事件版本 payload 中的 `status`、`evidence_summary`；中文界面把 `EventStatus.EMERGING` 展示为“早期信号”。

- [ ] **Step 1: 写早期信号、官方确认、双媒体确认和聚合去重失败测试**

```python
def test_social_and_aggregator_only_remains_early_signal():
    decision = decide_publication(candidate_with_roles("community", "aggregator"))
    assert decision.status is EventStatus.EMERGING
    assert decision.publish_to_top is False


def test_official_or_two_independent_media_confirms():
    assert decide_publication(candidate_with_roles("official")).status is EventStatus.CONFIRMED
    assert decide_publication(
        candidate_with_independent_media_roots("reuters", "ap")
    ).status is EventStatus.CONFIRMED


def test_syndicated_media_urls_count_as_one_root():
    evidence = assess_evidence(syndicated_items_same_origin())
    assert len({row.root_evidence_key for row in evidence if row.independent}) == 1
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/events/test_evidence.py tests/events/test_scoring.py tests/events/test_pipeline.py -q`

Expected: 至少聚合原始根、同稿转载根或 `evidence_summary` 断言失败。

- [ ] **Step 3: 收紧现有证据根与确认规则**

```python
def decide_publication(candidate, evidence):
    roots = independent_roots(evidence)
    if candidate.metadata.get("disputed"):
        return PublicationDecision(status=EventStatus.DISPUTED, publish_to_top=False)
    if has_official_root(roots) or professional_root_count(roots) >= 2:
        return PublicationDecision(status=EventStatus.CONFIRMED, publish_to_top=True)
    return PublicationDecision(status=EventStatus.EMERGING, publish_to_top=False)
```

继续在 `EvidenceAssessment` 中保存根：优先使用解析后的原始 Publisher + Canonical URL；聚合器 discovery URL 不计独立根；相同上游 URL 的转载只计一个根。来源角色从 SourceDefinition 的冻结 roles 与 Provider/nature 推导，不能由模型改写。官方来源只确认其自身发布；专业媒体的非官方事实仍需两个独立根。

- [ ] **Step 4: 将证据摘要写入不可变事件版本**

事件 payload 增加：

```python
"status": decision.status.value,
"evidence_summary": {
    "official_roots": official_count,
    "professional_roots": professional_count,
    "community_signals": community_count,
    "aggregator_pointers": aggregator_count,
    "missing_confirmation": list(decision.missing_confirmation),
},
```

- [ ] **Step 5: 运行测试确认 GREEN 并提交**

Run: `uv run pytest tests/events/test_evidence.py tests/events/test_scoring.py tests/events/test_pipeline.py -q`

Expected: PASS。

```bash
git add src/newsradar/events tests/events
git commit -m "feat: separate early signals from confirmed events"
```

---

### Task 5：综合热度、24 小时榜与 7 天趋势

**Files:**
- Create: `src/newsradar/events/trends.py`
- Modify: `src/newsradar/events/quality.py`
- Modify: `src/newsradar/events/scoring.py`
- Modify: `src/newsradar/events/publishing.py`
- Modify: `src/newsradar/events/pipeline.py`
- Create: `tests/events/test_trends.py`
- Modify: `tests/events/test_quality.py`
- Modify: `tests/events/test_ranking.py`
- Modify: `tests/events/test_publishing.py`

**Interfaces:**
- Produces `TrendDirection`、`TrendAssessment`、`assess_trend(current, history)`。
- 事件版本 payload 固定保存 `heat_breakdown` 与 `trend`，网页不得按墙上时间重算历史。

- [ ] **Step 1: 写综合分、隔离榜单和趋势失败测试**

```python
def test_community_velocity_cannot_promote_unconfirmed_event():
    score = score_event(high_engagement_community_only_input())
    decision = decide_event_tier(
        community_only_candidate(),
        score,
        evidence=community_only_evidence(),
    )
    assert decision.tier is EventTier.SIGNAL


def test_trend_uses_immutable_seven_day_snapshots():
    trend = assess_trend(
        current=heat_snapshot("2026-07-16T00:00:00Z", 82),
        history=[heat_snapshot("2026-07-15T00:00:00Z", 60)],
    )
    assert trend.direction is TrendDirection.RISING
    assert trend.delta == 22
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/events/test_trends.py tests/events/test_quality.py tests/events/test_ranking.py tests/events/test_publishing.py -q`

Expected: FAIL，趋势类型与 payload 不存在。

- [ ] **Step 3: 实现确定性趋势**

```python
class TrendDirection(StrEnum):
    RISING = "rising"
    SUSTAINED = "sustained"
    COOLING = "cooling"


@dataclass(frozen=True, slots=True)
class TrendAssessment:
    direction: TrendDirection
    delta: int
    current_heat: int
    baseline_heat: int
    snapshot_count: int
```

规则：与 24 小时前最近完整快照比较；delta ≥ 10 为 rising，delta ≤ -10 为 cooling，其余 sustained。无历史时为 rising，原因 `trend:first_snapshot`。

- [ ] **Step 4: 保存可解释热度与趋势**

`EventVersion.payload` 保存六维得分、传播速度输入、独立根数量、互动字段白名单、惩罚原因、趋势方向与比较快照。`EventRecord.rank_score` 继续保存当前确定性 heat；早期信号只能进入 signal tier。

- [ ] **Step 5: 运行测试确认 GREEN 并提交**

Run: `uv run pytest tests/events/test_trends.py tests/events/test_quality.py tests/events/test_ranking.py tests/events/test_publishing.py -q`

Expected: PASS。

```bash
git add src/newsradar/events tests/events
git commit -m "feat: rank explainable daily news trends"
```

---

### Task 6：Wave 事件阶段、完整快照与 MiniMax 降级

**Files:**
- Modify: `src/newsradar/waves/runtime.py`
- Modify: `src/newsradar/events/runtime.py`
- Modify: `src/newsradar/events/minimax.py`
- Modify: `src/newsradar/events/operation_snapshots.py`
- Modify: `tests/waves/test_runtime.py`
- Modify: `tests/events/test_runtime.py`
- Modify: `tests/events/test_minimax.py`
- Modify: `tests/events/test_operation_snapshots.py`

**Interfaces:**
- Wave Handler 在所有成员终态后调用现有 EventPipeline，使用同一 operation 的 `window_end` 与版本清单。
- `event_pipeline` 仍只接受 `succeeded` 快照；`high_value_news_wave` 在所有成员均已进入终态、成员清单完整且事件版本 manifest 完整时，可接受 `succeeded` 或 `partial`。这样单来源失败不会隐藏整轮结果，但运行中、取消或事件阶段失败的 Operation 绝不能成为网页快照。

- [ ] **Step 1: 写端到端阶段和模型离线失败测试**

```python
def test_wave_builds_event_snapshot_after_fetch_members_finish(wave_handler, lease):
    result = wave_handler(lease, checkpoint=lambda _: None)
    assert result.result_summary["completed_members"] == result.result_summary["member_total"]
    assert result.result_summary["event_version_snapshots"]
    assert result.result_summary["window_hours"] == 24


def test_minimax_offline_still_publishes_rule_snapshot(wave_handler, offline_model):
    result = wave_handler.with_model(offline_model)(lease(), lambda _: None)
    assert result.status in {OperationStatus.SUCCEEDED, OperationStatus.PARTIAL}
    assert result.result_summary["model_degraded"] is True
    assert result.result_summary["event_version_snapshots"]


def test_partial_wave_is_readable_only_with_complete_member_and_event_manifests(session):
    complete_partial = seed_wave_operation(
        session,
        status="partial",
        all_members_terminal=True,
        complete_event_manifest=True,
    )
    assert event_snapshot_by_id(session, complete_partial.id) is not None

    incomplete_partial = seed_wave_operation(
        session,
        status="partial",
        all_members_terminal=False,
        complete_event_manifest=True,
    )
    assert event_snapshot_by_id(session, incomplete_partial.id) is None
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/waves/test_runtime.py tests/events/test_runtime.py tests/events/test_minimax.py tests/events/test_operation_snapshots.py -q`

Expected: Wave result 尚无事件 manifest 或快照选择器不识别新 operation type。

- [ ] **Step 3: 集成 EventPipeline**

抓取阶段完成后，用持久化 `window_end` 调用：

```python
event_session = self._create_session()
try:
    event_result = EventPipeline.production(event_session).run(
        operation_id=lease.operation_id,
        window_hours=int(lease.requested_scope["window_hours"]),
        checkpoint=checkpoint,
    )
finally:
    event_session.close()
```

不得在抓取网络事务中运行事件处理。MiniMax 继续使用现有 `EventPipeline`/`EventMiniMaxAdapter` 的配置与规则回退，不在 Wave 层另建模型客户端。事件阶段失败时 Operation 为 `failed`，并保留已完成成员和错误阶段；不得把不完整 manifest 标记为可读。只有“成员抓取存在失败、但所有成员已终态且事件阶段完整”时才返回 `partial`。

- [ ] **Step 4: 扩展完整快照选择器**

`latest_complete_event_snapshot()` 与 `event_snapshot_by_id()` 接受 `event_pipeline` 与 `high_value_news_wave`，但两者都必须验证 operation 终态、窗口、算法版本和完整 event manifest。Wave 还必须核对持久化成员总数、终态成员数以及 result summary 中的 manifest 计数一致；不得仅凭 `partial` 状态放行。

- [ ] **Step 5: 运行测试确认 GREEN 并提交**

Run: `uv run pytest tests/waves/test_runtime.py tests/events/test_runtime.py tests/events/test_minimax.py tests/events/test_operation_snapshots.py -q`

Expected: PASS。

```bash
git add src/newsradar/waves src/newsradar/events tests/waves tests/events
git commit -m "feat: publish events from high-value waves"
```

---

### Task 7：中文热点首页、详情解释与安全入队

**Files:**
- Modify: `src/newsradar/web/event_queries.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/events_home.html`
- Modify: `src/newsradar/web/templates/events.html`
- Modify: `src/newsradar/web/templates/event_detail.html`
- Modify: `src/newsradar/web/static/styles.css`
- Modify: `src/newsradar/cli.py`
- Create: `tests/web/test_high_value_wave_pages.py`
- Modify: `tests/web/test_event_quality_pages.py`
- Modify: `tests/web/test_security.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- 新增 `POST /events/update`，只入队 `high_value_news_wave`，使用现有 loopback、same-origin、一次性 token。
- `EventQueryService.home()` 输出 confirmed、early、trend 三个区域和 wave 状态摘要。

- [ ] **Step 1: 写首页、详情和写操作失败测试**

```python
def test_home_separates_confirmed_early_and_seven_day_trends(client, event_snapshot):
    response = client.get("/")
    assert "最近 24 小时已确认热点" in response.text
    assert "早期信号" in response.text
    assert "7 天趋势" in response.text
    assert "为什么热门" in response.text


def test_event_update_only_enqueues_and_requires_safe_write(client, action_token):
    response = client.post(
        "/events/update",
        data={"action_token": action_token},
        headers={"Origin": "http://127.0.0.1:8766"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert network_recorder.calls == []
```

详情断言：时间线、热度六维分解、趋势、发现/确认来源分组、缺失确认条件、分歧、原始链接和 MiniMax 降级标记。

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/web/test_high_value_wave_pages.py tests/web/test_event_quality_pages.py tests/web/test_security.py tests/test_cli.py -q`

Expected: 新中文区块、入队路由或趋势字段断言失败。

- [ ] **Step 3: 扩展查询层与模板**

首页使用同一完整 operation snapshot：

```python
confirmed = rows(status="confirmed", hours=24)
early = rows(status="emerging", hours=24)
trends = rows(hours=24 * 7, trend=("rising", "sustained", "cooling"))
```

无完整快照时保留现有诊断警告，不以全局 current 目录冒充运行结果。

- [ ] **Step 4: 实现网页与 CLI 入队**

```text
newsradar waves enqueue --profile wave_profiles/high-value-ai-tech.yaml
newsradar waves status <operation-id>
newsradar waves report <operation-id> --output reports/high-value-news-wave-v1-5.md
```

网页和 CLI 都先严格加载 Profile/Source/Provider、同步定义并冻结计划；请求进程不访问外部网络或 MiniMax。

- [ ] **Step 5: 运行测试确认 GREEN 并提交**

Run: `uv run pytest tests/web/test_high_value_wave_pages.py tests/web/test_event_quality_pages.py tests/web/test_security.py tests/test_cli.py -q`

Expected: PASS。

```bash
git add src/newsradar/web src/newsradar/cli.py tests/web tests/test_cli.py
git commit -m "feat: show daily confirmed and early AI news"
```

---

### Task 8：`enqueue-due`、三轮真实验收与中文报告

**Files:**
- Create: `src/newsradar/waves/scheduling.py`
- Create: `src/newsradar/waves/reporting.py`
- Modify: `src/newsradar/cli.py`
- Create: `tests/waves/test_scheduling.py`
- Create: `tests/waves/test_reporting.py`
- Create: `tests/acceptance/test_high_value_news_wave_v1_5.py`
- Create: `reports/high-value-news-wave-v1-5.md`
- Modify only when real evidence proves a defect: Tasks 1–7 files and matching tests.

**Interfaces:**
- Produces `wave_due(profile, latest_operation, now)`、`enqueue-due` 和最终验收报告。
- 不直接配置 Windows Task Scheduler；命令只在到期且无活动批次时入队。

- [ ] **Step 1: 写到期判断和报告失败测试**

```python
def test_enqueue_due_is_idempotent_and_never_runs_network(commands, now):
    first = enqueue_due(commands, profile, now=now)
    second = enqueue_due(commands, profile, now=now)
    assert first.operation_id is not None
    assert second.reason == "active_or_recent_wave"
    assert network_recorder.calls == []


def test_report_contains_evidence_and_no_secrets(operation, members, events):
    report = render_high_value_wave_report(operation, members, events)
    assert "已确认热点" in report
    assert "早期信号" in report
    assert "7 天趋势" in report
    assert "Authorization" not in report
    assert "Cookie" not in report
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/waves/test_scheduling.py tests/waves/test_reporting.py tests/acceptance/test_high_value_news_wave_v1_5.py -q`

Expected: 调度器、报告器和验收路径不存在。

- [ ] **Step 3: 实现幂等到期判断**

```python
@dataclass(frozen=True, slots=True)
class DueDecision:
    due: bool
    reason: str
    next_due_at: datetime | None


def wave_due(profile, latest_operation, now):
    if latest_operation and latest_operation.status in {"queued", "running"}:
        return DueDecision(False, "active_or_recent_wave", None)
    interval = timedelta(minutes=30)
    next_due = latest_operation.created_at + interval if latest_operation else now
    return DueDecision(now >= next_due, "due" if now >= next_due else "not_due", next_due)
```

- [ ] **Step 4: 编写 PostgreSQL 真实验收**

验收测试在无 `DATABASE_URL` 时 skip；配置后必须：

1. 迁移到 `20260716_0020 (head)`。
2. 严格加载 35 个 Profile 目标并冻结唯一成员。
3. 从 Web 入队，Worker 完成抓取与事件阶段。
4. 连续运行三轮，记录 RawItem inserted/updated/unchanged 和事件版本。
5. 断言相同 RawItem、Canonical URL 和事件不发生爆炸式重复。
6. 抽查当轮最多 20 个事件：确认证据根、早期信号隔离和聚合原始 URL。
7. 禁用 MiniMax 后运行一轮，事件快照仍完整。
8. 验证取消、deadline、claim fencing 与显式安全恢复。

- [ ] **Step 5: 执行真实三轮并生成报告**

```text
uv run alembic upgrade head
uv run newsradar waves validate --profile wave_profiles/high-value-ai-tech.yaml
uv run newsradar waves enqueue --profile wave_profiles/high-value-ai-tech.yaml
uv run newsradar worker --once
uv run newsradar waves report <operation-id> --output reports/high-value-news-wave-v1-5.md
```

每轮必须等待终态后再创建下一轮；外部 429/超时如实记录，不通过更换协议伪造成功。

- [ ] **Step 6: 运行完整门禁与浏览器验收**

```text
uv run pytest -q --maxfail=1
uv run ruff check .
uv run newsradar providers validate
uv run newsradar sources validate
uv run newsradar waves validate --profile wave_profiles/high-value-ai-tech.yaml
git diff --check
```

在临时端口验收 `/`、`/events`、`/emerging`、一个 confirmed、一个 early_signal、一个 disputed/失败诊断页面。浏览器控制台不得出现应用错误；报告不得包含凭据、请求头或正文。

- [ ] **Step 7: 提交验收证据**

```bash
git add src/newsradar/waves/scheduling.py src/newsradar/waves/reporting.py src/newsradar/cli.py tests/waves tests/acceptance/test_high_value_news_wave_v1_5.py reports/high-value-news-wave-v1-5.md
git commit -m "docs: accept high-value news wave v1.5"
```

---

## 最终完成判定

- 35 个现有目标进入冻结 Profile；阻塞目标有明确原因且零内容请求。
- 可抓取成员连续三轮完成，单来源失败不阻塞事件快照。
- RawItem 与事件幂等，聚合转载不会冒充多个独立证据根。
- 最近 24 小时已确认热点、早期信号和 7 天趋势均使用同一完整 Operation 快照。
- 所有 confirmed 事件满足官方或独立媒体证据规则；社区/社交信号不能越权确认。
- 热度分和趋势可解释、可重放，不依赖模型或当前墙上时间。
- MiniMax 完全不可用时事件页仍可用，并明确显示规则降级。
- Worker 取消、deadline、claim fencing、安全恢复和日志关联全部通过。
- PostgreSQL 迁移、完整测试、Ruff、来源/Profile 校验、浏览器验收和敏感信息扫描通过。
- 中文验收报告已提交，最终分支审查无 Critical/Important 问题。
