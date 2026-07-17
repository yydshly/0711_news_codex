# Daily Overview Editorial Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为日报情报全览保存完整候选快照和逐条中文人工审核，只让“保留/需补证”内容进入全览正文与 MiniMax 语音。

**Architecture:** 在现有决策简报数据旁新增独立的全览条目与追加式审核记录，生成日报时固定候选，历史日报在创建修订版时从其绑定的不可变事件操作快照物化。查询层同时输出完整审计清单和经过审核的播报正文；音频入队与 Worker 执行前共同校验全览审核已完成。

**Tech Stack:** Python 3.13、SQLAlchemy 2、Alembic、FastAPI、Jinja2、PostgreSQL/SQLite 测试、pytest、ruff、MiniMax `speech-2.8-hd`、持久 Worker。

## Global Constraints

- 不重新抓取来源，不重新执行事件管线，不修改历史事件、RawItem、来源状态或用户保留报告。
- MiniMax 只做文字转语音，不判断来源合法性、事实可信度或审核结论。
- `keep`、`needs_evidence` 进入正文和语音；`exclude`、`duplicate`、未审核只出现在网页审计清单。
- `needs_evidence` 的正文和语音必须明确提示“尚待进一步确认”并播报中文证据评价。
- 单条失败不能阻塞整份日报；所有现有 Worker 超时、有限重试、取消、心跳、恢复、结构化日志、脱敏和中文诊断保持有效。
- 使用 `codex/daily-overview-editorial-review` 隔离分支；不强制推送；未经用户确认不合并、不推送。
- 不读取、覆盖、暂存或提交根工作区中的用户报告及 `.env`。
- 每项生产代码都遵循 RED → GREEN → REFACTOR；没有先观察到预期失败，不得写对应实现。

---

## File Structure

- `migrations/versions/20260717_0027_daily_report_overview_editorial_reviews.py`：创建全览条目和审核记录两张表，提供 PostgreSQL 升降级。
- `src/newsradar/db/models.py`：定义 `DailyReportOverviewItemRecord` 与 `DailyReportOverviewEditorialReviewRecord` ORM 模型。
- `src/newsradar/daily_reports/schema.py`：定义全览快照 draft、全览审核 draft 及输入边界。
- `src/newsradar/daily_reports/repository.py`：持久化全览条目、保存追加式审核、验证判重归属、复制修订版审核、提供音频就绪状态。
- `src/newsradar/daily_reports/service.py`：从固定事件操作快照物化全览候选；为旧日报创建修订版时补物化。
- `src/newsradar/daily_reports/intelligence.py`：只根据最新人工审核构建可信全览脚本并标注需补证风险。
- `src/newsradar/web/daily_report_queries.py`：投影全览候选、审核历史、汇总、正文和旧日报只读兼容视图。
- `src/newsradar/web/app.py`：新增全览审核 POST 路由和稳定中文错误映射。
- `src/newsradar/web/templates/daily_report_detail.html`：呈现全部候选、审核表单、重复关联、统计与可信正文。
- `src/newsradar/web/static/styles.css`：补充全览审核卡片、长文本换行、状态筛选和窄屏布局。
- `src/newsradar/operations/commands.py`：全览音频入队门禁。
- `src/newsradar/daily_reports/audio_runtime.py`：Worker 执行前二次校验全览脚本就绪。
- `tests/daily_reports/test_overview_migration.py`：迁移升级/降级和约束测试。
- `tests/daily_reports/test_schema.py`：全览审核输入测试。
- `tests/daily_reports/test_repository.py`：持久化、追加审核、判重和修订复制测试。
- `tests/daily_reports/test_service.py`：新日报与历史修订版物化测试。
- `tests/daily_reports/test_intelligence.py`：可信脚本过滤和风险提示测试。
- `tests/web/test_daily_report_pages.py`：查询投影、页面、路由、安全和音频门禁测试。
- `tests/daily_reports/test_audio_runtime.py`：Worker 就绪校验和脚本一致性测试。

---

### Task 1: 全览持久模型与可逆迁移

**Files:**
- Create: `migrations/versions/20260717_0027_daily_report_overview_editorial_reviews.py`
- Create: `tests/daily_reports/test_overview_migration.py`
- Modify: `src/newsradar/db/models.py`

**Interfaces:**
- Produces: `DailyReportOverviewItemRecord`、`DailyReportOverviewEditorialReviewRecord`。
- Produces: 数据库表 `daily_report_overview_items`、`daily_report_overview_editorial_reviews`。
- Consumes: 现有 `daily_reports`、`daily_report_items`、`events` 和迁移头 `20260717_0026`。

- [ ] **Step 1: 写迁移失败测试**

```python
def test_overview_editorial_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'overview.db'}"
    _upgrade(database_url, "20260717_0026")
    _upgrade(database_url, "20260717_0027")
    engine = create_engine(database_url)
    assert {
        "daily_report_overview_items",
        "daily_report_overview_editorial_reviews",
    } <= set(inspect(engine).get_table_names())
    _downgrade(database_url, "20260717_0026")
    assert "daily_report_overview_items" not in inspect(engine).get_table_names()
```

同时写 ORM 约束测试，断言同一日报事件版本、同一日报位置和同一条目审核版本不可重复，`position <= 0` 和非法 `decision` 被数据库拒绝。

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `uv run pytest tests/daily_reports/test_overview_migration.py -q`

Expected: FAIL，原因是迁移 `20260717_0027` 和两个 ORM 模型尚不存在，而不是 fixture 或数据库连接错误。

- [ ] **Step 3: 添加最小 ORM 与迁移实现**

在 `models.py` 添加：

```python
class DailyReportOverviewItemRecord(Base):
    __tablename__ = "daily_report_overview_items"
    __table_args__ = (
        CheckConstraint("position > 0", name="ck_daily_report_overview_position"),
        UniqueConstraint(
            "daily_report_id", "event_id", "event_version_number",
            name="uq_daily_report_overview_event_version",
        ),
        UniqueConstraint(
            "daily_report_id", "position", name="uq_daily_report_overview_position"
        ),
        Index("ix_daily_report_overview_report_position", "daily_report_id", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    daily_report_id: Mapped[int] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )
    event_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    decision_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_report_items.id", ondelete="SET NULL")
    )


class DailyReportOverviewEditorialReviewRecord(Base):
    __tablename__ = "daily_report_overview_editorial_reviews"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_daily_report_overview_review_revision"),
        CheckConstraint(
            "decision IN ('keep', 'needs_evidence', 'exclude', 'duplicate')",
            name="ck_daily_report_overview_review_decision",
        ),
        UniqueConstraint(
            "daily_report_overview_item_id", "revision",
            name="uq_daily_report_overview_review_item_revision",
        ),
        Index(
            "ix_daily_report_overview_reviews_item_revision",
            "daily_report_overview_item_id", "revision",
        ),
    )
```

审核模型的文本字段与现有决策审核模型一致，另含 `duplicate_of_overview_item_id`、`copied_from_editorial_review_id` 和 `created_at` 自引用/时间字段。迁移严格对应 ORM，并以 `down_revision = "20260717_0026"` 创建子表后创建审核表，降级时反序删除。

- [ ] **Step 4: 运行迁移测试并确认通过**

Run: `uv run pytest tests/daily_reports/test_overview_migration.py tests/test_migrations.py -q`

Expected: PASS；Alembic 仅有一个 head，升级和降级都成功。

- [ ] **Step 5: 提交里程碑**

```powershell
git add migrations/versions/20260717_0027_daily_report_overview_editorial_reviews.py src/newsradar/db/models.py tests/daily_reports/test_overview_migration.py
git commit -m "feat: add daily overview review storage"
```

---

### Task 2: 新日报与历史修订版固定全览快照

**Files:**
- Modify: `src/newsradar/daily_reports/schema.py`
- Modify: `src/newsradar/daily_reports/service.py`
- Modify: `src/newsradar/daily_reports/repository.py`
- Modify: `tests/daily_reports/test_service.py`
- Modify: `tests/daily_reports/test_repository.py`

**Interfaces:**
- Produces: `DailyReportOverviewItemDraft(event_id, event_version_number, position, snapshot, decision_event_id)`。
- Produces: `DailyReportDraft.overview_items: tuple[DailyReportOverviewItemDraft, ...]`，默认空元组以兼容旧测试和调用方。
- Produces: `DailyReportRepository.overview_items(report_id)`。
- Produces: `DailyReportRepository.revise(report_id, *, legacy_overview_items=())`。
- Consumes: 现有 `_item_snapshot()`、完成事件操作快照和 `DailyReportRepository.create_draft()`。

- [ ] **Step 1: 写新日报快照和历史修订失败测试**

```python
def test_generate_persists_every_displayable_overview_event_once(db_session: Session) -> None:
    operation = seed_event_snapshot(
        db_session,
        confirmed=1,
        hotspots=2,
        signals=2,
        audit_only=1,
    )
    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    rows = DailyReportRepository(db_session).overview_items(report.id)
    assert [row.snapshot["display_tier"] for row in rows] == [
        "hotspot", "hotspot", "signal", "signal", "audit_only"
    ]
    assert len({(row.event_id, row.event_version_number) for row in rows}) == 5
```

其中 confirmed 即使 `display_tier=audit_only` 也应纳入；emerging + audit_only 不纳入。再写两个测试：单个损坏事件被计入 `skipped_invalid_overview_event` 且其余条目仍保存；旧归档日报没有持久全览行时，`DailyReportService.revise()` 从父日报绑定操作快照物化新修订版且不修改父日报。

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `uv run pytest tests/daily_reports/test_service.py tests/daily_reports/test_repository.py -k "overview or legacy" -q`

Expected: FAIL，原因是 `overview_items` draft、repository 方法和物化逻辑尚不存在。

- [ ] **Step 3: 实现快照 draft 与持久化**

在 `schema.py` 添加：

```python
@dataclass(frozen=True, slots=True)
class DailyReportOverviewItemDraft:
    event_id: int
    event_version_number: int
    position: int
    snapshot: dict[str, Any]
    decision_event_id: int | None = None


@dataclass(frozen=True, slots=True)
class DailyReportDraft:
    report_date: date
    window_hours: int
    window_start: datetime
    window_end: datetime
    source_operation_id: int
    generation_summary: dict[str, Any]
    items: tuple[DailyReportItemDraft, ...]
    overview_items: tuple[DailyReportOverviewItemDraft, ...] = ()
    supersedes_report_id: int | None = None
```

`DailyReportService.generate()` 对完成操作快照中的每个可展示事件只读取一次固定版本详情，使用 `_item_snapshot()` 生成同口径快照；决策版仍按每栏最多 20 条选择，全览版不设该上限。`decision_event_id` 用于 repository 在决策条目 flush 后解析同日报 `decision_item_id`。

`create_draft()` 在日报和决策条目 flush 后写入全览行；`overview_items()` 按 `position, id` 返回。`DailyReportService.revise()` 先检查父日报是否已有全览行；没有则从父日报 `source_operation_id` 的固定快照构造 `legacy_overview_items`，交给 repository 复制。

- [ ] **Step 4: 运行服务和 repository 测试**

Run: `uv run pytest tests/daily_reports/test_service.py tests/daily_reports/test_repository.py -q`

Expected: PASS；现有决策条目数量、排序、幂等、并发修订和快照不可变测试不回归。

- [ ] **Step 5: 提交里程碑**

```powershell
git add src/newsradar/daily_reports/schema.py src/newsradar/daily_reports/service.py src/newsradar/daily_reports/repository.py tests/daily_reports/test_service.py tests/daily_reports/test_repository.py
git commit -m "feat: persist daily overview snapshots"
```

---

### Task 3: 追加式全览审核、判重与修订复制

**Files:**
- Modify: `src/newsradar/daily_reports/schema.py`
- Modify: `src/newsradar/daily_reports/repository.py`
- Modify: `tests/daily_reports/test_schema.py`
- Modify: `tests/daily_reports/test_repository.py`

**Interfaces:**
- Produces: `DailyReportOverviewEditorialReviewDraft.create(*, decision, zh_title, zh_summary, review_recommendation, evidence_assessment, duplicate_of_overview_item_id=None)`。
- Produces: `save_overview_editorial_review(report_id, item_id, draft)`。
- Produces: `overview_editorial_reviews(item_id)`。
- Produces: `OverviewAudioReadiness(total_count, reviewed_count, included_count)` 与 `overview_audio_readiness(report_id)`。
- Consumes: Task 1 的模型和 Task 2 的持久全览条目。

- [ ] **Step 1: 写输入边界和 repository 失败测试**

```python
def test_overview_duplicate_review_requires_same_report_target(db_session: Session) -> None:
    left = seed_report_with_overview(db_session, report_date=date(2026, 7, 16))
    right = seed_report_with_overview(db_session, report_date=date(2026, 7, 17))
    foreign = DailyReportRepository(db_session).overview_items(right.id)[0]
    draft = DailyReportOverviewEditorialReviewDraft.create(
        decision="duplicate",
        zh_title="重复事件",
        zh_summary="与另一候选项描述同一事实。",
        review_recommendation="合并到主事件。",
        evidence_assessment="原始 URL 与发布时间一致。",
        duplicate_of_overview_item_id=foreign.id,
    )
    with pytest.raises(ValueError, match="invalid_daily_report_overview_duplicate_target"):
        DailyReportRepository(db_session).save_overview_editorial_review(
            left.id,
            DailyReportRepository(db_session).overview_items(left.id)[1].id,
            draft,
        )
```

再分别测试：`duplicate` 缺目标、非 duplicate 带目标、自引用、外日报条目、归档日报、四种合法结论、文本空值/超长值、两次保存产生 revision 1/2、父修订只复制最新记录和 `copied_from_editorial_review_id`、就绪统计只把 keep/needs_evidence 计入 `included_count`。

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `uv run pytest tests/daily_reports/test_schema.py tests/daily_reports/test_repository.py -k "overview" -q`

Expected: FAIL，原因是审核 draft 和 repository 接口尚不存在。

- [ ] **Step 3: 实现验证、追加记录和修订复制**

```python
@dataclass(frozen=True, slots=True)
class DailyReportOverviewEditorialReviewDraft:
    decision: EditorialDecision
    zh_title: str
    zh_summary: str
    review_recommendation: str
    evidence_assessment: str
    duplicate_of_overview_item_id: int | None

    @classmethod
    def create(cls, *, decision: str, zh_title: str, zh_summary: str,
               review_recommendation: str, evidence_assessment: str,
               duplicate_of_overview_item_id: int | str | None = None
               ) -> "DailyReportOverviewEditorialReviewDraft":
        try:
            parsed_decision = EditorialDecision(decision)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid_daily_report_editorial_decision") from error
        duplicate_target: int | None = None
        if duplicate_of_overview_item_id not in {None, ""}:
            if isinstance(duplicate_of_overview_item_id, bool):
                raise ValueError("invalid_daily_report_overview_duplicate_target")
            try:
                duplicate_target = int(duplicate_of_overview_item_id)
            except (TypeError, ValueError) as error:
                raise ValueError("invalid_daily_report_overview_duplicate_target") from error
            if duplicate_target <= 0:
                raise ValueError("invalid_daily_report_overview_duplicate_target")
        if parsed_decision is EditorialDecision.DUPLICATE and duplicate_target is None:
            raise ValueError("invalid_daily_report_overview_duplicate_target")
        if parsed_decision is not EditorialDecision.DUPLICATE and duplicate_target is not None:
            raise ValueError("invalid_daily_report_overview_duplicate_target")
        return cls(
            decision=parsed_decision,
            zh_title=_editorial_text(
                zh_title, 240, "invalid_daily_report_editorial_title"
            ),
            zh_summary=_editorial_text(
                zh_summary, 4000, "invalid_daily_report_editorial_summary"
            ),
            review_recommendation=_editorial_text(
                review_recommendation,
                2000,
                "invalid_daily_report_editorial_recommendation",
            ),
            evidence_assessment=_editorial_text(
                evidence_assessment,
                2000,
                "invalid_daily_report_editorial_evidence_assessment",
            ),
            duplicate_of_overview_item_id=duplicate_target,
        )
```

实现时不得保留省略号：完整使用现有 `EditorialDecision` 和 `_editorial_text()`，并为新增错误码返回稳定 ValueError。repository 先调用 `_draft_report()` 获取行锁，再用 `daily_report_id + item_id` 校验归属；duplicate 目标必须属于同日报且不等于当前 item。审核 revision 使用当前最大值加一并追加，不修改 `snapshot`。

`revise()` 在全览行复制完成后，以 `event_id + event_version_number` 对齐父子条目，只复制父条目最新审核；duplicate 目标通过父目标事件键映射到子目标 ID，不能复制父表 ID。

在 repository 同文件定义只读就绪值：

```python
@dataclass(frozen=True, slots=True)
class OverviewAudioReadiness:
    total_count: int
    reviewed_count: int
    included_count: int
```

`overview_audio_readiness()` 一次读取该日报全部全览条目和每条最新审核，`reviewed_count` 统计有审核的条目，`included_count` 只统计最新结论为 `keep` 或 `needs_evidence` 的条目。

- [ ] **Step 4: 运行 schema/repository 全量测试**

Run: `uv run pytest tests/daily_reports/test_schema.py tests/daily_reports/test_repository.py -q`

Expected: PASS；追加历史、并发锁、父子映射和归档不可变全部通过。

- [ ] **Step 5: 提交里程碑**

```powershell
git add src/newsradar/daily_reports/schema.py src/newsradar/daily_reports/repository.py tests/daily_reports/test_schema.py tests/daily_reports/test_repository.py
git commit -m "feat: review daily overview items"
```

---

### Task 4: 可信全览正文与只读查询投影

**Files:**
- Modify: `src/newsradar/daily_reports/intelligence.py`
- Modify: `src/newsradar/web/daily_report_queries.py`
- Modify: `tests/daily_reports/test_intelligence.py`
- Modify: `tests/web/test_daily_report_pages.py`

**Interfaces:**
- Produces: 扩展后的 `OverviewReportItem`，含 `decision`、人工中文字段和证据评价。
- Produces: `DailyReportOverviewEditorialSummaryView`。
- Produces: 扩展后的 `DailyReportOverviewItemView`，含 item ID、固定 snapshot、最新审核、历史、duplicate 目标和 `included_in_decision`。
- Consumes: Task 3 的审核记录和音频就绪统计。

- [ ] **Step 1: 写过滤、风险提示和查询失败测试**

```python
def test_overview_script_only_speaks_reviewed_included_items() -> None:
    script = build_overview_script(
        report_date=date(2026, 7, 17),
        items=(
            overview_item(1, decision="keep", title="保留事件"),
            overview_item(2, decision="needs_evidence", title="待补证事件",
                          evidence_assessment="目前只有聚合来源。"),
            overview_item(3, decision="exclude", title="排除事件"),
            overview_item(4, decision="duplicate", title="重复事件"),
            overview_item(5, decision=None, title="未审核事件"),
        ),
    )
    assert "保留事件" in script
    assert "尚待进一步确认：待补证事件" in script
    assert "证据评价：目前只有聚合来源" in script
    assert all(title not in script for title in ("排除事件", "重复事件", "未审核事件"))
```

查询测试建立 5 个持久全览条目及四类审核，断言候选总数 5、进入 2、需补证 1、排除 1、重复 1、未审核 1；全部 5 条仍在 `overview.items`，但 `overview.script` 只有 2 条。另保留一个旧日报无持久行测试，确认仍能从绑定操作快照只读显示，但 `legacy_unreviewed=True` 且不能被误认作审核完成。

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `uv run pytest tests/daily_reports/test_intelligence.py tests/web/test_daily_report_pages.py -k "overview" -q`

Expected: FAIL，现有脚本仍播报全部候选，查询视图也没有审核字段和汇总。

- [ ] **Step 3: 实现可信脚本和查询投影**

`OverviewReportItem` 改为：

```python
@dataclass(frozen=True, slots=True)
class OverviewReportItem:
    event_id: int
    status: str
    display_tier: str
    rank_score: float
    decision: str | None
    zh_title: str
    zh_summary: str
    why_it_matters: str
    confirmation_summary: str
    recommendation: str | None
    evidence_assessment: str | None
```

`build_overview_script()` 第一层过滤 `decision in {"keep", "needs_evidence"}`；needs_evidence 标题前添加“尚待进一步确认：”，并总是附加证据评价。查询层优先读取 `daily_report_overview_items` 及一次批量查询得到的审核历史，不能产生 N+1 查询。人工字段覆盖展示标题/概述，原 snapshot 始终保留供对照和公开证据展示。

没有持久全览行的历史日报继续走现有操作快照只读 fallback，但所有条目标记为未审核、脚本为空口径，不允许旧 fallback 直接生成新音频。

- [ ] **Step 4: 运行 intelligence 和页面查询测试**

Run: `uv run pytest tests/daily_reports/test_intelligence.py tests/web/test_daily_report_pages.py -k "overview" -q`

Expected: PASS；全部候选可见，正文严格过滤，补证风险提示存在，旧日报仍可浏览。

- [ ] **Step 5: 提交里程碑**

```powershell
git add src/newsradar/daily_reports/intelligence.py src/newsradar/web/daily_report_queries.py tests/daily_reports/test_intelligence.py tests/web/test_daily_report_pages.py
git commit -m "feat: build reviewed overview intelligence"
```

---

### Task 5: 中文全览审核页面与安全表单

**Files:**
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/daily_report_detail.html`
- Modify: `src/newsradar/web/static/styles.css`
- Modify: `tests/web/test_daily_report_pages.py`

**Interfaces:**
- Produces: `POST /daily-reports/{report_id}/overview-items/{item_id}/editorial-reviews`。
- Consumes: `DailyReportOverviewEditorialReviewDraft.create()` 与 `save_overview_editorial_review()`。
- Consumes: Task 4 的 `daily_report.overview.summary`、全览 item view 和 script。

- [ ] **Step 1: 写页面与路由失败测试**

```python
def test_overview_review_post_saves_chinese_content_and_redirects(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report_with_overview(db_session)
    item = DailyReportRepository(db_session).overview_items(report.id)[0]
    client, token = safe_client_with_token(db_session, monkeypatch)
    response = client.post(
        f"/daily-reports/{report.id}/overview-items/{item.id}/editorial-reviews",
        data={
            "action_token": token,
            "decision": "needs_evidence",
            "zh_title": "中文标题",
            "zh_summary": "中文文章概述。",
            "review_recommendation": "继续寻找第一方公告。",
            "evidence_assessment": "目前只有一家聚合来源。",
            "duplicate_of_overview_item_id": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/daily-reports/{report.id}#overview-item-{item.id}"
```

页面 GET 测试断言六个统计、全部候选卡片、中文概述/建议/证据评价、未审核提示、重复目标下拉框、长文本容器和“审核未完成时不展示可用全览音频按钮”。安全测试断言缺 action token、外日报 item、归档日报、HTML 注入和非法 duplicate 目标分别被拒绝或转义。

- [ ] **Step 2: 运行页面测试并确认按预期失败**

Run: `uv run pytest tests/web/test_daily_report_pages.py -k "overview_review or overview_page" -q`

Expected: FAIL，路由 404 或页面缺少审核统计/表单。

- [ ] **Step 3: 实现路由、中文错误和页面布局**

在 `_DAILY_REPORT_ERRORS` 加入：

```python
"daily_report_overview_item_not_found": (404, "全览条目不存在或不属于当前日报。"),
"invalid_daily_report_overview_duplicate_target": (422, "重复项必须关联同一日报中的另一条全览情报。"),
"invalid_daily_report_overview_duplicate_self": (422, "重复项不能关联自身。"),
"daily_report_overview_review_incomplete": (409, "情报全览仍有未审核条目，暂不能生成全览语音。"),
"daily_report_overview_has_no_included_items": (409, "情报全览没有可播报的保留或需补证条目。"),
```

新增路由复用 `require_safe_action()`，解析 draft 后用短事务保存并 303 跳转回条目锚点。模板把“可信全览正文”和“全部候选审核清单”分开：前者只显示收录项，后者始终显示全部候选及审核表单。CSS 必须为标题、概述、建议、证据评价设置 `overflow-wrap:anywhere`、`white-space:pre-wrap`，网格使用 `minmax(0, 1fr)` 并保持移动端单列。

- [ ] **Step 4: 运行完整 Web 日报测试**

Run: `uv run pytest tests/web/test_daily_report_pages.py -q`

Expected: PASS；现有决策版编辑、归档、修订、音频播放和 URL 安全测试不回归。

- [ ] **Step 5: 提交里程碑**

```powershell
git add src/newsradar/web/app.py src/newsradar/web/templates/daily_report_detail.html src/newsradar/web/static/styles.css tests/web/test_daily_report_pages.py
git commit -m "feat: add overview review interface"
```

---

### Task 6: 全览音频双重门禁与 Worker 一致性

**Files:**
- Modify: `src/newsradar/operations/commands.py`
- Modify: `src/newsradar/daily_reports/audio_runtime.py`
- Modify: `tests/web/test_daily_report_pages.py`
- Modify: `tests/daily_reports/test_audio_runtime.py`

**Interfaces:**
- Consumes: `DailyReportRepository.overview_audio_readiness(report_id)`。
- Produces: 入队错误 `daily_report_overview_review_incomplete`、`daily_report_overview_has_no_included_items`。
- Produces: Worker 非重试失败使用相同错误码和中文消息。

- [ ] **Step 1: 写入队和 Worker 失败测试**

```python
def test_overview_audio_enqueue_requires_every_candidate_reviewed(db_session: Session) -> None:
    report = seed_daily_report_with_overview(db_session)
    DailyReportRepository(db_session).archive(report.id)
    with pytest.raises(ValueError, match="daily_report_overview_review_incomplete"):
        OperationCommandService(db_session).enqueue_daily_report_audio(
            report_id=report.id, rendition="overview", trigger="test"
        )
```

再写：全部审核但全是 exclude/duplicate 时拒绝；全部审核且至少一个 keep/needs_evidence 时成功入队；decision 音频不受影响；Worker 收到绕过入队门禁的旧/手工 operation 时二次校验并返回 nonretryable 中文失败；成功 Worker 的 artifact.script 不含排除、重复、未审核标题。

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `uv run pytest tests/web/test_daily_report_pages.py tests/daily_reports/test_audio_runtime.py -k "overview_audio" -q`

Expected: FAIL，现有命令和 Worker 会接受未审核全览。

- [ ] **Step 3: 实现命令与 Worker 双重校验**

`OperationCommandService._enqueue_daily_report_audio()` 在 report 已归档且 `rendition == "overview"` 时读取 readiness：

```python
readiness = DailyReportRepository(self.session).overview_audio_readiness(report_id)
if readiness.reviewed_count != readiness.total_count:
    raise ValueError("daily_report_overview_review_incomplete")
if readiness.included_count == 0:
    raise ValueError("daily_report_overview_has_no_included_items")
```

这里 `total_count == 0` 也归为“审核未完成/历史日报需创建修订版”，不得把空脚本送入 MiniMax。`DailyReportAudioHandler` 在创建 artifact 和调用 synthesize 前执行相同校验；失败通过 `_result()` 返回 `retryable=False`，不创建伪成功音频文件。成功路径仍使用查询层生成的确定性 script 和 SHA-256。

- [ ] **Step 4: 运行音频、命令和 Web 测试**

Run: `uv run pytest tests/daily_reports/test_audio_runtime.py tests/web/test_daily_report_pages.py -q`

Expected: PASS；MiniMax 网络失败、鉴权失败、取消、坏音频、重复入队和决策音频测试均不回归。

- [ ] **Step 5: 提交里程碑**

```powershell
git add src/newsradar/operations/commands.py src/newsradar/daily_reports/audio_runtime.py tests/daily_reports/test_audio_runtime.py tests/web/test_daily_report_pages.py
git commit -m "feat: gate overview audio on review completion"
```

---

### Task 7: 全量自动验证与真实日报 4 验收

**Files:**
- Modify only if a failing acceptance test exposes a defect; write the regression test before its fix.
- Do not modify or stage any file under the protected user report list.

**Interfaces:**
- Consumes: Tasks 1–6 的完整能力。
- Produces: 一个从日报 4 创建的草稿修订版、约 49 条逐项中文审核记录、归档后的可信全览正文和真实 MiniMax 全览音频。

- [ ] **Step 1: 运行目标测试、迁移和静态检查**

Run:

```powershell
uv run pytest tests/daily_reports tests/web/test_daily_report_pages.py tests/test_migrations.py -q
uv run ruff check .
uv run alembic upgrade head
```

Expected: 所有命令 exit 0，无失败、错误或新增警告。若任何命令失败，先写/确认能复现该失败的最小测试，再修复并重跑本步骤全部命令。

- [ ] **Step 2: 运行完整测试套件**

Run: `uv run pytest -q`

Expected: exit 0，0 failed；记录实际 passed/skipped 数量，不沿用历史数字。

- [ ] **Step 3: 重启本地 Web 与 Worker 并核对运行状态**

使用项目现有启动方式重启 `127.0.0.1:8766` 和 `newsradar-local`，然后访问：

```text
GET http://127.0.0.1:8766/daily-reports/4
GET http://127.0.0.1:8766/system-status
```

Expected: HTTP 200；Worker 心跳正常、active operation 为 0；日报 4 仍保持归档和原音频，不被迁移修改。

- [ ] **Step 4: 从日报 4 创建修订版并完成约 49 条人工中文审核**

通过页面“创建修订版”产生新日报，逐条检查固定证据中的原始媒体、原始 URL、发布时间、独立根和重复关系，并填写：中文标题、中文文章概述、审核结论、中文审核建议、中文证据评价。遵守以下判定口径：

- 第一方或两条独立可靠证据一致：`keep`；
- 有价值但只有单一/聚合/间接证据：`needs_evidence`，写明缺少的第一方或独立证据；
- 标题与证据不符、无可验证原文或明显低价值：`exclude`；
- 同一原始事实重复出现：`duplicate` 并关联保留的主条目。

Expected: 候选总数等于物化记录数，未审核数为 0；页面全部候选仍可见；正文只显示 keep/needs_evidence；所有 needs_evidence 都带风险提示。

- [ ] **Step 5: 归档修订版并生成真实全览音频**

先在页面核对正文，再点击“归档定稿”；待自动决策音频任务完成后，点击“生成全览版语音”。轮询现有系统状态页面，不并发重复提交。

Expected: Worker 操作最终 `succeeded`；artifact 模型为 `speech-2.8-hd`；音频 HTTP 200、可播放；artifact 的 script 哈希与页面可信全览脚本一致；语音不含任何 exclude、duplicate、未审核标题。

- [ ] **Step 6: 浏览器视觉验收**

在桌面宽度和窄屏宽度检查新修订版：统计、正文、全部候选清单、审核历史、重复关联、证据 URL、中文长段落换行、音频播放器和失败诊断均可直接阅读，不存在横向滚动或文本重叠。截图记录仅保存在临时验收位置，不加入仓库。

- [ ] **Step 7: 最终差异与保护文件检查**

Run:

```powershell
git status --short
git diff main...HEAD --check
git diff main...HEAD --name-only
```

Expected: 差异只包含本计划列出的代码、测试、迁移、规格和计划；不包含 `.env` 或任何用户保留报告。不得执行 push 或 merge。

- [ ] **Step 8: 处理验收缺陷或确认无需额外提交**

若步骤 1–7 暴露缺陷，回到拥有该行为的 Task，先增加能复现缺陷的失败测试，再使用该 Task 已列出的精确 `git add` 和 `git commit` 命令完成 RED/GREEN/REFACTOR。若没有缺陷，确认 `git status --short` 为空并且不创建空提交。任何情况下不得使用 `git add .`。

---

## Milestone Reporting

只在以下大里程碑完成后统一汇报：

1. Task 1–3：数据、快照、审核与修订闭环；
2. Task 4–6：可信正文、中文页面与音频门禁闭环；
3. Task 7：全量自动验证、真实网页、逐项人工审核和真实语音验收。

每次汇报说明实际测试命令与结果、当前分支/提交、未完成风险和下一里程碑；不推送、不合并。
