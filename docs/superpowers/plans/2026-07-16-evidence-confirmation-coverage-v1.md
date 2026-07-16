# News Codex「证据确认覆盖 v1」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有高价值新闻波次从 35 个目标扩展到 41 个目标，安全提升同一事件的官方/专业媒体交叉命中率，并通过三轮真实抓取自然产出至少一个可追溯的 `confirmed` 事件。

**Architecture:** 继续复用现有 Wave Profile、Worker、RawItem、EventPipeline、不可变 EventVersion 和中文网页。新增工作只收紧跨来源匹配、补齐三态 MiniMax 边界降级和运行证据指标；所有确认结论仍由审核来源元数据与确定性证据规则产生，不创建新事件表或第二套抓取系统。

**Tech Stack:** Python 3.12、SQLAlchemy 2、Pydantic 2、Typer、FastAPI/Jinja2、HTTPX、PostgreSQL、pytest、MiniMax API。

## Global Constraints

- 所有工作只在 `codex/evidence-confirmation-coverage-v1` 隔离分支执行，不直接修改 `main`。
- Profile 最终固定为 41 个唯一 Target，只新增设计规格列出的 6 个来源。
- 新增来源必须是 `coverage_mode: direct`、`availability: ready`、已批准 ingestion、包含 `evidence` 角色且最新探测成功。
- 来源的初步接入批准不等于深度研究完成；不得把 `research.status: needs_research` 改写成已完成。
- 官方一手来源可以确认自身发布；非官方事实必须具有两个独立专业媒体证据根。
- 聚合、社区和社交来源不能成为独立证据根；转载、同发布者镜像和共同上游只能计一个根。
- 跨来源确定性合并必须同时满足 48 小时窗口、非泛化共享实体、相同动作和安全标题相似度；强身份匹配除外。
- MiniMax 只判断规则边界候选对；`uncertain`、超时、429、非法 JSON 或未配置 Key 一律不合并。
- 不增加自动 HTML、登录页或付费墙抓取，不使用 Cookie、验证码破解、代理绕过或高风险非官方爬虫。
- 不新增 Event/RawItem 数据表，不新增后台调度，不重做导航和页面结构。
- API Key、Authorization、Cookie、数据库连接串、代理地址和完整正文不得进入日志、网页、报告、测试快照或 Git。
- 每个任务严格执行 RED → GREEN → 回归 → 提交；出现与本任务无关的基线失败时停止并报告。

---

## 文件结构与职责

### 只修改的现有文件

- `wave_profiles/high-value-ai-tech.yaml`：固定 41 个高价值波次成员。
- `src/newsradar/events/clustering.py`：跨来源确定性候选规则和 `cluster-v3`。
- `src/newsradar/events/schema.py`：边界候选三态响应及受限摘要字段。
- `src/newsradar/events/minimax.py`：MiniMax 边界候选的有界输入与保守回退。
- `src/newsradar/events/pairing.py`：把三态模型结果收敛成可审计的 merge/separate。
- `src/newsradar/events/pipeline.py`：候选对计数、精确事件版本指标和运行汇总。
- `src/newsradar/events/versions.py`：发布/读取双方共同认可的算法版本。
- `src/newsradar/waves/runtime.py`：冻结成员证据能力和事件确认指标写入 Operation 快照。
- `src/newsradar/waves/reporting.py`：中文单轮波次报告。
- `src/newsradar/web/event_queries.py`：事件证据计数和中文确认理由的只读投影。
- `src/newsradar/web/operation_queries.py`：Operation 结果中允许展示的数字指标白名单。
- `src/newsradar/web/i18n.py`：统一中文证据理由。
- `src/newsradar/web/templates/events_home.html`：现有首页事件卡证据说明。
- `src/newsradar/web/templates/event_detail.html`：现有详情页确认依据。
- `src/newsradar/web/templates/operation_detail.html`：现有运行页证据覆盖汇总。
- `src/newsradar/cli.py`：继续复用 `waves report`，不增加第二套报告入口。

### 新增的聚焦文件

- `src/newsradar/events/coverage.py`：从精确 EventVersion payload 计算证据覆盖指标的纯逻辑。
- `tests/events/test_coverage.py`：证据覆盖指标固定样本。
- `tests/acceptance/test_evidence_confirmation_coverage.py`：官方确认、双媒体确认、升级与失败隔离的端到端回归。
- `reports/evidence-confirmation-coverage-v1-acceptance-2026-07-16.md`：三轮真实运行的最终中文验收证据；只在真实运行完成后创建。

除上述文件外不主动重构。现有数据库结构足以保存来源冻结快照、候选对审计和事件版本，本计划不创建 Alembic 迁移。

---

### Task 1：将高价值 Profile 锁定为 41 个证据覆盖目标

**Files:**
- Modify: `wave_profiles/high-value-ai-tech.yaml`
- Modify: `tests/waves/test_profile.py`
- Modify: `tests/waves/test_planning.py`

**Interfaces:**
- Consumes: `load_wave_profile(path: Path) -> WaveProfile`、`load_source_tree(path: Path) -> list[SourceDefinition]`、`build_wave_plan(profile: WaveProfile, sources: Iterable[SourceDefinition], latest_probes: Mapping[str, object], configured_credentials: Set[str]) -> WavePlan`。
- Produces: 精确包含 41 个唯一 `source_id` 的 `high-value-ai-tech` Profile；后续 Task 4 以其冻结成员计算证据能力指标。

- [ ] **Step 1: 写 41 个目标与 6 个新增来源的失败测试**

将 `tests/waves/test_profile.py` 的宽松数量断言改成精确断言，并加入以下检查：

```python
from newsradar.providers.schema import Availability, CoverageMode

ADDED_EVIDENCE_SOURCE_IDS = frozenset(
    {
        "google-ai-blog",
        "nvidia-developer-blog",
        "universe-cnbc-1",
        "universe-mit-tech-review-1",
        "universe-venturebeat-1",
        "universe-wired-1",
    }
)


def test_high_value_profile_has_exact_evidence_confirmation_scope() -> None:
    profile = load_wave_profile(Path("wave_profiles/high-value-ai-tech.yaml"))
    sources = {source.id: source for source in load_source_tree(Path("sources"))}

    assert len(profile.source_ids) == 41
    assert len(set(profile.source_ids)) == 41
    assert ADDED_EVIDENCE_SOURCE_IDS <= set(profile.source_ids)
    for source_id in ADDED_EVIDENCE_SOURCE_IDS:
        source = sources[source_id]
        assert source.availability is Availability.READY
        assert source.coverage_mode is CoverageMode.DIRECT
        assert "evidence" in {role.value for role in source.roles}
        assert source.ingestion is not None and source.ingestion.enabled is True
        assert source.access_methods
```

在 `tests/waves/test_planning.py` 增加固定成功探测，证明新增来源会成为可抓取成员：

```python
def test_added_evidence_sources_are_fetchable_with_matching_success_probes() -> None:
    profile = load_wave_profile(Path("wave_profiles/high-value-ai-tech.yaml"))
    sources = load_source_tree(Path("sources"))
    added = [source for source in sources if source.id in ADDED_EVIDENCE_SOURCE_IDS]
    probes = {
        source.id: SimpleNamespace(
            access_kind=source.access_methods[0].kind.value,
            outcome="success",
        )
        for source in added
    }

    plan = build_wave_plan(profile, sources, probes, configured_credentials=set())
    by_id = {member.source_id: member for member in plan.members}
    assert all(by_id[source_id].fetchable for source_id in ADDED_EVIDENCE_SOURCE_IDS)
    assert all("evidence" in by_id[source_id].roles for source_id in ADDED_EVIDENCE_SOURCE_IDS)
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/waves/test_profile.py tests/waves/test_planning.py -q`

Expected: FAIL，当前 Profile 只有 35 个成员，6 个新增 ID 尚未全部进入 Profile。

- [ ] **Step 3: 在 Profile 末尾追加固定的 6 个来源**

```yaml
  - google-ai-blog
  - nvidia-developer-blog
  - universe-cnbc-1
  - universe-mit-tech-review-1
  - universe-venturebeat-1
  - universe-wired-1
```

不得修改这 6 个来源 YAML 的 `research.status`，也不得为通过测试伪造新的探测记录。

- [ ] **Step 4: 验证 Profile 与真实 YAML**

Run: `uv run newsradar waves validate --profile wave_profiles/high-value-ai-tech.yaml`

Expected: `Validated wave profile high-value-ai-tech: 41 sources`。

Run: `uv run pytest tests/waves/test_profile.py tests/waves/test_planning.py -q`

Expected: PASS。

- [ ] **Step 5: 提交 Task 1**

```powershell
git add wave_profiles/high-value-ai-tech.yaml tests/waves/test_profile.py tests/waves/test_planning.py
git commit -m "feat: expand evidence confirmation wave profile"
```

---

### Task 2：实现 `cluster-v3` 严格跨来源确定性匹配

**Files:**
- Modify: `src/newsradar/events/clustering.py`
- Modify: `src/newsradar/events/versions.py`
- Modify: `tests/events/test_clustering.py`
- Modify: `tests/events/test_pairing.py`
- Modify: `tests/events/test_operation_snapshots.py`

**Interfaces:**
- Consumes: `ClusterItem`、`candidate_pairs(items)`。
- Produces: `compare_items(left, right) -> ClusterDecision`、`evaluate_pair_rules(left, right) -> PairRuleDecision`，算法版本固定为 `cluster-v3`。
- Task 3 只会对 `PairDecisionKind.MODEL_BOUNDARY` 调用 MiniMax。

- [ ] **Step 1: 写严格语义匹配与误合并失败测试**

在 `tests/events/test_clustering.py` 增加：

```python
def test_cross_publisher_semantic_merge_requires_entity_action_time_and_title() -> None:
    left = item(
        title="OpenAI launches Orion reasoning model",
        publisher_name="Official",
        entities=("organization:openai", "model:orion"),
        published_at=NOW,
    )
    right = item(
        raw_item_id=2,
        title="OpenAI releases new Orion model for developers",
        publisher_name="Media A",
        entities=("organization:openai", "model:orion"),
        published_at=NOW + timedelta(hours=3),
    )

    decision = compare_items(left, right)
    assert decision.matched is True
    assert {"shared_non_generic_entity", "same_action", "within_48_hours", "safe_title_similarity"} <= set(decision.reasons)


def test_same_entity_and_window_with_different_action_stays_separate() -> None:
    left = item(title="Regulator investigates Orion", entities=("model:orion",))
    right = item(
        raw_item_id=2,
        title="OpenAI launches Orion",
        entities=("model:orion",),
        published_at=NOW + timedelta(hours=1),
    )
    assert compare_items(left, right).matched is False


def test_generic_ai_words_never_create_candidate_pair() -> None:
    left = item(raw_item_id=1, title="AI model market grows", entities=("model:ai",))
    right = item(raw_item_id=2, title="AI model safety debate", entities=("model:model",))
    assert candidate_pairs((left, right)) == ()
```

同时加入以下固定样本：48 小时边界、不同产品版本、相同公司不同融资/发布动作、媒体后缀去除、同 Canonical URL 强匹配、相同 repository/paper ID 强匹配。

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/events/test_clustering.py tests/events/test_pairing.py tests/events/test_operation_snapshots.py -q`

Expected: 至少跨媒体标题相似度和 `cluster-v3` 版本断言失败。

- [ ] **Step 3: 实现动作、标题归一化与安全阈值**

在 `src/newsradar/events/clustering.py` 中使用标准库 `difflib.SequenceMatcher`，不增加依赖：

```python
from difflib import SequenceMatcher

CLUSTER_RULE_VERSION = "cluster-v3"
TITLE_SIMILARITY_THRESHOLD = 0.58
MODEL_BOUNDARY_TITLE_THRESHOLD = 0.42

_ACTION_GROUPS = {
    "launch": frozenset({"announce", "announced", "launch", "launches", "launched", "publish", "published", "release", "released", "unveil", "unveiled"}),
    "acquire": frozenset({"acquire", "acquires", "acquired", "acquisition"}),
    "partner": frozenset({"partner", "partners", "partnership"}),
    "fund": frozenset({"funding", "raises", "raised", "investment"}),
    "regulate": frozenset({"regulate", "regulates", "regulated", "regulation", "investigate", "investigates", "investigation", "ban", "bans", "banned"}),
}


def _normalized_title(item: ClusterItem) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", item.title.casefold()).strip()
    publisher = re.sub(r"[^a-z0-9]+", " ", (item.publisher_name or "").casefold()).strip()
    if publisher and text.endswith(f" {publisher}"):
        text = text[: -(len(publisher) + 1)].strip()
    return " ".join(token for token in text.split() if token not in {"the", "a", "an", "new", "report"})


def _title_similarity(left: ClusterItem, right: ClusterItem) -> float:
    return SequenceMatcher(None, _normalized_title(left), _normalized_title(right)).ratio()
```

`compare_items()` 的顺序固定为：

1. Canonical/original URL、repository ID、paper ID 强身份直接匹配；
2. 动作冲突直接分开；
3. 要求共享非泛化实体；
4. 要求相同动作；
5. 要求发布时间差不超过 48 小时；
6. 标题相似度达到 `0.58` 才确定性合并；`0.42–0.58` 仅进入模型边界候选；低于 `0.42` 分开。

`evaluate_pair_rules()` 将 `shared_non_generic_entity` 与 `same_action` 共同视为结构锚点；单独的标题相似、时间接近或通用词重合不能产生结构锚点。

确定性语义合并理由必须包含：

```python
("shared_non_generic_entity", "same_action", "within_48_hours", "safe_title_similarity")
```

共享组织实体可以参与公司融资、收购、合作和监管等事件匹配；若两边都提取到产品/模型/项目/论文等对象实体而对象集合互不相交，则直接分开，避免把同一公司的不同发布合并。

- [ ] **Step 4: 同步消费者算法版本**

将 `src/newsradar/events/versions.py` 修改为：

```python
EVENT_ALGORITHM_VERSIONS = MappingProxyType(
    {
        "relevance": "relevance-v2",
        "newsworthiness": "newsworthiness-v2",
        "entities": "entities-v2",
        "cluster": "cluster-v3",
        "score": "score-v2",
    }
)
```

更新快照测试，确认旧 `cluster-v2` Operation 不会冒充当前算法快照。

- [ ] **Step 5: 运行聚类回归确认 GREEN**

Run: `uv run pytest tests/events/test_clustering.py tests/events/test_pairing.py tests/events/test_operation_snapshots.py -q`

Expected: PASS。

Run: `uv run pytest tests/events -q`

Expected: PASS。

- [ ] **Step 6: 提交 Task 2**

```powershell
git add src/newsradar/events/clustering.py src/newsradar/events/versions.py tests/events/test_clustering.py tests/events/test_pairing.py tests/events/test_operation_snapshots.py
git commit -m "feat: tighten cross-source event clustering"
```

---

### Task 3：将 MiniMax 边界配对收口为 same/different/uncertain 三态

**Files:**
- Modify: `src/newsradar/events/schema.py`
- Modify: `src/newsradar/events/minimax.py`
- Modify: `src/newsradar/events/pairing.py`
- Modify: `src/newsradar/events/pipeline.py`
- Modify: `tests/events/test_minimax.py`
- Modify: `tests/events/test_pairing.py`
- Modify: `tests/events/test_pipeline.py`

**Interfaces:**
- Consumes: Task 2 的 `PairDecisionKind.MODEL_BOUNDARY`。
- Produces: `PairSemanticDecision.decision: Literal["same_event", "different_event", "uncertain"]`、`PipelineResult.ambiguous_pairs_checked`、`PipelineResult.model_pair_fallback_count`。
- Task 4 将两个计数写入 Wave Operation 的 `result_summary`。

- [ ] **Step 1: 写三态与保守降级失败测试**

```python
@pytest.mark.parametrize(
    "semantic",
    [
        PairSemanticDecision(decision="uncertain", confidence=0.9, rationale="insufficient", origin="model"),
        PairSemanticDecision(decision="uncertain", confidence=0.0, rationale="fallback", origin="rule_fallback"),
        None,
    ],
)
def test_uncertain_or_missing_model_result_never_merges(semantic) -> None:
    rule = PairRuleDecision(
        left_raw_item_id=1,
        right_raw_item_id=2,
        score=0.5,
        reasons=("shared_object_entity", "same_action", "within_48_hours"),
        structural_anchor=True,
        kind=PairDecisionKind.MODEL_BOUNDARY,
    )
    assert finalize_pair_decision(rule, semantic, "a" * 64).decision == "separate"


def test_high_confidence_same_event_can_merge_only_anchored_boundary() -> None:
    rule = PairRuleDecision(
        left_raw_item_id=1,
        right_raw_item_id=2,
        score=0.5,
        reasons=("shared_non_generic_entity", "same_action", "within_48_hours"),
        structural_anchor=True,
        kind=PairDecisionKind.MODEL_BOUNDARY,
    )
    semantic = PairSemanticDecision(
        decision="same_event", confidence=0.91, rationale="same release", origin="model"
    )
    assert finalize_pair_decision(rule, semantic, "b" * 64).decision == "merge"
```

在 `tests/events/test_minimax.py` 增加非法 JSON、429、超时和无 Key 均返回 `decision == "uncertain"` 的断言，并检查 prompt 不包含 URL 查询参数、环境变量或完整正文。

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/events/test_minimax.py tests/events/test_pairing.py tests/events/test_pipeline.py -q`

Expected: FAIL，当前响应仍使用 `same_event: bool`，且 Pipeline 未暴露两个新计数。

- [ ] **Step 3: 修改三态 Schema 并保留兼容只读属性**

```python
class PairSemanticDecision(_Schema):
    decision: Literal["same_event", "different_event", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(max_length=500)
    origin: Literal["model", "rule_fallback"] = "rule_fallback"

    @property
    def same_event(self) -> bool:
        return self.decision == "same_event"
```

为 `ClusterItem` 增加只在内存中使用的受限摘要：

```python
class ClusterItem(_Schema):
    # 保留现有字段
    summary: str = Field(default="", max_length=2_000)
```

`EventPipeline._select_and_classify_items()` 从已截断的 `row["summary"]` 赋值，不读取完整正文。

- [ ] **Step 4: 修改 MiniMax 有界上下文与 fallback**

`EventMiniMaxAdapter.compare_candidate_pair()` 的 fallback 固定为：

```python
fallback = PairSemanticDecision(
    decision="uncertain",
    confidence=0,
    rationale="规则回退：语义配对不可用",
    origin="rule_fallback",
)
```

`_context()` 对每条候选最多输出：500 字符标题、1,000 字符摘要、ISO 发布时间、来源性质、发布者、最多 20 个规则实体；URL、metadata、payload 和环境变量不得进入 prompt。

模型返回 `different_event` 时明确分开；只有 `same_event`、`origin == "model"`、`confidence >= 0.85` 且存在结构锚点时合并。

- [ ] **Step 5: 持久化三态含义并增加运行计数**

`PairFinalDecision.model_same_event` 使用现有可空布尔字段表达三态，不增加迁移：

```python
model_same_event = (
    None
    if semantic is None or semantic.decision == "uncertain"
    else semantic.decision == "same_event"
)
```

在 `_resolve_pair_decisions()` 中先计算 `rule = evaluate_pair_rules(left, right)`，再读取缓存；这样缓存命中也能计入本轮边界候选：

```python
if rule.kind is PairDecisionKind.MODEL_BOUNDARY:
    self._pair_metrics["ambiguous_checked"] += 1

if rule.kind is PairDecisionKind.MODEL_BOUNDARY and (
    semantic is None
    or semantic.origin == "rule_fallback"
    or semantic.decision == "uncertain"
):
    self._pair_metrics["model_pair_fallback"] += 1
```

缓存记录的 `model_same_event is None` 同样计为保守回退；`False` 表示模型明确判断不同事件，不计为故障回退。

- [ ] **Step 6: 运行三态与安全回归确认 GREEN**

Run: `uv run pytest tests/events/test_minimax.py tests/events/test_pairing.py tests/events/test_pipeline.py -q`

Expected: PASS。

Run: `uv run pytest tests/test_minimax.py tests/events -q`

Expected: PASS，且无真实网络请求。

- [ ] **Step 7: 提交 Task 3**

```powershell
git add src/newsradar/events/schema.py src/newsradar/events/minimax.py src/newsradar/events/pairing.py src/newsradar/events/pipeline.py tests/events/test_minimax.py tests/events/test_pairing.py tests/events/test_pipeline.py
git commit -m "feat: make model pair decisions fail closed"
```

---

### Task 4：从不可变事件版本计算并保存证据覆盖指标

**Files:**
- Create: `src/newsradar/events/coverage.py`
- Modify: `src/newsradar/events/pipeline.py`
- Modify: `src/newsradar/waves/runtime.py`
- Create: `tests/events/test_coverage.py`
- Modify: `tests/events/test_pipeline.py`
- Modify: `tests/waves/test_runtime.py`

**Interfaces:**
- Produces: `EvidenceCoverageMetrics`、`summarize_event_version_payloads(payloads)`。
- Extends: `PipelineResult` with exact evidence counts and Task 3 pair counts。
- Persists: Wave `result_summary` 中的 8 个规格指标，不增加数据库表或字段。

- [ ] **Step 1: 写证据版本汇总失败测试**

```python
def test_evidence_coverage_counts_exact_event_versions() -> None:
    payloads = (
        {"status": "confirmed", "evidence_summary": {"official_roots": 1, "professional_roots": 0}},
        {"status": "emerging", "evidence_summary": {"official_roots": 0, "professional_roots": 1}},
        {"status": "confirmed", "evidence_summary": {"official_roots": 0, "professional_roots": 2}},
    )
    metrics = summarize_event_version_payloads(payloads)
    assert metrics.events_with_official_root == 1
    assert metrics.events_with_one_professional_root == 1
    assert metrics.events_with_two_professional_roots == 1
    assert metrics.confirmed_event_count == 2
```

加入畸形 payload、布尔伪装数字、负数和缺失 `evidence_summary` 测试；畸形数据按 0 计并不得抛出原始内容。

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/events/test_coverage.py tests/events/test_pipeline.py tests/waves/test_runtime.py -q`

Expected: FAIL，`newsradar.events.coverage` 和新指标尚不存在。

- [ ] **Step 3: 实现纯证据覆盖汇总**

```python
from dataclasses import dataclass
from collections.abc import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class EvidenceCoverageMetrics:
    events_with_official_root: int = 0
    events_with_one_professional_root: int = 0
    events_with_two_professional_roots: int = 0
    confirmed_event_count: int = 0


def summarize_event_version_payloads(
    payloads: Iterable[Mapping[str, object]],
) -> EvidenceCoverageMetrics:
    official = one_professional = two_professional = confirmed = 0
    for payload in payloads:
        summary = payload.get("evidence_summary")
        summary = summary if isinstance(summary, Mapping) else {}
        official_roots = _count(summary.get("official_roots"))
        professional_roots = _count(summary.get("professional_roots"))
        official += int(official_roots > 0)
        one_professional += int(professional_roots == 1)
        two_professional += int(professional_roots >= 2)
        confirmed += int(payload.get("status") == "confirmed")
    return EvidenceCoverageMetrics(official, one_professional, two_professional, confirmed)


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
```

- [ ] **Step 4: 从精确 EventVersion manifest 读取指标**

`EventPipeline` 在 `_publish()` 返回精确 `(event_id, version_number)` 后，用新的短 Session 读取对应 `EventVersionRecord.payload`。如果 manifest 引用不存在，抛出已有 `EventPublicationConflict`，不得回退到 current 指针。

`PipelineResult` 增加：

```python
events_with_official_root: int
events_with_one_professional_root: int
events_with_two_professional_roots: int
confirmed_event_count: int
ambiguous_pairs_checked: int
model_pair_fallback_count: int
```

- [ ] **Step 5: 将成员与事件指标写入 Wave result_summary**

`HighValueWaveHandler._operation_result()` 使用冻结成员计算：

```python
evidence_members = [
    row for row in rows
    if row.fetchable and "evidence" in row.roles_snapshot
]
result_summary.update(
    {
        "evidence_capable_members": len(evidence_members),
        "direct_evidence_fetch_succeeded": sum(row.state == "succeeded" for row in evidence_members),
    }
)
```

`_run_event_stage()` 从 `PipelineResult` 加入：

```python
{
    "events_with_official_root": event_result.events_with_official_root,
    "events_with_one_professional_root": event_result.events_with_one_professional_root,
    "events_with_two_professional_roots": event_result.events_with_two_professional_roots,
    "confirmed_event_count": event_result.confirmed_event_count,
    "ambiguous_pairs_checked": event_result.ambiguous_pairs_checked,
    "model_pair_fallback_count": event_result.model_pair_fallback_count,
}
```

`model_degraded` 同时考虑事件摘要降级和候选对回退，但不能影响 Operation 完成。

- [ ] **Step 6: 运行指标回归确认 GREEN**

Run: `uv run pytest tests/events/test_coverage.py tests/events/test_pipeline.py tests/waves/test_runtime.py -q`

Expected: PASS。

Run: `uv run pytest tests/waves tests/events -q`

Expected: PASS。

- [ ] **Step 7: 提交 Task 4**

```powershell
git add src/newsradar/events/coverage.py src/newsradar/events/pipeline.py src/newsradar/waves/runtime.py tests/events/test_coverage.py tests/events/test_pipeline.py tests/waves/test_runtime.py
git commit -m "feat: persist evidence coverage metrics"
```

---

### Task 5：在现有中文网页和 CLI 中展示确认依据

**Files:**
- Modify: `src/newsradar/web/event_queries.py`
- Modify: `src/newsradar/web/operation_queries.py`
- Modify: `src/newsradar/web/i18n.py`
- Modify: `src/newsradar/web/templates/events_home.html`
- Modify: `src/newsradar/web/templates/event_detail.html`
- Modify: `src/newsradar/web/templates/operation_detail.html`
- Modify: `src/newsradar/waves/reporting.py`
- Modify: `src/newsradar/cli.py`
- Modify: `tests/web/test_event_queries.py`
- Modify: `tests/web/test_high_value_wave_pages.py`
- Modify: `tests/web/test_operation_queries.py`
- Modify: `tests/web/test_event_routes.py`
- Modify: `tests/waves/test_reporting.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 4 的 EventVersion `evidence_summary` 与 Wave `result_summary`。
- Produces: `EventRow.confirmation_summary`、`HighValueWaveMetricsView`、统一中文报告。
- 网页只读取数据库快照，不发起抓取或 MiniMax 调用。

- [ ] **Step 1: 写网页与报告失败测试**

首页/详情测试必须分别覆盖：

```python
assert "已由官方一手来源确认" in confirmed_response.text
assert "已由 2 家独立专业媒体交叉确认" in two_media_response.text
assert "当前有 1 家独立专业媒体，仍缺少 1 个独立媒体证据根" in emerging_response.text
assert "当前仅有聚合/社区发现信号" in aggregator_only_response.text
```

Operation 详情测试写入 allow-listed `result_summary`，断言页面显示 41、证据成员数、直接证据抓取成功数、确认事件数，并断言伪造的 `api_key`、`Authorization` 和 `Cookie` 字段不出现在 HTML。

报告测试断言以下字段存在：

```python
for expected in (
    "证据型成员",
    "直接证据抓取成功",
    "含官方证据根事件",
    "含一个专业媒体根事件",
    "含两个专业媒体根事件",
    "已确认事件",
    "边界候选检查",
    "模型配对保守回退",
):
    assert expected in report
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run pytest tests/web/test_event_queries.py tests/web/test_high_value_wave_pages.py tests/web/test_operation_queries.py tests/web/test_event_routes.py tests/waves/test_reporting.py tests/test_cli.py -q`

Expected: FAIL，新中文字段和运行指标尚未投影。

- [ ] **Step 3: 增加事件确认中文投影**

`EventRow` 增加：

```python
official_root_count: int
professional_root_count: int
confirmation_summary: str
```

`_event_row()` 只从不可变版本的 `evidence_summary` 读取：

```python
def _confirmation_summary(status: str, summary: dict[str, object]) -> str:
    official = _safe_count(summary.get("official_roots"))
    professional = _safe_count(summary.get("professional_roots"))
    if status == "confirmed" and official:
        return "已由官方一手来源确认"
    if status == "confirmed" and professional >= 2:
        return f"已由 {professional} 家独立专业媒体交叉确认"
    if professional == 1:
        return "当前有 1 家独立专业媒体，仍缺少 1 个独立媒体证据根"
    return "当前仅有聚合/社区发现信号，尚无独立确认"


def _safe_count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
```

`src/newsradar/web/i18n.py` 同时接受现有实际代码 `official_or_two_professional_roots`，避免详情页落入泛化文本。

- [ ] **Step 4: 增加 Operation 数字白名单视图**

不得把整个 `result_summary` 传给模板。新增：

```python
@dataclass(frozen=True, slots=True)
class HighValueWaveMetricsView:
    member_total: int
    evidence_capable_members: int
    direct_evidence_fetch_succeeded: int
    events_with_official_root: int
    events_with_one_professional_root: int
    events_with_two_professional_roots: int
    confirmed_event_count: int
    ambiguous_pairs_checked: int
    model_pair_fallback_count: int
```

`OperationDetail` 增加 `wave_metrics: HighValueWaveMetricsView | None`；只在 `operation_type == "high_value_news_wave"` 时从固定键读取非负整数，布尔值、字符串、负数和未知键全部忽略。

- [ ] **Step 5: 修改现有模板，不增加导航**

`events_home.html` 的确认和早期卡片加入：

```jinja2
<p class="metric-note">{{ event.confirmation_summary }}</p>
```

`event_detail.html` 的“展示与确认依据”加入：

```jinja2
<p><strong>{{ event_detail.event.confirmation_summary }}</strong></p>
```

`operation_detail.html` 只在 `wave_metrics` 存在时显示 9 个允许字段；不存在时保持原页面行为。

- [ ] **Step 6: 扩展中文 Wave 报告并保持 CLI 单入口**

`render_high_value_wave_report()` 在“执行范围”后加入“证据确认覆盖”章节，所有数字使用现有 `_safe()`/白名单整数读取。`waves report` 继续调用同一个 renderer，不创建并行报告实现。

- [ ] **Step 7: 运行网页、报告与安全回归确认 GREEN**

Run: `uv run pytest tests/web/test_event_queries.py tests/web/test_high_value_wave_pages.py tests/web/test_operation_queries.py tests/web/test_event_routes.py tests/waves/test_reporting.py tests/test_cli.py -q`

Expected: PASS。

Run: `uv run pytest tests/web tests/waves -q`

Expected: PASS。

- [ ] **Step 8: 提交 Task 5**

```powershell
git add src/newsradar/web/event_queries.py src/newsradar/web/operation_queries.py src/newsradar/web/i18n.py src/newsradar/web/templates/events_home.html src/newsradar/web/templates/event_detail.html src/newsradar/web/templates/operation_detail.html src/newsradar/waves/reporting.py src/newsradar/cli.py tests/web tests/waves/test_reporting.py tests/test_cli.py
git commit -m "feat: show evidence confirmation coverage"
```

---

### Task 6：完成可靠性回归、三轮真实验收和最终审查

**Files:**
- Create: `tests/acceptance/test_evidence_confirmation_coverage.py`
- Modify: `README.md`
- Create after real runs: `reports/evidence-confirmation-coverage-v1-acceptance-2026-07-16.md`

**Interfaces:**
- Consumes: Task 1–5 的完整 Wave → RawItem → EventVersion → Web/Report 闭环。
- Produces: 自动化端到端证据、三轮真实 Operation ID、中文验收报告和可审查分支。

- [ ] **Step 1: 写端到端失败测试**

`tests/acceptance/test_evidence_confirmation_coverage.py` 先定义以下真实数据库辅助函数，不使用未定义的测试替身：

```python
from datetime import UTC, datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    EventRecord,
    OperationRunRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.pipeline import EventPipeline
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS


NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _add_source_and_item(
    session: Session,
    *,
    source_id: str,
    nature: str,
    url: str,
    external_id: str,
) -> None:
    if session.get(SourceDefinitionRecord, source_id) is None:
        session.add(
            SourceDefinitionRecord(
                id=source_id,
                name=source_id,
                status="active",
                nature=nature,
                language="en",
                roles=["evidence"] if nature != "aggregator" else ["discovery"],
                topics=["ai"],
                authority_score=90,
                poll_interval_minutes=60,
                expected_fields=[],
                definition_hash=source_id,
            )
        )
    session.add(
        RawItemRecord(
            source_id=source_id,
            external_id=external_id,
            canonical_url=url,
            payload={},
            title="OpenAI launches Orion reasoning model",
            summary="OpenAI released the Orion reasoning model for developers.",
            published_at=NOW,
        )
    )


def _run(session: Session, operation_id: int):
    session.add(
        OperationRunRecord(
            id=operation_id,
            operation_type="event_pipeline",
            trigger="test",
            status="running",
            requested_scope={
                "window_hours": 24,
                "window_end": NOW.isoformat(),
                "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
            },
            result_summary={},
        )
    )
    session.commit()
    return EventPipeline.production(session).run(
        window_hours=24,
        operation_id=operation_id,
        checkpoint=lambda _: None,
    )
```

随后实现四个场景：

```python
def test_official_item_publishes_confirmed_event():
    with Session(_engine()) as session:
        _add_source_and_item(
            session,
            source_id="official",
            nature="first_party",
            url="https://official.test/orion",
            external_id="official-orion",
        )
        result = _run(session, 1)
    assert result.confirmed_event_count == 1
    assert result.events_with_official_root == 1


def test_two_independent_professional_sources_confirm_one_event():
    with Session(_engine()) as session:
        _add_source_and_item(session, source_id="media-a", nature="professional_media", url="https://a.test/orion", external_id="a-orion")
        _add_source_and_item(session, source_id="media-b", nature="professional_media", url="https://b.test/orion", external_id="b-orion")
        result = _run(session, 1)
    assert result.confirmed_event_count == 1
    assert result.events_with_two_professional_roots == 1


def test_aggregator_and_one_media_remain_emerging():
    with Session(_engine()) as session:
        _add_source_and_item(session, source_id="google-news", nature="aggregator", url="https://news.test/orion", external_id="google-orion")
        _add_source_and_item(session, source_id="media-a", nature="professional_media", url="https://a.test/orion", external_id="a-orion")
        result = _run(session, 1)
    assert result.confirmed_event_count == 0
    assert result.events_with_one_professional_root == 1


def test_later_evidence_upgrades_same_event_without_duplicate():
    with Session(_engine()) as session:
        _add_source_and_item(session, source_id="media-a", nature="professional_media", url="https://a.test/orion", external_id="a-orion")
        first = _run(session, 1)
        first_event_id = first.current_event_ids[0]
        _add_source_and_item(session, source_id="media-b", nature="professional_media", url="https://b.test/orion", external_id="b-orion")
        second = _run(session, 2)
        event = session.get(EventRecord, first_event_id)
        assert second.current_event_ids == (first_event_id,)
        assert event is not None and event.current_version_number == 2
        assert session.scalar(select(func.count()).select_from(EventRecord)) == 1
```

再覆盖：共同 upstream 只计一根、单来源失败不阻塞、取消、deadline、恢复、MiniMax 无 Key 完成和重复执行幂等。

- [ ] **Step 2: 运行自动化验收确认 RED/GREEN**

Run: `uv run pytest tests/acceptance/test_evidence_confirmation_coverage.py -q`

Expected before final fixes: FAIL 于尚未闭合的端到端断言。

完成最小修正后再次运行同一命令。

Expected: PASS。

- [ ] **Step 3: 更新 README 日常入口说明**

在现有“事件情报 v2.1”章节补充：

```markdown
高价值波次当前固定 41 个目标。聚合、社区和社交入口用于发现；官方一手来源或两个独立专业媒体证据根才能把事件升级为“已确认”。运行详情页显示证据型成员、直接证据抓取成功数、确认事件数和 MiniMax 保守回退数。MiniMax 关闭时规则管线仍会完成。
```

- [ ] **Step 4: 运行完整静态和自动化验证**

Run: `uv run ruff check src tests`

Expected: PASS，0 errors。

Run: `uv run pytest`

Expected: PASS，0 failed；允许项目已有的显式 skip 和已知 warning。

Run: `git diff --check`

Expected: 无输出，exit 0。

Run: `rg -n "sk-[A-Za-z0-9_-]+|Authorization:\s*Bearer|Cookie=|DATABASE_URL=.*@|MINIMAX_API_KEY=" src tests README.md docs reports`

Expected: 不出现真实凭据；测试中的固定假值必须只存在于安全脱敏断言上下文。

- [ ] **Step 5: 使用本地安全环境执行三轮真实波次**

保持当前 `newsradar serve --host 127.0.0.1 --port 8766` 的 Worker 正常运行。在 PowerShell 中执行以下有界脚本；它只入队、轮询状态和生成只读报告，不读取或打印 `.env`：

```powershell
$operationIds = @()
1..3 | ForEach-Object {
    $round = $_
    $enqueue = uv run newsradar waves enqueue --profile wave_profiles/high-value-ai-tech.yaml
    if ($LASTEXITCODE -ne 0) { throw "第 $round 轮入队失败" }
    $match = [regex]::Match(($enqueue -join "`n"), '(\d+)\s*$')
    if (-not $match.Success) { throw "第 $round 轮没有返回 Operation ID" }
    $operationId = [int]$match.Groups[1].Value
    $operationIds += $operationId
    $deadline = (Get-Date).AddMinutes(15)
    do {
        Start-Sleep -Seconds 2
        $status = uv run newsradar waves status $operationId
        if ($LASTEXITCODE -ne 0) { throw "无法读取 Operation $operationId" }
        $terminal = ($status -join "`n") -match "高价值新闻波次 $operationId：(succeeded|partial|failed|cancelled|interrupted)"
    } until ($terminal -or (Get-Date) -ge $deadline)
    if (-not $terminal) { throw "Operation $operationId 在 15 分钟内未到终态" }
    uv run newsradar waves report $operationId --output "reports/evidence-confirmation-coverage-v1-round-$round.md"
    if ($LASTEXITCODE -ne 0) { throw "第 $round 轮报告失败" }
}
$operationIds -join ','
```

三轮之间不修改 Profile、来源 YAML、凭据或算法代码。若发生网络波动，如实记录，不通过人工重试美化同一轮结果。

- [ ] **Step 6: 浏览器核对与人工抽查**

使用浏览器检查：

- `http://127.0.0.1:8766/`
- `http://127.0.0.1:8766/events`
- 每轮 Operation 的 `/operations/{operation_id}`
- 每个确认事件的 `/events/{event_id}?operation={operation_id}&version={version_number}`

每轮抽查最多 20 个事件或当轮全部事件（取较小者），记录：误合并、漏合并、转载去重、来源归属、确认依据和页面/报告一致性。浏览器本身不得触发网络抓取。

- [ ] **Step 7: 执行 MiniMax 关闭验收**

先正常停止当前 `newsradar serve` 进程，避免带 Key 的常驻 Worker 抢占此轮 Operation。在不删除本地 Key 的前提下，在同一个 PowerShell 进程中临时覆盖空值、入队并由同一空 Key 环境启动一次 Worker：

```powershell
$previousMiniMaxKey = $env:MINIMAX_API_KEY
try {
    $env:MINIMAX_API_KEY = ''
    $enqueue = uv run newsradar waves enqueue --profile wave_profiles/high-value-ai-tech.yaml
    if ($LASTEXITCODE -ne 0) { throw "MiniMax 关闭轮入队失败" }
    $match = [regex]::Match(($enqueue -join "`n"), '(\d+)\s*$')
    if (-not $match.Success) { throw "MiniMax 关闭轮没有 Operation ID" }
    $operationId = [int]$match.Groups[1].Value
    uv run newsradar worker --once --worker-id minimax-off-acceptance
    if ($LASTEXITCODE -ne 0) { throw "MiniMax 关闭轮 Worker 失败" }
    uv run newsradar waves report $operationId --output reports/evidence-confirmation-coverage-v1-minimax-off.md
    if ($LASTEXITCODE -ne 0) { throw "MiniMax 关闭轮报告失败" }
} finally {
    if ($null -eq $previousMiniMaxKey) {
        Remove-Item Env:MINIMAX_API_KEY -ErrorAction SilentlyContinue
    } else {
        $env:MINIMAX_API_KEY = $previousMiniMaxKey
    }
}
```

确认该 Operation 已由 `minimax-off-acceptance` Worker 消费，并在恢复正常本地服务前检查报告；模型回退不能改变证据结论。

- [ ] **Step 8: 生成最终中文验收报告**

使用 `apply_patch` 创建 `reports/evidence-confirmation-coverage-v1-acceptance-2026-07-16.md`，固定包含：

1. 分支、提交和算法版本；
2. 三轮 Operation ID、冻结 41 个成员与每轮终态；
3. 8 个证据覆盖指标逐轮对比；
4. RawItem/事件新增、重复和升级情况；
5. 人工抽查样本数、误合并、漏合并和转载去重结论；
6. MiniMax 关闭轮结果；
7. 网页、CLI 和报告一致性；
8. 敏感信息扫描结果；
9. 工程验收与数据验收分别判定。

数据验收只有在至少一轮 `confirmed_event_count >= 1`，且每个确认事件均满足官方根或两个独立专业媒体根时才写“通过”。没有自然确认事件时必须写“工程验收通过、数据验收未通过”，并列出证据来源命中率、边界候选数、规则拒绝分布和疑似漏合并样本；不得降低规则后重跑。

- [ ] **Step 9: 提交 Task 6**

```powershell
git add tests/acceptance/test_evidence_confirmation_coverage.py README.md reports/evidence-confirmation-coverage-v1-acceptance-2026-07-16.md
git commit -m "test: accept evidence confirmation coverage v1"
```

- [ ] **Step 10: 最终分支审查**

使用 `superpowers:requesting-code-review` 审查从设计提交父提交到当前 HEAD 的完整差异，重点检查：

- 是否存在聚合/社交/社区来源越权确认；
- 是否存在同 upstream 或同发布者重复计根；
- 是否存在 MiniMax 失败后宽松合并；
- 是否存在跨来源误合并、事件重复或 current 指针污染；
- 是否存在数据库会话跨网络请求、Worker 卡住或恢复覆盖新 claim；
- 是否存在网页/报告输出敏感字段；
- 是否确实保持 41 个冻结目标和三轮真实证据。

修复所有 P0/P1/P2 问题，重新运行 `uv run ruff check src tests`、`uv run pytest` 和 `git diff --check`，再使用 `superpowers:finishing-a-development-branch` 选择合并方式。未经用户明确要求不得推送远端。

---

## 完成定义

- Profile 精确包含 41 个唯一目标，新增 6 个证据来源符合初步接入要求。
- `cluster-v3` 对强身份和跨来源语义匹配给出可审计理由，泛化词和不同动作不误合并。
- MiniMax 三态响应严格 fail-closed，完全关闭时整条规则管线仍可完成。
- Wave Operation 持久化全部 8 个证据覆盖指标，网页、CLI 和报告一致。
- 单来源失败、取消、deadline、恢复和重复执行不造成批次卡住或数据爆炸。
- 三轮真实抓取全部到达终态，并形成完整中文验收报告。
- 至少一轮自然产生真实 `confirmed` 事件；否则明确判定数据验收未通过且不降低阈值。
- 完整测试与 Ruff 通过，最终审查无未解决的 P0/P1/P2 问题。

## 模型使用建议

- 计划审查、聚类阈值与证据边界审查：`5.6 Sol + 高推理`。
- Task 1、4、5 的常规实现与测试：`5.6 Terra + 中推理`。
- Task 2、3 的匹配/安全实现，以及 Task 6 最终分支审查：`5.6 Sol + 高推理`。
