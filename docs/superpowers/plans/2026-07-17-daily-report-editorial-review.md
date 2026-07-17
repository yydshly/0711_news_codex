# 中文日报人工审核与编辑覆盖层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 让中文日报草稿可保存并展示可追溯的人工中文概述、审核建议和证据评价，归档后只读且可审计。

**Architecture:** 保持 daily_report_items.snapshot 不变；用新的追加式 daily_report_item_editorial_reviews 表保存每次人工审核。repository 在日报草稿锁内追加记录并同步 included，query service 选择最新审核记录作为页面覆盖层，模板仍从原始快照展示确认状态与证据。

**Tech Stack:** Python 3.12、SQLAlchemy 2、Alembic、FastAPI、Jinja2、pytest、Ruff、PostgreSQL/SQLite test DB。

## Global Constraints

- 不重新抓取来源、不重跑事件、不调用 MiniMax、不新增 Worker 任务。
- 不修改 RawItem、Event、EventVersion、已有证据或 daily_report_items.snapshot。
- emerging 始终显示“尚未确认”，人工审核不得将其升级为 confirmed。
- 仅草稿日报可写；归档日报只能读取和创建修订版。
- 所有写接口复用本机环回、同源检查和一次性动作令牌；文本按模板默认转义。
- 不读取或输出 .env；不改动、暂存或提交 reports/ 下用户文件。
- 所有新增文本均为纯文本并实施长度限制：标题 1–240、概述 1–4,000、审核建议与证据评价各 1–2,000 个字符。
- keep/needs_evidence 同步 included=true；exclude/duplicate 同步 included=false。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| migrations/versions/20260717_0025_daily_report_editorial_reviews.py | 新审核记录表、约束、索引、升级/降级。 |
| src/newsradar/db/models.py | DailyReportItemEditorialReviewRecord ORM 映射。 |
| src/newsradar/daily_reports/schema.py | 审核结论枚举、输入值对象和纯文本校验。 |
| src/newsradar/daily_reports/repository.py | 追加审核记录、读取最新记录、修订版复制。 |
| src/newsradar/web/daily_report_queries.py | 详情页审核记录与历史投影。 |
| src/newsradar/web/app.py | 审核表单 POST 和中文错误映射。 |
| src/newsradar/web/templates/daily_report_detail.html | 审核内容、原始快照对照、历史和草稿表单。 |
| tests/daily_reports/test_schema.py | 结论与文本边界单测。 |
| tests/daily_reports/test_repository.py | 追加、收录同步、归档锁、复制和快照不变测试。 |
| tests/web/test_daily_report_pages.py | 页面、令牌、错误、归档只读测试。 |
| tests/test_migrations.py | 表、约束、索引与升级/降级验收。 |

### Task 1: 审核记录迁移与 ORM

**Files:**

- Create: migrations/versions/20260717_0025_daily_report_editorial_reviews.py
- Modify: src/newsradar/db/models.py:854-901
- Modify: tests/test_migrations.py:190-260
- Test: tests/test_migrations.py

**Interfaces:**

- Produces DailyReportItemEditorialReviewRecord，供 repository 与 query service 查询。
- Produces PostgreSQL 表 daily_report_item_editorial_reviews；每个日报条目的审核 revision 唯一且正数。

- [ ] **Step 1: 写失败的迁移结构测试**

在 tests/test_migrations.py 的日报迁移验收中加入：

~~~python
assert "daily_report_item_editorial_reviews" <= set(inspector.get_table_names())
review_columns = {
    column["name"]
    for column in inspector.get_columns("daily_report_item_editorial_reviews")
}
assert review_columns >= {
    "id", "daily_report_item_id", "revision", "decision", "zh_title",
    "zh_summary", "review_recommendation", "evidence_assessment",
    "created_at", "copied_from_editorial_review_id",
}
review_indexes = {
    index["name"]
    for index in inspector.get_indexes("daily_report_item_editorial_reviews")
}
assert "ix_daily_report_editorial_reviews_item_revision" in review_indexes
~~~

再在迁移的升级/降级测试中断言升级后该表存在、降级回 20260716_0024 后该表不存在。

- [ ] **Step 2: 运行测试并确认其因表不存在而失败**

Run:

~~~powershell
& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests/test_migrations.py -x
~~~

Expected: FAIL，缺少 daily_report_item_editorial_reviews。

- [ ] **Step 3: 新增迁移和 ORM 映射**

在 src/newsradar/db/models.py 的 DailyReportItemRecord 后新增：

~~~python
class DailyReportItemEditorialReviewRecord(Base):
    __tablename__ = "daily_report_item_editorial_reviews"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_daily_report_editorial_revision"),
        CheckConstraint(
            "decision IN ('keep', 'needs_evidence', 'exclude', 'duplicate')",
            name="ck_daily_report_editorial_decision",
        ),
        UniqueConstraint(
            "daily_report_item_id",
            "revision",
            name="uq_daily_report_editorial_item_revision",
        ),
        Index(
            "ix_daily_report_editorial_reviews_item_revision",
            "daily_report_item_id",
            "revision",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    daily_report_item_id: Mapped[int] = mapped_column(
        ForeignKey("daily_report_items.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    zh_title: Mapped[str] = mapped_column(Text, nullable=False)
    zh_summary: Mapped[str] = mapped_column(Text, nullable=False)
    review_recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    copied_from_editorial_review_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_report_item_editorial_reviews.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
~~~

迁移 upgrade() 使用 op.create_table 创建同名字段、两个 check constraint、唯一约束、两个外键和复合索引；downgrade() 先 op.drop_index 再 op.drop_table。迁移头部必须为：

~~~python
revision = "20260717_0025"
down_revision = "20260716_0024"
branch_labels = None
depends_on = None
~~~

- [ ] **Step 4: 运行迁移和模型测试并确认通过**

Run:

~~~powershell
& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests/test_migrations.py -x
~~~

Expected: PASS。

- [ ] **Step 5: 提交迁移边界**

~~~powershell
git add migrations/versions/20260717_0025_daily_report_editorial_reviews.py src/newsradar/db/models.py tests/test_migrations.py
git commit -m "feat: add daily report editorial review storage"
~~~

### Task 2: 审核输入校验与追加式 repository

**Files:**

- Modify: src/newsradar/daily_reports/schema.py:8-48
- Modify: src/newsradar/daily_reports/repository.py:1-246
- Modify: tests/daily_reports/test_schema.py
- Modify: tests/daily_reports/test_repository.py

**Interfaces:**

- Consumes DailyReportItemEditorialReviewRecord。
- Produces EditorialDecision、DailyReportEditorialReviewDraft 和 DailyReportRepository.save_editorial_review()。
- Produces DailyReportRepository.editorial_reviews(item_id)，按 revision 升序返回不可变历史。

- [ ] **Step 1: 写失败的 schema 与 repository 测试**

在 tests/daily_reports/test_schema.py 增加：

~~~python
@pytest.mark.parametrize("value", ("keep", "needs_evidence", "exclude", "duplicate"))
def test_editorial_decision_is_closed(value: str) -> None:
    assert EditorialDecision(value).value == value


def test_editorial_review_draft_trims_and_rejects_invalid_text() -> None:
    review = DailyReportEditorialReviewDraft.create(
        decision="keep", zh_title=" 标题 ", zh_summary=" 概述 ",
        review_recommendation=" 建议 ", evidence_assessment=" 评价 ",
    )
    assert review.zh_title == "标题"
    with pytest.raises(ValueError, match="invalid_daily_report_editorial_title"):
        DailyReportEditorialReviewDraft.create(
            decision="keep", zh_title=" ", zh_summary="概述",
            review_recommendation="建议", evidence_assessment="评价",
        )
~~~

在 tests/daily_reports/test_repository.py 增加：

~~~python
REVIEW_KEEP = DailyReportEditorialReviewDraft.create(
    decision="keep", zh_title="人工标题", zh_summary="人工中文概述",
    review_recommendation="建议保留并继续补证", evidence_assessment="已有公开证据，仍需补充独立来源。",
)
REVIEW_DUPLICATE = DailyReportEditorialReviewDraft.create(
    decision="duplicate", zh_title="重复标题", zh_summary="重复概述",
    review_recommendation="与已收录条目合并重复", evidence_assessment="指向同一原始发布事实。",
)

def test_save_editorial_review_appends_history_syncs_inclusion_and_preserves_snapshot(db_session):
    report = DailyReportRepository(db_session, utcnow=lambda: NOW).create_draft(_draft(db_session))
    item = DailyReportRepository(db_session).items(report.id)[1]
    before = dict(item.snapshot)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    first = repository.save_editorial_review(report.id, item.id, REVIEW_KEEP)
    second = repository.save_editorial_review(report.id, item.id, REVIEW_DUPLICATE)
    assert (first.revision, second.revision) == (1, 2)
    assert [row.decision for row in repository.editorial_reviews(item.id)] == ["keep", "duplicate"]
    assert db_session.get(DailyReportItemRecord, item.id).included is False
    assert db_session.get(DailyReportItemRecord, item.id).snapshot == before
~~~

再增加：归档后 save_editorial_review 抛出 daily_report_archived；外日报 item 抛出 daily_report_item_not_found；revise() 复制最新审核记录而旧记录不变。

- [ ] **Step 2: 运行测试并确认因缺少接口而失败**

Run:

~~~powershell
& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests/daily_reports/test_schema.py tests/daily_reports/test_repository.py -x
~~~

Expected: FAIL，无法导入 EditorialDecision 或 save_editorial_review。

- [ ] **Step 3: 实现输入对象和 repository 方法**

在 schema.py 增加以下闭合枚举和值对象；所有 create() 调用都先去除空白并抛出稳定错误代码：

~~~python
class EditorialDecision(StrEnum):
    KEEP = "keep"
    NEEDS_EVIDENCE = "needs_evidence"
    EXCLUDE = "exclude"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class DailyReportEditorialReviewDraft:
    decision: EditorialDecision
    zh_title: str
    zh_summary: str
    review_recommendation: str
    evidence_assessment: str

    @classmethod
    def create(cls, *, decision: str, zh_title: str, zh_summary: str,
               review_recommendation: str, evidence_assessment: str) -> "DailyReportEditorialReviewDraft":
        try:
            parsed_decision = EditorialDecision(decision)
        except ValueError as error:
            raise ValueError("invalid_daily_report_editorial_decision") from error
        return cls(
            decision=parsed_decision,
            zh_title=_editorial_text(zh_title, 240, "invalid_daily_report_editorial_title"),
            zh_summary=_editorial_text(zh_summary, 4000, "invalid_daily_report_editorial_summary"),
            review_recommendation=_editorial_text(review_recommendation, 2000, "invalid_daily_report_editorial_recommendation"),
            evidence_assessment=_editorial_text(evidence_assessment, 2000, "invalid_daily_report_editorial_evidence_assessment"),
        )
~~~

在 repository 中实现：

~~~python
def save_editorial_review(
    self,
    report_id: int,
    item_id: int,
    draft: DailyReportEditorialReviewDraft,
) -> DailyReportItemEditorialReviewRecord:
    self._draft_report(report_id)
    item = self._owned_item(report_id, item_id)
    revision = int(self.session.scalar(
        select(func.max(DailyReportItemEditorialReviewRecord.revision).where(
            DailyReportItemEditorialReviewRecord.daily_report_item_id == item.id
        )
    ) or 0) + 1
    review = DailyReportItemEditorialReviewRecord(
        daily_report_item_id=item.id, revision=revision, decision=draft.decision.value,
        zh_title=draft.zh_title, zh_summary=draft.zh_summary,
        review_recommendation=draft.review_recommendation,
        evidence_assessment=draft.evidence_assessment, created_at=self._utcnow(),
    )
    item.included = draft.decision in {
        EditorialDecision.KEEP, EditorialDecision.NEEDS_EVIDENCE,
    }
    self.session.add(review)
    self.session.commit()
    return review
~~~

editorial_reviews(item_id) 必须按 revision, id 升序读取；新增私有 _latest_editorial_review(item_id) 按 revision.desc(), id.desc() 返回一条或 None。revise() 在 create_draft() 取得新条目后，逐一找到原条目的最新记录并在新条目写 revision 1，copied_from_editorial_review_id 指向原记录；若父条目无审核记录则不创建复制记录。

- [ ] **Step 4: 运行 repository 测试并确认通过**

Run:

~~~powershell
& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests/daily_reports/test_schema.py tests/daily_reports/test_repository.py -x
~~~

Expected: PASS。

- [ ] **Step 5: 提交审核领域逻辑**

~~~powershell
git add src/newsradar/daily_reports/schema.py src/newsradar/daily_reports/repository.py tests/daily_reports/test_schema.py tests/daily_reports/test_repository.py
git commit -m "feat: append daily report editorial reviews"
~~~

### Task 3: 详情查询投影与只读历史

**Files:**

- Modify: src/newsradar/web/daily_report_queries.py:14-125
- Modify: tests/web/test_daily_report_pages.py:180-248

**Interfaces:**

- Consumes ORM 审核记录。
- Produces DailyReportEditorialReviewView 和扩展后的 DailyReportItemView(editorial_review, editorial_history)。

- [ ] **Step 1: 写失败的详情页查询测试**

在 tests/web/test_daily_report_pages.py 添加：

~~~python
REVIEW_NEEDS_EVIDENCE = DailyReportEditorialReviewDraft.create(
    decision="needs_evidence", zh_title="人工标题", zh_summary="人工中文概述",
    review_recommendation="保留为线索并补充第一方证据", evidence_assessment="现有链接可发现，独立根数仍不足。",
)

def test_daily_report_detail_prefers_latest_editorial_review_but_keeps_snapshot_evidence(db_session, monkeypatch):
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[1]
    DailyReportRepository(db_session, utcnow=lambda: NOW).save_editorial_review(
        report.id, item.id, REVIEW_NEEDS_EVIDENCE
    )
    client, _token = safe_client_with_token(db_session, monkeypatch)
    page = client.get(f"/daily-reports/{report.id}")
    assert "人工审核版本" in page.text
    assert "人工中文概述" in page.text
    assert "中文证据评价" in page.text
    assert "尚未确认" in page.text
    assert 'href="https://example.com/evidence"' in page.text
~~~

并增加未保存审核记录时页面显示“尚未人工审核”、归档页展示历史但没有表单的测试。

- [ ] **Step 2: 运行测试并确认其因缺少 view 字段而失败**

Run:

~~~powershell
& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests/web/test_daily_report_pages.py -x
~~~

Expected: FAIL，页面中没有“人工审核版本”。

- [ ] **Step 3: 实现投影**

在 daily_report_queries.py 定义：

~~~python
@dataclass(frozen=True, slots=True)
class DailyReportEditorialReviewView:
    review_id: int
    revision: int
    decision: str
    zh_title: str
    zh_summary: str
    review_recommendation: str
    evidence_assessment: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DailyReportItemView:
    item_id: int
    event_id: int
    event_version_number: int
    section: str
    position: int
    included: bool
    snapshot: dict[str, object]
    editorial_review: DailyReportEditorialReviewView | None
    editorial_history: tuple[DailyReportEditorialReviewView, ...]
~~~

在 detail() 一次查询日报条目，再一次查询这些条目所有审核记录，按 daily_report_item_id, revision, id 排序并分组。每组最后一项作为 editorial_review，完整组作为 editorial_history；没有记录时两个字段分别为 None 和空元组。不要用 EventRecord 或当前事件指针填充任何展示字段。

- [ ] **Step 4: 运行详情页测试并确认通过**

Run:

~~~powershell
& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests/web/test_daily_report_pages.py -x
~~~

Expected: PASS。

- [ ] **Step 5: 提交只读投影**

~~~powershell
git add src/newsradar/web/daily_report_queries.py tests/web/test_daily_report_pages.py
git commit -m "feat: project daily report editorial reviews"
~~~

### Task 4: 草稿审核表单、中文错误与归档展示

**Files:**

- Modify: src/newsradar/web/app.py:94-110,597-670
- Modify: src/newsradar/web/templates/daily_report_detail.html
- Modify: tests/web/test_daily_report_pages.py

**Interfaces:**

- Consumes DailyReportEditorialReviewDraft.create() 和 DailyReportRepository.save_editorial_review()。
- Produces受保护的 POST /daily-reports/{report_id}/items/{item_id}/editorial-reviews。

- [ ] **Step 1: 写失败的表单和安全测试**

加入以下测试，使用现有 safe_client_with_token()，每个 POST 前重新取 token：

~~~python
EDITORIAL_FORM = {
    "decision": "keep",
    "zh_title": "人工标题",
    "zh_summary": "人工中文概述",
    "review_recommendation": "建议保留并持续补证。",
    "evidence_assessment": "公开证据可追溯，但尚未达到独立确认门槛。",
}

def test_editorial_review_post_requires_token_and_writes_draft(db_session, monkeypatch):
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[1]
    client = TestClient(create_app(), base_url="http://127.0.0.1")
    forbidden = client.post(
        f"/daily-reports/{report.id}/items/{item.id}/editorial-reviews",
        data=EDITORIAL_FORM,
    )
    assert forbidden.status_code == 400
    client, token = safe_client_with_token(db_session, monkeypatch)
    response = client.post(
        f"/daily-reports/{report.id}/items/{item.id}/editorial-reviews",
        data={"action_token": token, **EDITORIAL_FORM}, follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/daily-reports/{report.id}"
~~~

再覆盖：非法结论、空标题、越界概述返回 422 中文错误；归档后 POST 返回 409 中文错误；duplicate 保存后详情页显示“本版未收录”；归档详情页有审核历史、没有“编辑中文审核内容”表单。

- [ ] **Step 2: 运行测试并确认路由不存在**

Run:

~~~powershell
& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests/web/test_daily_report_pages.py -x
~~~

Expected: FAIL，POST 返回 404。

- [ ] **Step 3: 实现路由、错误映射和模板**

在 _DAILY_REPORT_ERRORS 增加以下精确映射：

~~~python
"invalid_daily_report_editorial_decision": (422, "审核结论仅支持保留、待补证、排除或合并重复。"),
"invalid_daily_report_editorial_title": (422, "中文标题不能为空且不能超过 240 个字符。"),
"invalid_daily_report_editorial_summary": (422, "中文文章概述不能为空且不能超过 4000 个字符。"),
"invalid_daily_report_editorial_recommendation": (422, "中文审核建议不能为空且不能超过 2000 个字符。"),
"invalid_daily_report_editorial_evidence_assessment": (422, "中文证据评价不能为空且不能超过 2000 个字符。"),
~~~

新增路由：

~~~python
@app.post("/daily-reports/{report_id}/items/{item_id}/editorial-reviews")
async def save_daily_report_editorial_review(
    request: Request, report_id: int, item_id: int
) -> RedirectResponse:
    values = await require_safe_action(request)
    try:
        draft = DailyReportEditorialReviewDraft.create(
            decision=values.get("decision", ""),
            zh_title=values.get("zh_title", ""),
            zh_summary=values.get("zh_summary", ""),
            review_recommendation=values.get("review_recommendation", ""),
            evidence_assessment=values.get("evidence_assessment", ""),
        )
        with create_session() as session:
            DailyReportRepository(session).save_editorial_review(report_id, item_id, draft)
    except LookupError as error:
        raise _daily_report_http_error(error, default_status=404) from error
    except ValueError as error:
        raise _daily_report_http_error(error, default_status=422) from error
    except SQLAlchemyError as error:
        return database_error_response(request, error)  # type: ignore[return-value]
    return RedirectResponse(url=f"/daily-reports/{report_id}", status_code=303)
~~~

模板对每个条目先计算 review = item.editorial_review。review 存在时使用其标题、概述、审核建议与证据评价，并显示“人工审核版本”；没有时保留原有 snapshot 文案且显示“尚未人工审核”。不论 review 是否存在，证据和“尚未确认”标识仍按原模板快照渲染。

草稿显示 details 审核表单，包含四个结论 option、预填当前审核内容或 snapshot 标题/摘要、四个纯文本 textarea/input，以及 action token。删除现有快速“排除/恢复”表单，只保留上移/下移排序表单；既有 included POST 路由维持兼容但不再由页面调用。归档时不渲染审核表单，改为按 revision 升序显示“审核历史”；所有 Jinja 输出保持默认转义。

- [ ] **Step 4: 运行日报 Web 测试并确认通过**

Run:

~~~powershell
& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests/web/test_daily_report_pages.py -x
~~~

Expected: PASS。

- [ ] **Step 5: 提交网页审核功能**

~~~powershell
git add src/newsradar/web/app.py src/newsradar/web/templates/daily_report_detail.html tests/web/test_daily_report_pages.py
git commit -m "feat: edit daily report editorial reviews"
~~~

### Task 5: 全量验证与真实本地网页验收

**Files:**

- Test: tests/daily_reports, tests/web/test_daily_report_pages.py, tests/test_migrations.py, full suite.

**Interfaces:**

- Consumes完整实现。
- Produces可审计、可人工编辑且归档锁定的日报页面。

- [ ] **Step 1: 运行聚焦质量门禁**

~~~powershell
& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q tests/daily_reports tests/web/test_daily_report_pages.py tests/test_migrations.py
& 'D:\codex_project_work\news_codex\.venv\Scripts\ruff.exe' check src tests migrations
~~~

Expected: 两条命令均 PASS；仅允许既有第三方弃用警告。

- [ ] **Step 2: 运行完整测试与静态检查**

~~~powershell
& 'D:\codex_project_work\news_codex\.venv\Scripts\python.exe' -m pytest -q
& 'D:\codex_project_work\news_codex\.venv\Scripts\ruff.exe' check .
~~~

Expected: PASS；如测试超过一次 60 秒等待窗口，使用条件轮询获取完成输出，不以固定 sleep 代替。

- [ ] **Step 3: 真实网页验收（不归档）**

使用迁移后的本地服务和浏览器/HTTP 客户端：

1. 打开 /daily-reports/1，确认仍为草稿；
2. 为三条保留项保存中文标题、中文概述、keep/needs_evidence 审核结论、审核建议和证据评价；
3. 为高盛金额项保存 exclude 及“金额口径无法由高盛原始材料确认”；
4. 为重复 Codex 项保存 duplicate 及“与 Codex Micro 为同一事件”；
5. 刷新页面，确认人工审核内容、原始证据、emerging 的“尚未确认”、收录/排除状态和审核历史均正确；
6. 不点击“归档定稿”。

验收过程不得触发来源抓取、事件运行或模型调用；仅写 daily_report_item_editorial_reviews 和既有 daily_report_items.included。

- [ ] **Step 4: 核对最终变更集**

~~~powershell
git status --short
git diff --check
~~~

Expected: 只有本计划 Task 1–4 已提交的迁移、审核领域、查询、网页和测试变更；不得出现 reports/、.env 或无关文件。

## Plan Self-Review

- [ ] 数据迁移、ORM、schema、repository、查询、路由、模板、修订复制、测试和真实网页验收均有对应任务。
- [ ] 所有新增接口名、表名、错误码和字段名在前置任务中定义，后续任务一致复用。
- [ ] 所有生产行为先写失败测试，再实现并运行通过测试。
- [ ] 计划不包含抓取、模型调用、推送、定时任务、推荐或来源扩充。
