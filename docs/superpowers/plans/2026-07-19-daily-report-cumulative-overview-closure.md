# News Codex 同日累计与情报全览收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让同一北京时间自然日的自动日报合并所有有效归档报告头与当前操作快照，并保证全览统计、正文、播报稿、按需音频使用完全相同的审核后条目集合，同时在页面上清楚区分“最近一次运行”与“今日累计日报”。

**Architecture:** 保留现有不可变日报、事件快照、单一 `supersedes_report_id` 和 Worker 音频架构。仓储层在日级锁内选择所有合格的同日报告头，并仍选其中最新一个作为线性 `supersedes_report_id`；服务层顺序折叠全部报告头后再合并当前操作；查询层建立唯一的 `overview.included` 投影，模板与音频只消费该投影；事件页额外读取一个有界的当日累计上下文，不改变事件页本身的快照口径。

**Tech Stack:** Python 3.12、SQLAlchemy 2、PostgreSQL/SQLite 测试夹具、FastAPI、Jinja2、pytest、Ruff、Alembic、现有 MiniMax T2A Worker。

## Global Constraints

- 不重新抓取来源、不重新聚类、不扩充来源、不调用 MiniMax 决定收录或合法性。
- 不修改数据库结构，不新增 Alembic 迁移，不重写历史日报或历史音频。
- 不读取、输出或提交 `.env`；不触碰主工作区内用户保留的 `reports/*.md`。
- 所有生成继续以完整 `Operation` 事件版本快照为输入；事件首页和全部事件页仍表示最近一次完整运行。
- 当前操作重复提交必须幂等；同日不同窗口共同累计；跨日、已删除、草稿、未来窗口报告不得进入累计基线。
- 任一候选损坏只跳过该候选并记录中文诊断，不得阻断其余候选；累计不得比任一有效头的有效身份集合更小。
- 全览正文、播报稿和音频均不得出现 `exclude`、`duplicate` 或未审核条目，同一事件最多出现一次。
- 每个任务遵循 RED → GREEN → REFACTOR；只提交本计划列出的文件。

---

### Task 1: 在日级锁内选择全部有效归档报告头

**Files:**
- Modify: `src/newsradar/daily_reports/repository.py`
- Test: `tests/daily_reports/test_service.py`

- [ ] **Step 1: 为报告头选择写失败测试**

在 `tests/daily_reports/test_service.py` 增加：

```python
def test_archived_heads_for_day_returns_one_head_per_disconnected_chain(
    db_session: Session,
) -> None:
    chain_a_root = _archived_report(db_session, revision=1)
    chain_a_head = _archived_report(
        db_session, revision=2, supersedes_report_id=chain_a_root.id
    )
    chain_b_head = _archived_report(db_session, revision=3)
    deleted = _archived_report(db_session, revision=4)
    deleted.deleted_at = NOW
    future = _archived_report(db_session, revision=5, window_end=NOW + timedelta(hours=2))
    _archived_report(db_session, report_date=date(2026, 7, 18), revision=1)
    db_session.commit()

    heads = DailyReportRepository(db_session).archived_heads_for_day(
        date(2026, 7, 19),
        excluding_operation_id=9999,
        window_end=NOW + timedelta(hours=1),
    )

    assert [row.id for row in heads] == [chain_a_head.id, chain_b_head.id]
    assert chain_a_root.id not in {row.id for row in heads}
    assert deleted.id not in {row.id for row in heads}
    assert future.id not in {row.id for row in heads}
```

同步调整夹具 `_archived_report`，仅增加计划内测试需要的可选 `supersedes_report_id` 与 `window_end` 参数。再补三条边界测试：排除相同 `source_operation_id`、草稿不入选、不同 `window_hours` 仍入选。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
pytest tests/daily_reports/test_service.py -k "archived_heads_for_day" -q
```

Expected: FAIL，提示 `DailyReportRepository` 尚无 `archived_heads_for_day`。

- [ ] **Step 3: 实现有界报告头查询**

在 `repository.py` 使用 `aliased()` 与 `exists()` 实现以下接口：

```python
def archived_heads_for_day(
    self,
    report_date: date,
    *,
    excluding_operation_id: int,
    window_end: datetime,
) -> tuple[DailyReportRecord, ...]:
    """Return every eligible unsuperseded archived head for one Beijing day."""
```

候选与“替代该候选的子报告”都必须满足：同一 `report_date`、`archived`、未删除、`window_end <= 当前 window_end`、来源操作不等于当前操作。查询结果按 `(window_end, archived_at, generated_at, id)` 从旧到新稳定排序。保留 `latest_archived_for_day` 作为兼容薄封装，从上述结果返回最后一个。

- [ ] **Step 4: 让发布入口返回报告头集合**

把接口改为：

```python
def begin_publication(
    self,
    report_date: date,
    *,
    source_operation_id: int,
    window_end: datetime,
) -> tuple[
    DailyReportRecord | None,
    DailyReportRecord | None,
    tuple[DailyReportRecord, ...],
]:
```

返回值依次为 `existing_draft`、作为标量 `supersedes_report_id` 的最新头、全部基线头。必须先 `_lock_report_day(report_date)`，再选择头集合。更新现有锁顺序测试，断言调用顺序为 `lock -> archived_heads_for_day`。

- [ ] **Step 5: 运行仓储相关测试并确认 GREEN**

Run:

```powershell
pytest tests/daily_reports/test_service.py -k "archived_heads_for_day or latest_archived_for_day or publication_lock" -q
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/newsradar/daily_reports/repository.py tests/daily_reports/test_service.py
git commit -m "feat: select all same-day report heads"
```

### Task 2: 合并多条同日修订链并安全继承审核

**Files:**
- Modify: `src/newsradar/daily_reports/accumulation.py`
- Modify: `src/newsradar/daily_reports/repository.py`
- Modify: `src/newsradar/daily_reports/service.py`
- Test: `tests/daily_reports/test_accumulation.py`
- Test: `tests/daily_reports/test_service.py`
- Test: `tests/daily_reports/test_repository.py`

- [ ] **Step 1: 写 `4 + 2 + 6 - 2 = 10` 的服务失败测试**

在 `tests/daily_reports/test_service.py` 构造两条互不相连的已归档同日报告头：A 包含 `(1,2,3,4)`，B 包含 `(4,5)`；当前完整操作包含 `(5,6,7,8,9,10)`。生成后断言：

```python
assert [row.event_id for row in repository.overview_items(report.id)] == list(range(1, 11))
assert report.supersedes_report_id == chain_b_head.id
assert report.generation_summary["current_operation_event_count"] == 6
assert report.generation_summary["same_day_report_head_count"] == 2
assert report.generation_summary["same_day_historical_candidate_count"] == 6
assert report.generation_summary["merge_input_count"] == 12
assert report.generation_summary["overview_count"] == 10
assert report.generation_summary["inherited_count"] == 4
assert report.generation_summary["deduplicated_count"] == 2
```

再增加：旧修订不重复累计；同一操作再次生成复用原草稿；跨日、未来窗口、删除报告不进入结果；同日 24/48/72 小时仍共同累计。

另增加一个历史头中含损坏 overview snapshot 的测试：只跳过该条目，其余历史与当前条目仍生成成功，并断言 `generation_summary["skipped_invalid_historical_overview_event"] == 1`。

- [ ] **Step 2: 写多头审核优先级和复制失败测试**

在 `tests/daily_reports/test_repository.py` 增加两个头都包含相同事件版本但审核不同的用例，断言较新的头的明确审核被复制到新报告，较旧审核不能覆盖它。另测新头缺失审核时沿用旧头审核。预期新接口：

```python
repository.create_cumulative_draft(
    draft,
    baseline_report_ids=(older_head.id, newer_head.id),
)
```

- [ ] **Step 3: 运行测试并确认 RED**

Run:

```powershell
pytest tests/daily_reports/test_service.py tests/daily_reports/test_repository.py -k "disconnected or baseline_report or same_day" -q
```

Expected: FAIL；当前服务只使用一个 `predecessor`，仓储也只复制一个前序审核。

- [ ] **Step 4: 增加顺序折叠辅助函数**

在 `accumulation.py` 增加：

```python
@dataclass(frozen=True, slots=True)
class DailyOverviewBaseline:
    items: tuple[DailyReportOverviewItemDraft, ...]
    decisions: Mapping[tuple[int, int], EditorialDecision]


def accumulate_daily_overview_baselines(
    baselines: tuple[DailyOverviewBaseline, ...],
    current: tuple[DailyReportOverviewItemDraft, ...],
    *,
    canonical_event_ids: Mapping[int, int],
) -> DailyOverviewAccumulation:
```

按报告头从旧到新调用现有 `accumulate_daily_overview`，并让较新的明确审核覆盖较旧审核、缺失审核不覆盖已有值；最后再合并当前操作。累计统计按身份计算：`inherited_count` 是最终结果中仅来自历史的身份数，`new_count` 是仅由当前操作加入的身份数，`deduplicated_count = merge_input_count - 最终唯一身份数`。保留 `exclude/duplicate` 审计条目的现有 disposition 语义。

- [ ] **Step 5: 改造服务生成摘要与回归保护**

`DailyReportService._generate` 调用 `begin_publication(report_date, source_operation_id=page.snapshot.operation_id, window_end=window_end)`，把每个头的固定 overview 条目与审核组装为 `DailyOverviewBaseline`。对所有涉及的事件 ID 一次调用 `applied_event_survivors`，再折叠。

逐个物化历史条目，只捕获条目级 `TypeError/ValueError/KeyError`；损坏条目跳过并增加中文诊断与计数，数据库异常继续上抛。每个历史快照的复制字典增加：

```python
"daily_accumulation_origin": {
    "report_id": head.id,
    "operation_id": head.source_operation_id,
    "window_end": head.window_end.isoformat(),
}
```

当前操作条目记录对应 operation ID。该诊断只写入新日报的固定快照，不修改原报告。

`generation_summary` 新增且必须为非负整数：

```python
{
    "current_operation_event_count": len(snapshot.event_versions),
    "same_day_report_head_count": len(baseline_heads),
    "same_day_historical_candidate_count": sum(len(head.items) for head in baselines),
    "merge_input_count": historical_input_count + len(overview_drafts),
    "overview_count": len(accumulated.items),
    "inherited_count": accumulated.stats.inherited_count,
    "deduplicated_count": accumulated.stats.deduplicated_count,
    "skipped_invalid_historical_overview_event": skipped_historical_count,
}
```

如果最终规范身份集合不是每个基线头规范身份集合的超集，抛出 `RuntimeError("daily_report_cumulative_regression")`，回滚且不修改历史头。`revise(report_id)` 保持基于被修订归档快照的现有语义，不读取其他日报头。

- [ ] **Step 6: 在同一锁事务内验证全部头并复制审核**

`create_cumulative_draft` 接受 `baseline_report_ids: tuple[int, ...]`。在 `match_or_validate_predecessor` 内按 `draft.window_end` 重查头集合，并要求 ID 元组完全相同；否则抛出 `daily_report_cumulative_chain_changed`。仍把最新头写入 `draft.supersedes_report_id`。

将 `_copy_revision_reviews` 扩展为从 `reversed(baseline_heads)` 复制：目标事件版本已有审核后跳过，因此最新头优先；`duplicate_of_overview_item_id` 继续按事件身份重定向。此处不新增外键或迁移。

- [ ] **Step 7: 运行累计、仓储和服务测试**

Run:

```powershell
pytest tests/daily_reports/test_accumulation.py tests/daily_reports/test_repository.py tests/daily_reports/test_service.py -q
```

Expected: PASS。

- [ ] **Step 8: 提交**

```powershell
git add src/newsradar/daily_reports/accumulation.py src/newsradar/daily_reports/repository.py src/newsradar/daily_reports/service.py tests/daily_reports/test_accumulation.py tests/daily_reports/test_repository.py tests/daily_reports/test_service.py
git commit -m "feat: accumulate every same-day report head"
```

### Task 3: 建立唯一全览收录集合并修复 `2/7` 消失问题

**Files:**
- Modify: `src/newsradar/daily_reports/intelligence.py`
- Modify: `src/newsradar/web/daily_report_queries.py`
- Test: `tests/daily_reports/test_intelligence.py`
- Test: `tests/web/test_daily_report_pages.py`

- [ ] **Step 1: 写展示层级降级失败测试**

在 `tests/daily_reports/test_intelligence.py` 增加 `decision="keep"`、`status="emerging"`、`display_tier="audit_only"` 的条目，断言标题只在播报稿出现一次且位于“新兴信号”。

在 `tests/web/test_daily_report_pages.py` 建立 10 个 overview 候选：8 个 `keep/needs_evidence`（其中至少两个 `display_tier` 缺失或为 `audit_only`）、1 个 `exclude`、1 个 `duplicate`。断言：

```python
assert detail.overview.summary.included_count == 8
assert len(detail.overview.included) == 8
assert sum(map(len, (
    detail.overview.included_confirmed,
    detail.overview.included_hotspots,
    detail.overview.included_signals,
))) == 8
for item in detail.overview.included:
    assert detail.overview.script.count(item.zh_title) == 1
```

同时断言降级条目的 `display_tier == "signal"`，且快照含中文诊断 `全览展示层级缺失或不兼容，已降级为新兴信号。`。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
pytest tests/daily_reports/test_intelligence.py tests/web/test_daily_report_pages.py -k "overview and (fallback or included or tier)" -q
```

Expected: FAIL；合法收录条目仍会因 `audit_only` 从正文和脚本消失。

- [ ] **Step 3: 在查询层规范化唯一收录集合**

在 `daily_report_queries.py` 增加私有函数：

```python
def _normalize_included_overview_item(
    item: DailyReportOverviewItemView,
) -> DailyReportOverviewItemView:
```

规则：`confirmed` 保持确认组；非确认且 tier 为 `hotspot/signal` 保持；其余合法 `keep/needs_evidence` 使用下式复制投影，不修改持久快照：

```python
replace(
    item,
    display_tier="signal",
    snapshot={
        **item.snapshot,
        "overview_display_diagnostic_zh": (
            "全览展示层级缺失或不兼容，已降级为新兴信号。"
        ),
    },
)
```

`_overview_view` 先算并规范化 `included`，随后 `included_confirmed/hotspots/signals`、`summary.included_count` 和 `build_overview_script` 全部只消费这个元组。审计 `items/confirmed/hotspots/signals` 保持原始固定快照投影，不修改数据库。

- [ ] **Step 4: 给脚本构建器增加防御性降级**

把 `_overview_section` 的最后分支从 `return None` 改为：仅当 `decision in {"keep", "needs_evidence"}` 时返回 `"signal"`，否则仍返回 `None`。这保证其他调用方也不会静默丢失已纳入条目。

- [ ] **Step 5: 运行全览查询与脚本测试**

Run:

```powershell
pytest tests/daily_reports/test_intelligence.py tests/web/test_daily_report_pages.py -q
```

Expected: PASS，且既有排除/重复测试不回归。

- [ ] **Step 6: 提交**

```powershell
git add src/newsradar/daily_reports/intelligence.py src/newsradar/web/daily_report_queries.py tests/daily_reports/test_intelligence.py tests/web/test_daily_report_pages.py
git commit -m "fix: keep overview body and script in sync"
```

### Task 4: 证明按需全览音频使用同一集合

**Files:**
- Modify: `src/newsradar/daily_reports/repository.py`
- Modify: `src/newsradar/daily_reports/audio_runtime.py`
- Test: `tests/daily_reports/test_repository.py`
- Test: `tests/daily_reports/test_audio_runtime.py`
- Test: `tests/web/test_daily_report_pages.py`

- [ ] **Step 1: 写音频一致性失败测试**

在 `tests/daily_reports/test_audio_runtime.py` 用 Task 3 的 8/10 场景执行 overview handler，替换 `synthesize` 为捕获脚本文本的 fake。断言 8 个收录标题各一次，排除和重复标题均不存在；生成 artifact 的 `script` 与 `DailyReportQueryService.detail(report.id).overview.script` 完全相等。

在 `tests/daily_reports/test_repository.py` 断言 readiness 的 `included_count == 8`。在页面测试断言按钮附近出现 `将播报全部 8 条已纳入全览的情报；排除和重复项不会播报。`

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
pytest tests/daily_reports/test_audio_runtime.py tests/daily_reports/test_repository.py tests/web/test_daily_report_pages.py -k "overview_audio or overview" -q
```

Expected: 页面范围说明尚不存在；旧查询下脚本数量测试失败。

- [ ] **Step 3: 收紧 readiness 与运行时诊断**

保留现有“所有候选完成审核后才允许生成”的安全门槛。让 `overview_audio_readiness` 的 `included_count` 与查询层定义相同，即最新审核为 `keep/needs_evidence` 的唯一 overview item 数；不得按 display tier 再过滤。`DailyReportAudioHandler` 继续从 `detail.overview.script` 取脚本，并在合成前验证脚本非空；若收录数大于 0 但脚本没有正文，返回不可重试错误 `daily_report_overview_projection_mismatch`，中文消息为 `情报全览统计与播报稿不一致，请先修复日报投影。`。

- [ ] **Step 4: 运行音频相关测试**

Run:

```powershell
pytest tests/daily_reports/test_repository.py tests/daily_reports/test_audio_runtime.py tests/web/test_daily_report_pages.py -k "audio or overview" -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add src/newsradar/daily_reports/repository.py src/newsradar/daily_reports/audio_runtime.py tests/daily_reports/test_repository.py tests/daily_reports/test_audio_runtime.py tests/web/test_daily_report_pages.py
git commit -m "fix: align overview audio with included intelligence"
```

### Task 5: 收敛日报详情页的信息层级

**Files:**
- Modify: `src/newsradar/web/daily_report_queries.py`
- Modify: `src/newsradar/web/templates/daily_report_detail.html`
- Modify: `src/newsradar/web/static/app.css`
- Test: `tests/web/test_daily_report_pages.py`

- [ ] **Step 1: 写页面结构失败测试**

在 `tests/web/test_daily_report_pages.py` 断言页面 DOM 文本顺序：`日报一眼看懂` < `今日决策简报` < `今日情报全览` < `审核与证据附录` < `日报版本与操作`。断言：

- 摘要漏斗展示本次运行、同日历史输入、去重、排除、决策收录、全览收录六个指标；
- 全览音频状态/按钮与确切条数出现在全览标题之后、可信正文之前；
- `审核与证据附录` 使用未设置 `open` 的 `<details>`；
- 页面不再出现独立的 `完整报告与证据` 顶层区块；
- 决策区仅展示决策集合，全览正文仅展示 `overview.included`，附录展示全部候选。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
pytest tests/web/test_daily_report_pages.py -k "overview or complete_report or report_summary" -q
```

Expected: FAIL；当前音频位于正文之后，审计列表未折叠且完整报告重复展示。

- [ ] **Step 3: 扩展只读漏斗投影**

扩展 `DailyReportCoverageView`：

```python
current_operation_event_count: int
same_day_historical_candidate_count: int
merge_input_count: int
deduplicated_count: int
excluded_count: int
overview_included_count: int
```

使用 `_generation_count` 安全读取新摘要字段；旧报告缺失字段时使用现有 `coverage` 和审核统计推导非负回退值，不修改历史记录。

- [ ] **Step 4: 调整模板与最小样式**

日报详情页按设计的五段结构重排：

1. 漏斗指标；
2. 决策简报、稿件、决策音频；
3. 全览标题、范围说明、全览音频、稿件、三组正文；
4. 默认折叠的审核与证据附录；
5. 固定快照、版本、修订、置顶、回收站操作。

把现有 `render_overview_audit_item` 作为附录唯一详情宏；删除底部重复的确认/新兴 `render_item` 全量区块，但保留决策正文所需宏。`app.css` 只增加折叠附录、漏斗和音频范围提示的响应式样式，不更改全站视觉系统。

- [ ] **Step 5: 运行日报页面测试**

Run:

```powershell
pytest tests/web/test_daily_report_pages.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/newsradar/web/daily_report_queries.py src/newsradar/web/templates/daily_report_detail.html src/newsradar/web/static/app.css tests/web/test_daily_report_pages.py
git commit -m "feat: clarify daily report overview layout"
```

### Task 6: 在事件页并列展示最新运行与今日累计

**Files:**
- Modify: `src/newsradar/web/daily_report_queries.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/events_home.html`
- Modify: `src/newsradar/web/templates/events.html`
- Test: `tests/web/test_event_routes.py`
- Test: `tests/web/test_daily_report_pages.py`

- [ ] **Step 1: 写事件页口径失败测试**

在 `tests/web/test_event_routes.py` 创建最新 Operation 的 6 个事件和当日最新非删除日报的 10 个 overview 身份，其中 4 个不在 Operation。分别请求 `/` 与 `/events`，断言：

```text
最新运行事件 6 条 · 今日累计日报 10 条 · 沿用历史 4 条
```

同时断言链接指向该日报 `/daily-reports/{report_id}`，事件列表仍只渲染 Operation 的 6 个事件。再测没有当日日报时不显示累计条，而不是伪造 0 条。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
pytest tests/web/test_event_routes.py -k "cumulative or latest_operation" -q
```

Expected: FAIL；当前路由没有日报累计上下文。

- [ ] **Step 3: 增加有界只读累计上下文**

在 `daily_report_queries.py` 增加：

```python
@dataclass(frozen=True, slots=True)
class DailyCumulativeContextView:
    report_id: int
    operation_event_count: int
    cumulative_event_count: int
    carried_event_count: int


def cumulative_context_for_operation(
    self,
    *,
    operation_id: int,
    window_end: datetime,
) -> DailyCumulativeContextView | None:
```

按 `window_end` 的北京时间日期读取 `window_end <= 当前 operation window_end` 的最新非删除日报（草稿优先展示正在处理版本，否则最新归档版），从固定 overview item 取得日报身份；通过 `event_snapshot_by_id` 读取完整 Operation 版本引用，不能使用首页已截断或已过滤的可见列表计数。使用 `DailyReportRepository.applied_event_survivors` 规范两侧身份后计算集合差：`carried = cumulative_ids - operation_ids`。该方法只读、查询有界、不读取全局 current 目录。

- [ ] **Step 4: 接入两个路由与模板**

`events_home` 在已有同一 session 中获取 `event_home` 后，用 snapshot 的 operation ID 和 window end 获取 context；`/events` 仅在 `scope=latest & visibility=current` 时获取。将 `daily_cumulative` 传给模板并显示并列提示与链接。不得改变 `EventQueryService.latest_operation_page/home` 的列表结果。

- [ ] **Step 5: 运行事件和日报路由测试**

Run:

```powershell
pytest tests/web/test_event_routes.py tests/web/test_event_queries.py tests/web/test_daily_report_pages.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/newsradar/web/daily_report_queries.py src/newsradar/web/app.py src/newsradar/web/templates/events_home.html src/newsradar/web/templates/events.html tests/web/test_event_routes.py tests/web/test_daily_report_pages.py
git commit -m "feat: show daily cumulative context on event pages"
```

### Task 7: 完整验证与真实网页验收

**Files:**
- Modify only if verification exposes an in-scope defect; add the failing regression test first.

- [ ] **Step 1: 运行聚焦回归集**

```powershell
pytest tests/daily_reports/test_accumulation.py tests/daily_reports/test_repository.py tests/daily_reports/test_service.py tests/daily_reports/test_intelligence.py tests/daily_reports/test_audio_runtime.py tests/web/test_daily_report_pages.py tests/web/test_event_queries.py tests/web/test_event_routes.py -q
```

Expected: PASS。

- [ ] **Step 2: 运行完整静态与测试验证**

```powershell
ruff check .
pytest -q
alembic heads
```

Expected: Ruff 无错误；pytest 全部通过（允许仓库既有显式 skip）；Alembic 仍只有既有 head，不新增迁移。

- [ ] **Step 3: 用本地测试数据做真实网页验收**

使用项目现有启动命令在未占用端口启动 Web/Worker；不得读取或打印 `.env`。在浏览器验证：

- 新建等价于两条同日报告头加当前 6 个事件的测试日报，结果为 10 个唯一候选；
- 日报漏斗能解释 `6 + 6 - 2 = 10`；
- 8 个纳入条目时，统计、三组正文、播报稿标题集合均为相同 8 条；
- 全览音频按钮在全览顶部并明确“播报 8 条”；只手动触发一次真实全览音频，确认 artifact 脚本包含相同 8 条；
- `/` 和 `/events` 仍只列最新 6 条，同时提示并链接“今日累计 10 条、沿用历史 4 条”；
- 审核与证据附录默认折叠，展开后能看到 10 个候选、公开原文链接和审核历史；
- 同一 Operation 再次请求生成直接复用同一报告，不新增重复日报；同日后续新 Operation 能继续累计。

- [ ] **Step 4: 检查变更范围**

```powershell
git status --short
git diff --check
git log --oneline --decorate -8
```

Expected: 只有计划内代码、测试和文档；无 `.env`、无用户 `reports/*.md`、无数据库文件、无音频产物。

- [ ] **Step 5: 提交必要的验收修正（如有）**

若无修正，不创建空提交。若有，先加回归测试，再提交：

```powershell
git add src/newsradar/daily_reports/accumulation.py src/newsradar/daily_reports/repository.py src/newsradar/daily_reports/service.py src/newsradar/daily_reports/intelligence.py src/newsradar/daily_reports/audio_runtime.py src/newsradar/web/daily_report_queries.py src/newsradar/web/app.py src/newsradar/web/templates/daily_report_detail.html src/newsradar/web/templates/events_home.html src/newsradar/web/templates/events.html src/newsradar/web/static/app.css tests/daily_reports/test_accumulation.py tests/daily_reports/test_repository.py tests/daily_reports/test_service.py tests/daily_reports/test_intelligence.py tests/daily_reports/test_audio_runtime.py tests/web/test_daily_report_pages.py tests/web/test_event_routes.py tests/web/test_event_queries.py
git commit -m "test: close daily overview acceptance gaps"
```

- [ ] **Step 6: 停止并等待用户决定集成**

汇报测试数量、跳过数量、Ruff、迁移头、真实网页与音频验收结果。未经用户确认，不合并、不推送；推荐下一步模型为 `gpt-5.6-sol`、推理强度 `high`（执行复杂 TDD 与跨层回归），若只做网页目视复验可用 `gpt-5.6-terra`、推理强度 `medium`。
