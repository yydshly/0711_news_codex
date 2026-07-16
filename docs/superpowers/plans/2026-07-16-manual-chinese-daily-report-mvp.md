# 手动中文日报 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用最近一次完整事件运行快照，手动生成、整理、归档和回看一份严格区分“已确认要闻”与“未确认线索”的中文日报。

**Architecture:** 新增独立 `newsradar.daily_reports` 包，负责日报状态、持久化和从现有不可变事件快照生成固定条目；现有事件、抓取和模型管线保持不变。网页路由只调用日报服务与只读查询，归档页面永远读取 `daily_report_items.snapshot`，不跟随 Event current 指针。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL/SQLite 测试、Jinja2、pytest、Ruff。

## Global Constraints

- 不重新探测或抓取来源，不增加 Provider 或 Target。
- 不重新运行事件聚类、合并、确认或模型增强。
- 不调用 MiniMax 或其他外部模型；规则中文回退内容可直接进入日报。
- 日报只读取最近一次完整、读者可见的事件运行快照，不得回退到全局 current 目录。
- `confirmed` 与 `emerging` 必须严格分区；每条 `emerging` 必须用文字标注“尚未确认”。
- 时间窗口只允许 `24`、`48`、`72` 小时，默认 `24`；日期显示使用 `Asia/Shanghai`，数据库时间保存为 UTC。
- 每个分区最多 20 条；确认区不足时不得用线索补齐。
- 草稿只能排除、恢复、在同一分区排序和归档；不得编辑事件内容或跨分区移动。
- 归档日报不可修改；调整必须创建带 `supersedes_report_id` 的新修订版。
- 日报操作不得修改 `Event`、`EventVersion`、`RawItem` 或来源证据。
- 单条事件损坏不得阻塞整份日报；无完整事件快照时不得创建空日报。
- 只保存公开、清洗后的 `http`/`https` 证据 URL；不保存 Cookie、凭据、提示词、模型原始响应或错误正文。
- 所有写端点复用现有 loopback、same-origin 和一次性动作令牌保护。
- 不修改、暂存或提交用户保留的 `reports/` 文件；不读取或输出 `.env` 密钥。
- 未经用户确认不得合并或推送，不得强制推送。

---

## File Structure

- Create `migrations/versions/20260716_0023_daily_reports.py`：日报表、索引、外键和约束。
- Modify `src/newsradar/db/models.py`：`DailyReportRecord`、`DailyReportItemRecord` ORM。
- Create `src/newsradar/daily_reports/__init__.py`：公开接口出口。
- Create `src/newsradar/daily_reports/schema.py`：状态枚举、允许窗口和纯数据类型。
- Create `src/newsradar/daily_reports/repository.py`：草稿、条目顺序、归档、修订和并发约束。
- Create `src/newsradar/daily_reports/service.py`：读取完整事件快照、选择事件、复制安全快照。
- Create `src/newsradar/web/daily_report_queries.py`：列表和详情只读视图。
- Modify `src/newsradar/web/app.py`：日报 GET/POST 路由，保持薄路由。
- Modify `src/newsradar/web/templates/base.html`：增加“中文日报”导航。
- Create `src/newsradar/web/templates/daily_reports.html`：生成表单和存档列表。
- Create `src/newsradar/web/templates/daily_report_detail.html`：固定日报、草稿操作和归档视图。
- Create `tests/daily_reports/test_schema.py`：纯选择和输入边界。
- Create `tests/daily_reports/test_repository.py`：状态机和修订持久化。
- Create `tests/daily_reports/test_service.py`：完整快照生成、分区、证据清洗和降级。
- Create `tests/web/test_daily_report_pages.py`：路由、CSRF、中文标记和无网络副作用。
- Modify `tests/test_migrations.py`：迁移升级、降级和历史事件保留。

---

### Task 1: 日报表、ORM 与纯类型

**Files:**
- Create: `migrations/versions/20260716_0023_daily_reports.py`
- Modify: `src/newsradar/db/models.py`
- Create: `src/newsradar/daily_reports/__init__.py`
- Create: `src/newsradar/daily_reports/schema.py`
- Create: `tests/daily_reports/test_schema.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Consumes: 现有 `OperationRunRecord`、`EventRecord` 和 UTC 时间字段约定。
- Produces: `ReportStatus`、`ReportSection`、`ALLOWED_WINDOW_HOURS`、`DailyReportRecord`、`DailyReportItemRecord`，供后续 repository/service 使用。

- [ ] **Step 1: 写纯类型和迁移失败测试**

在 `tests/daily_reports/test_schema.py` 创建：

```python
import pytest

from newsradar.daily_reports.schema import (
    ALLOWED_WINDOW_HOURS,
    ReportSection,
    ReportStatus,
    validate_window_hours,
)


def test_daily_report_enums_and_windows_are_closed() -> None:
    assert ALLOWED_WINDOW_HOURS == frozenset({24, 48, 72})
    assert ReportStatus.DRAFT.value == "draft"
    assert ReportStatus.ARCHIVED.value == "archived"
    assert ReportSection.CONFIRMED.value == "confirmed"
    assert ReportSection.EMERGING.value == "emerging"
    assert validate_window_hours(24) == 24

    for invalid in (0, 12, 25, 96, True, "24"):
        with pytest.raises(ValueError, match="invalid_daily_report_window"):
            validate_window_hours(invalid)  # type: ignore[arg-type]
```

在 `tests/test_migrations.py` 增加：

```python
def test_daily_report_migration_creates_archive_tables_without_changing_events(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path / "daily-reports.db")
    _upgrade(database_url, "20260716_0022")
    before = _seed_event_history(database_url)

    _upgrade(database_url, "head")

    engine = create_engine(database_url)
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert {"daily_reports", "daily_report_items"} <= set(inspector.get_table_names())
        report_columns = {column["name"] for column in inspector.get_columns("daily_reports")}
        item_columns = {column["name"] for column in inspector.get_columns("daily_report_items")}
        assert {
            "report_date", "timezone", "window_hours", "window_start", "window_end",
            "source_operation_id", "status", "revision", "supersedes_report_id",
            "generation_summary", "generated_at", "archived_at",
        } <= report_columns
        assert {
            "daily_report_id", "event_id", "event_version_number", "section",
            "position", "included", "snapshot",
        } <= item_columns
        after = {
            table_name: connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()
            for table_name in ("events", "event_versions", "event_items", "event_scores")
        }
        assert after == before


def test_daily_report_migration_downgrade_removes_only_report_tables(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "daily-reports-downgrade.db")
    _upgrade(database_url, "head")
    engine = create_engine(database_url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "20260716_0022")
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "daily_reports" not in tables
        assert "daily_report_items" not in tables
        assert {"events", "event_versions", "event_items", "event_scores"} <= tables
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q tests/daily_reports/test_schema.py tests/test_migrations.py::test_daily_report_migration_creates_archive_tables_without_changing_events -x
```

Expected: FAIL，原因是 `newsradar.daily_reports` 或迁移 `20260716_0023` 尚不存在。

- [ ] **Step 3: 实现纯类型**

在 `src/newsradar/daily_reports/schema.py` 实现：

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any


ALLOWED_WINDOW_HOURS = frozenset({24, 48, 72})
MAX_ITEMS_PER_SECTION = 20
REPORT_TIMEZONE = "Asia/Shanghai"


class ReportStatus(StrEnum):
    DRAFT = "draft"
    ARCHIVED = "archived"


class ReportSection(StrEnum):
    CONFIRMED = "confirmed"
    EMERGING = "emerging"


def validate_window_hours(value: int) -> int:
    if isinstance(value, bool) or value not in ALLOWED_WINDOW_HOURS:
        raise ValueError("invalid_daily_report_window")
    return value


@dataclass(frozen=True, slots=True)
class DailyReportItemDraft:
    event_id: int
    event_version_number: int
    section: ReportSection
    position: int
    snapshot: dict[str, Any]
    included: bool = True


@dataclass(frozen=True, slots=True)
class DailyReportDraft:
    report_date: date
    window_hours: int
    window_start: datetime
    window_end: datetime
    source_operation_id: int
    generation_summary: dict[str, Any]
    items: tuple[DailyReportItemDraft, ...]
    supersedes_report_id: int | None = None
```

在 `src/newsradar/daily_reports/__init__.py` 只导出稳定公共符号：

```python
from .schema import (
    ALLOWED_WINDOW_HOURS,
    MAX_ITEMS_PER_SECTION,
    REPORT_TIMEZONE,
    DailyReportDraft,
    DailyReportItemDraft,
    ReportSection,
    ReportStatus,
    validate_window_hours,
)

__all__ = [
    "ALLOWED_WINDOW_HOURS",
    "MAX_ITEMS_PER_SECTION",
    "REPORT_TIMEZONE",
    "DailyReportDraft",
    "DailyReportItemDraft",
    "ReportSection",
    "ReportStatus",
    "validate_window_hours",
]
```

- [ ] **Step 4: 实现迁移和 ORM**

创建 `migrations/versions/20260716_0023_daily_reports.py`，使用：

```python
"""Add immutable manual Chinese daily report archives."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0023"
down_revision = "20260716_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_operation_id",
            sa.Integer(),
            sa.ForeignKey("operation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "supersedes_report_id",
            sa.Integer(),
            sa.ForeignKey("daily_reports.id", ondelete="RESTRICT"),
        ),
        sa.Column("generation_summary", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("window_hours IN (24, 48, 72)", name="ck_daily_report_window"),
        sa.CheckConstraint("status IN ('draft', 'archived')", name="ck_daily_report_status"),
        sa.CheckConstraint("revision > 0", name="ck_daily_report_revision"),
        sa.UniqueConstraint(
            "report_date", "window_hours", "revision", name="uq_daily_report_revision"
        ),
    )
    op.create_index(
        "ix_daily_reports_date_status", "daily_reports", ["report_date", "status"]
    )
    op.create_table(
        "daily_report_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "daily_report_id",
            sa.Integer(),
            sa.ForeignKey("daily_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_version_number", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "section IN ('confirmed', 'emerging')", name="ck_daily_report_item_section"
        ),
        sa.CheckConstraint("position > 0", name="ck_daily_report_item_position"),
        sa.UniqueConstraint(
            "daily_report_id",
            "event_id",
            "event_version_number",
            name="uq_daily_report_event_version",
        ),
        sa.UniqueConstraint(
            "daily_report_id", "section", "position", name="uq_daily_report_position"
        ),
    )
    op.create_index(
        "ix_daily_report_items_report_section",
        "daily_report_items",
        ["daily_report_id", "section", "position"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_report_items_report_section", table_name="daily_report_items")
    op.drop_table("daily_report_items")
    op.drop_index("ix_daily_reports_date_status", table_name="daily_reports")
    op.drop_table("daily_reports")
```

在 `src/newsradar/db/models.py` 增加与迁移完全一致的两个 ORM 类；使用 `date`、`Boolean`、`CheckConstraint` 导入，并保证：

```python
class DailyReportRecord(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (
        CheckConstraint("window_hours IN (24, 48, 72)", name="ck_daily_report_window"),
        CheckConstraint("status IN ('draft', 'archived')", name="ck_daily_report_status"),
        CheckConstraint("revision > 0", name="ck_daily_report_revision"),
        UniqueConstraint("report_date", "window_hours", "revision", name="uq_daily_report_revision"),
        Index("ix_daily_reports_date_status", "report_date", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_operation_id: Mapped[int] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="RESTRICT")
    )
    generation_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

`DailyReportItemRecord` 使用以下完整定义，`included` 同时设置 Python 默认和数据库默认：

```python
class DailyReportItemRecord(Base):
    __tablename__ = "daily_report_items"
    __table_args__ = (
        CheckConstraint(
            "section IN ('confirmed', 'emerging')", name="ck_daily_report_item_section"
        ),
        CheckConstraint("position > 0", name="ck_daily_report_item_position"),
        UniqueConstraint(
            "daily_report_id",
            "event_id",
            "event_version_number",
            name="uq_daily_report_event_version",
        ),
        UniqueConstraint(
            "daily_report_id", "section", "position", name="uq_daily_report_position"
        ),
        Index(
            "ix_daily_report_items_report_section",
            "daily_report_id",
            "section",
            "position",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    daily_report_id: Mapped[int] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )
    event_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    included: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
```

- [ ] **Step 5: 运行迁移和纯类型测试**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q tests/daily_reports/test_schema.py tests/test_migrations.py -x
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add migrations/versions/20260716_0023_daily_reports.py src/newsradar/db/models.py src/newsradar/daily_reports/__init__.py src/newsradar/daily_reports/schema.py tests/daily_reports/test_schema.py tests/test_migrations.py
git commit -m "feat: add daily report archive schema"
```

---

### Task 2: 草稿、排序、归档与修订状态机

**Files:**
- Create: `src/newsradar/daily_reports/repository.py`
- Create: `tests/daily_reports/test_repository.py`

**Interfaces:**
- Consumes: `DailyReportDraft`、`DailyReportRecord`、`DailyReportItemRecord`。
- Produces: `DailyReportRepository.create_draft()`、`set_included()`、`move_item()`、`archive()`、`revise()`。

- [ ] **Step 1: 写状态机失败测试**

在 `tests/daily_reports/test_repository.py` 建立确定性工厂；它创建外键所需的 Operation/Event 行，并返回一条 confirmed 和两条 emerging：

```python
NOW = datetime(2026, 7, 16, 4, tzinfo=UTC)


def _draft(session, *, report_date: date = date(2026, 7, 16)) -> DailyReportDraft:
    operation_id = int(report_date.strftime("%m%d"))
    if session.get(OperationRunRecord, operation_id) is None:
        session.add(
            OperationRunRecord(
                id=operation_id,
                operation_type="event_pipeline",
                trigger="test",
                status="succeeded",
                requested_scope={},
                result_summary={},
                created_at=NOW,
                finished_at=NOW,
            )
        )
    base_event_id = operation_id * 10
    for event_id, status in (
        (base_event_id + 1, "confirmed"),
        (base_event_id + 2, "emerging"),
        (base_event_id + 3, "emerging"),
    ):
        if session.get(EventRecord, event_id) is None:
            session.add(
                EventRecord(
                    id=event_id,
                    canonical_key=f"daily-report-test-{event_id}",
                    status=status,
                    current_version_number=1,
                    occurred_at=NOW,
                )
            )
    session.commit()
    return DailyReportDraft(
        report_date=report_date,
        window_hours=24,
        window_start=NOW - timedelta(hours=24),
        window_end=NOW,
        source_operation_id=operation_id,
        generation_summary={"confirmed_count": 1, "emerging_count": 2},
        items=tuple(
            DailyReportItemDraft(
                event_id=event_id,
                event_version_number=1,
                section=ReportSection(status),
                position=position,
                snapshot={"zh_title": f"事件 {event_id}", "status": status},
            )
            for event_id, status, position in (
                (base_event_id + 1, "confirmed", 1),
                (base_event_id + 2, "emerging", 1),
                (base_event_id + 3, "emerging", 2),
            )
        ),
    )
```

然后覆盖：

```python
def test_create_draft_is_idempotent_while_same_draft_exists(db_session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    first = repository.create_draft(_draft(db_session))
    second = repository.create_draft(_draft(db_session))
    assert second.id == first.id
    assert db_session.scalar(select(func.count()).select_from(DailyReportRecord)) == 1


def test_draft_can_toggle_and_move_only_inside_its_section(db_session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    report = repository.create_draft(_draft(db_session))
    confirmed, first_signal, second_signal = repository.items(report.id)

    repository.set_included(report.id, first_signal.id, included=False)
    repository.move_item(report.id, second_signal.id, direction="up")

    rows = repository.items(report.id)
    assert [row.event_id for row in rows if row.section == "confirmed"] == [confirmed.event_id]
    assert [row.event_id for row in rows if row.section == "emerging"] == [
        second_signal.event_id,
        first_signal.event_id,
    ]
    assert next(row for row in rows if row.id == first_signal.id).included is False


def test_archived_report_rejects_mutation_and_revision_copies_snapshots(db_session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = repository.create_draft(_draft(db_session))
    archived = repository.archive(original.id)

    with pytest.raises(ValueError, match="daily_report_archived"):
        repository.set_included(archived.id, repository.items(archived.id)[0].id, included=False)

    revision = repository.revise(archived.id)
    assert revision.status == "draft"
    assert revision.revision == archived.revision + 1
    assert revision.supersedes_report_id == archived.id
    assert [row.snapshot for row in repository.items(revision.id)] == [
        row.snapshot for row in repository.items(archived.id)
    ]
```

再加入以下具名测试和精确断言：

```python
def test_repository_rejects_invalid_move_and_foreign_item(db_session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    left = repository.create_draft(_draft(db_session, report_date=date(2026, 7, 16)))
    right = repository.create_draft(_draft(db_session, report_date=date(2026, 7, 17)))
    foreign_item = repository.items(right.id)[0]
    with pytest.raises(ValueError, match="invalid_daily_report_move"):
        repository.move_item(left.id, repository.items(left.id)[0].id, direction="sideways")
    with pytest.raises(LookupError, match="daily_report_item_not_found"):
        repository.set_included(left.id, foreign_item.id, included=False)


def test_repository_rejects_revision_of_draft_and_reuses_existing_revision(db_session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    draft = repository.create_draft(_draft(db_session))
    with pytest.raises(ValueError, match="daily_report_must_be_archived"):
        repository.revise(draft.id)
    archived = repository.archive(draft.id)
    first = repository.revise(archived.id)
    second = repository.revise(archived.id)
    assert second.id == first.id


def test_move_at_section_boundary_is_a_no_op(db_session) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    report = repository.create_draft(_draft(db_session))
    first = next(row for row in repository.items(report.id) if row.section == "emerging")
    before = [(row.id, row.position) for row in repository.items(report.id)]
    repository.move_item(report.id, first.id, direction="up")
    assert [(row.id, row.position) for row in repository.items(report.id)] == before
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q tests/daily_reports/test_repository.py -x
```

Expected: FAIL，原因是 `DailyReportRepository` 尚不存在。

- [ ] **Step 3: 实现 repository 创建与幂等规则**

在 `src/newsradar/daily_reports/repository.py` 实现：

```python
class DailyReportRepository:
    def __init__(self, session: Session, *, utcnow: Callable[[], datetime] | None = None) -> None:
        self.session = session
        self._utcnow = utcnow or (lambda: datetime.now(UTC))

    def create_draft(self, draft: DailyReportDraft) -> DailyReportRecord:
        validate_window_hours(draft.window_hours)
        report_date = draft.report_date
        self._lock_revision(report_date, draft.window_hours)
        existing = self.session.scalar(
            select(DailyReportRecord).where(
                DailyReportRecord.report_date == report_date,
                DailyReportRecord.window_hours == draft.window_hours,
                DailyReportRecord.source_operation_id == draft.source_operation_id,
                DailyReportRecord.status == ReportStatus.DRAFT.value,
                DailyReportRecord.supersedes_report_id == draft.supersedes_report_id,
            )
        )
        if existing is not None:
            return existing
        revision = int(
            self.session.scalar(
                select(func.max(DailyReportRecord.revision)).where(
                    DailyReportRecord.report_date == report_date,
                    DailyReportRecord.window_hours == draft.window_hours,
                )
            )
            or 0
        ) + 1
        report = DailyReportRecord(
            report_date=report_date,
            timezone=REPORT_TIMEZONE,
            window_hours=draft.window_hours,
            window_start=draft.window_start,
            window_end=draft.window_end,
            source_operation_id=draft.source_operation_id,
            status=ReportStatus.DRAFT.value,
            revision=revision,
            supersedes_report_id=draft.supersedes_report_id,
            generation_summary=draft.generation_summary,
            generated_at=self._utcnow(),
        )
        self.session.add(report)
        self.session.flush()
        self.session.add_all(
            DailyReportItemRecord(
                daily_report_id=report.id,
                event_id=item.event_id,
                event_version_number=item.event_version_number,
                section=item.section.value,
                position=item.position,
                included=item.included,
                snapshot=item.snapshot,
            )
            for item in draft.items
        )
        self.session.commit()
        return report
```

`_lock_revision()` 在 PostgreSQL 执行固定 advisory lock：

```python
self.session.execute(
    text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
    {"key": f"newsradar:daily-report:{report_date.isoformat()}:{window_hours}"},
)
```

SQLite 测试不执行 advisory lock，唯一约束仍作为最终并发防线。

- [ ] **Step 4: 实现草稿状态转换**

实现以下精确方法；`_draft_report()` 与 `_owned_item()` 先完成归属和状态校验：

```python
def items(self, report_id: int) -> tuple[DailyReportItemRecord, ...]:
    records = self.session.scalars(
        select(DailyReportItemRecord)
        .where(DailyReportItemRecord.daily_report_id == report_id)
        .order_by(
            case((DailyReportItemRecord.section == "confirmed", 0), else_=1),
            DailyReportItemRecord.position,
            DailyReportItemRecord.id,
        )
    )
    return tuple(records)

def set_included(
    self, report_id: int, item_id: int, *, included: bool
) -> DailyReportItemRecord:
    self._draft_report(report_id)
    item = self._owned_item(report_id, item_id)
    item.included = included
    self.session.commit()
    return item

def move_item(
    self, report_id: int, item_id: int, *, direction: str
) -> tuple[DailyReportItemRecord, ...]:
    if direction not in {"up", "down"}:
        raise ValueError("invalid_daily_report_move")
    self._draft_report(report_id)
    item = self._owned_item(report_id, item_id)
    section_rows = [row for row in self.items(report_id) if row.section == item.section]
    index = next(index for index, row in enumerate(section_rows) if row.id == item.id)
    target_index = index - 1 if direction == "up" else index + 1
    if target_index < 0 or target_index >= len(section_rows):
        return self.items(report_id)
    adjacent = section_rows[target_index]
    item_position, adjacent_position = item.position, adjacent.position
    temporary_position = max(row.position for row in section_rows) + 1
    item.position = temporary_position
    self.session.flush()
    adjacent.position = item_position
    self.session.flush()
    item.position = adjacent_position
    self.session.commit()
    return self.items(report_id)

def archive(self, report_id: int) -> DailyReportRecord:
    report = self._draft_report(report_id)
    report.status = ReportStatus.ARCHIVED.value
    report.archived_at = self._utcnow()
    self.session.commit()
    return report

def revise(self, report_id: int) -> DailyReportRecord:
    original = self.session.get(DailyReportRecord, report_id)
    if original is None:
        raise LookupError("daily_report_not_found")
    if original.status != ReportStatus.ARCHIVED.value:
        raise ValueError("daily_report_must_be_archived")
    return self.create_draft(
        DailyReportDraft(
            report_date=original.report_date,
            window_hours=original.window_hours,
            window_start=original.window_start,
            window_end=original.window_end,
            source_operation_id=original.source_operation_id,
            generation_summary=dict(original.generation_summary),
            supersedes_report_id=original.id,
            items=tuple(
                DailyReportItemDraft(
                    event_id=row.event_id,
                    event_version_number=row.event_version_number,
                    section=ReportSection(row.section),
                    position=row.position,
                    snapshot=dict(row.snapshot),
                    included=row.included,
                )
                for row in self.items(original.id)
            ),
        )
    )
```

规则：

- `_draft_report(report_id)` 对不存在返回 `LookupError("daily_report_not_found")`，对归档返回 `ValueError("daily_report_archived")`；
- `_owned_item(report_id, item_id)` 禁止跨日报修改；
- `move_item` 只接受 `up`、`down`，只与同 section 相邻条目交换；使用临时负 position 避免唯一约束碰撞，再写回连续的 `1..N`；
- `archive` 只允许 draft，设置 `status="archived"` 和 `archived_at` 后提交；
- `revise` 只允许 archived；若已存在 `supersedes_report_id == original.id` 的 draft，直接返回；否则复制原日报和全部 item 快照到新 draft，不重新读取 Event。

- [ ] **Step 5: 运行 repository 测试**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q tests/daily_reports/test_repository.py -x
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/newsradar/daily_reports/repository.py tests/daily_reports/test_repository.py
git commit -m "feat: add daily report draft lifecycle"
```

---

### Task 3: 从完整事件快照生成安全日报

**Files:**
- Create: `src/newsradar/daily_reports/service.py`
- Modify: `src/newsradar/daily_reports/__init__.py`
- Create: `tests/daily_reports/test_service.py`

**Interfaces:**
- Consumes: `latest_complete_event_snapshot()`、`EventQueryService.latest_operation_page()`、`EventQueryService.get_operation_event()`、`DailyReportRepository.create_draft()`。
- Produces: `DailyReportService.generate(window_hours, now=None)` 和 `DailyReportService.revise(report_id)`。

- [ ] **Step 1: 写生成规则失败测试**

在 `tests/daily_reports/test_service.py` 使用现有事件测试工厂创建一个完整 Operation 快照，包含：

- 2个窗口内 confirmed；
- 2个窗口内 `signal/hotspot` emerging；
- 1个 `audit_only` emerging；
- 1个窗口外事件；
- 1个缺失事件时间的事件；
- 1个证据 URL 带查询参数；
- 1个规则回退中文事件。

测试文件定义以下本地工厂，不从其他测试模块导入私有 helper：

```python
NOW = datetime(2026, 7, 16, 4, tzinfo=UTC)
SEEDED_WINDOW_END = NOW
SEEDED_OPERATION_ID = 2301
BROKEN_EVENT_ID = 202


def _seed_snapshot_event(
    session,
    *,
    event_id: int,
    status: str,
    display_tier: str,
    rank_score: float,
    occurred_at: datetime | None,
    enrichment_origin: str = "model",
) -> None:
    event_time = occurred_at or NOW
    event = EventRecord(
        id=event_id,
        canonical_key=f"daily-snapshot-{event_id}",
        visibility="current",
        display_tier=display_tier,
        rank_score=rank_score,
        status=status,
        occurred_at=occurred_at,
        current_version_number=1,
    )
    raw = RawItemRecord(
        source_id="github-openai-python",
        external_id=f"daily-evidence-{event_id}",
        canonical_url=f"https://example.com/evidence/{event_id}?token=hidden",
        original_url=f"https://example.com/evidence/{event_id}?token=hidden#fragment",
        payload={},
        title=f"证据 {event_id}",
        published_at=event_time,
    )
    session.add_all((event, raw))
    session.flush()
    payload = {
        "status": status,
        "category": "product_model",
        "publication": {"tier": display_tier},
        "enrichment": {
            "why_it_matters": "影响行业采用路径。",
            "limitations": [],
            "origin": enrichment_origin,
        },
        "evidence_summary": {
            "official_roots": 1 if status == "confirmed" else 0,
            "professional_roots": 0,
        },
        "evidence": [
            {
                "raw_item_id": raw.id,
                "role": "official",
                "root_evidence_key": f"official:{event_id}",
                "independent": True,
                "limitations": [],
            }
        ],
    }
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at.isoformat()
    session.add_all(
        (
            EventVersionRecord(
                event_id=event_id,
                version_number=1,
                zh_title=f"事件 {event_id}",
                zh_summary="固定中文摘要",
                payload=payload,
                created_at=NOW,
            ),
            EventItemRecord(event_id=event_id, raw_item_id=raw.id, added_version_number=1),
            EventScoreRecord(
                event_id=event_id,
                version_number=1,
                heat=rank_score,
                breakdown={
                    "ai_relevance": 90,
                    "source_coverage": 70,
                    "source_authority": 90,
                    "recency": 100,
                    "engagement_velocity": 0,
                    "novelty": 70,
                    "importance": rank_score,
                    "credibility": 90,
                    "heat": rank_score,
                    "rule_version": "score-v2",
                    "reasons": ["official_evidence"],
                },
                created_at=NOW,
            ),
        )
    )


def seed_complete_snapshot(
    session,
    *,
    confirmed: tuple[int, ...] = (101, 102),
    emerging: tuple[int, ...] = (201, 202),
) -> int:
    refs: list[tuple[int, int]] = []
    for index, event_id in enumerate(confirmed):
        _seed_snapshot_event(
            session,
            event_id=event_id,
            status="confirmed",
            display_tier="hotspot",
            rank_score=95 - index,
            occurred_at=NOW - timedelta(hours=index + 1),
        )
        refs.append((event_id, 1))
    for index, event_id in enumerate(emerging):
        _seed_snapshot_event(
            session,
            event_id=event_id,
            status="emerging",
            display_tier="signal",
            rank_score=85 - index,
            occurred_at=NOW - timedelta(hours=index + 1),
            enrichment_origin="rule_fallback" if index == 0 else "model",
        )
        refs.append((event_id, 1))
    for event_id, tier, occurred_at in (
        (301, "audit_only", NOW - timedelta(hours=1)),
        (302, "signal", NOW - timedelta(hours=25)),
        (303, "signal", None),
    ):
        _seed_snapshot_event(
            session,
            event_id=event_id,
            status="emerging",
            display_tier=tier,
            rank_score=70,
            occurred_at=occurred_at,
        )
        refs.append((event_id, 1))
    session.add(
        OperationRunRecord(
            id=SEEDED_OPERATION_ID,
            operation_type="event_pipeline",
            trigger="test",
            status="succeeded",
            requested_scope={
                "window_hours": 72,
                "window_end": NOW.isoformat(),
                "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
            },
            result_summary={
                "event_version_snapshots": [
                    {"event_id": event_id, "version_number": version}
                    for event_id, version in refs
                ]
            },
            created_at=NOW,
            finished_at=NOW,
        )
    )
    session.commit()
    return SEEDED_OPERATION_ID


def seed_ranked_snapshot(session, *, confirmed_count: int, emerging_count: int) -> None:
    seed_complete_snapshot(
        session,
        confirmed=tuple(range(1001, 1001 + confirmed_count)),
        emerging=tuple(range(2001, 2001 + emerging_count)),
    )
```

核心断言：

```python
def test_generate_freezes_confirmed_and_emerging_in_separate_sections(db_session) -> None:
    seed_complete_snapshot(db_session)
    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    rows = DailyReportRepository(db_session).items(report.id)

    confirmed = [row for row in rows if row.section == "confirmed"]
    emerging = [row for row in rows if row.section == "emerging"]
    assert [row.snapshot["status"] for row in confirmed] == ["confirmed", "confirmed"]
    assert all(row.snapshot["status"] == "emerging" for row in emerging)
    assert all(row.snapshot["unconfirmed"] is True for row in emerging)
    assert all(row.snapshot["unconfirmed"] is False for row in confirmed)
    assert all(row.snapshot["display_tier"] != "audit_only" for row in emerging)
    assert report.source_operation_id == SEEDED_OPERATION_ID
    assert report.window_end == SEEDED_WINDOW_END


def test_generate_sanitizes_evidence_and_never_calls_network_or_model(
    db_session, monkeypatch
) -> None:
    seed_complete_snapshot(db_session)
    monkeypatch.setattr("httpx.Client.request", lambda *args, **kwargs: pytest.fail("network"))
    monkeypatch.setattr("httpx.AsyncClient.request", lambda *args, **kwargs: pytest.fail("network"))
    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    evidence = DailyReportRepository(db_session).items(report.id)[0].snapshot["evidence"]
    assert all("?" not in (item["url"] or "") for item in evidence)
    assert all("#" not in (item["url"] or "") for item in evidence)
```

再增加这些具名测试：

```python
def test_generate_requires_complete_snapshot_and_writes_nothing(db_session) -> None:
    with pytest.raises(ValueError, match="complete_event_snapshot_required"):
        DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    assert db_session.scalar(select(func.count()).select_from(DailyReportRecord)) == 0


def test_generate_allows_empty_sections_without_lowering_threshold(db_session) -> None:
    seed_complete_snapshot(db_session, confirmed=(), emerging=())
    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    assert DailyReportRepository(db_session).items(report.id) == ()


def test_generate_caps_each_section_and_keeps_stable_order(db_session) -> None:
    seed_ranked_snapshot(db_session, confirmed_count=25, emerging_count=25)
    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    rows = DailyReportRepository(db_session).items(report.id)
    for section in ("confirmed", "emerging"):
        selected = [row for row in rows if row.section == section]
        assert len(selected) == 20
        assert [row.position for row in selected] == list(range(1, 21))
        assert [row.snapshot["rank_score"] for row in selected] == sorted(
            (row.snapshot["rank_score"] for row in selected), reverse=True
        )


def test_generate_skips_invalid_detail_and_records_rule_fallback(db_session, monkeypatch) -> None:
    seed_complete_snapshot(db_session)
    original = EventQueryService.get_operation_event
    monkeypatch.setattr(
        EventQueryService,
        "get_operation_event",
        lambda self, event_id, *args, **kwargs: None
        if event_id == BROKEN_EVENT_ID
        else original(self, event_id, *args, **kwargs),
    )
    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    assert report.generation_summary["skipped_invalid_event"] == 1
    assert report.generation_summary["skipped_missing_time"] == 1
    assert report.generation_summary["minimax_degraded"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q tests/daily_reports/test_service.py -x
```

Expected: FAIL，原因是 `DailyReportService` 尚不存在。

- [ ] **Step 3: 实现选择和安全 URL 函数**

在 `src/newsradar/daily_reports/service.py` 实现纯函数：

```python
def _public_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _selected_rows(rows: tuple[EventRow, ...], section: ReportSection) -> tuple[EventRow, ...]:
    return tuple(
        row
        for row in rows
        if row.status == section.value
        and (
            section is ReportSection.CONFIRMED
            or row.display_tier in {"hotspot", "signal"}
        )
    )


def _snapshot_missing_time_count(session: Session, snapshot: OperationSnapshotRef) -> int:
    refs = {(ref.event_id, ref.version_number) for ref in snapshot.event_versions}
    if not refs:
        return 0
    versions = session.scalars(
        select(EventVersionRecord).where(
            EventVersionRecord.event_id.in_({event_id for event_id, _ in refs})
        )
    )
    missing = 0
    for version in versions:
        if (version.event_id, version.version_number) not in refs:
            continue
        payload = version.payload if isinstance(version.payload, dict) else {}
        raw = payload.get("occurred_at")
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            missing += 1
            continue
        if parsed.tzinfo is None:
            missing += 1
    return missing
```

`latest_operation_page()` 已按 `rank_score`、`occurred_at`、`event_id` 稳定排序；调用时传 `{"hours": window_hours, "limit": 1000}`，不得自行使用当前时间窗口。

- [ ] **Step 4: 实现固定条目快照和 generate**

实现：

```python
class DailyReportService:
    def __init__(self, session: Session, *, utcnow: Callable[[], datetime] | None = None) -> None:
        self.session = session
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._events = EventQueryService(session)
        self._reports = DailyReportRepository(session, utcnow=self._utcnow)

    def generate(self, window_hours: int, *, now: datetime | None = None) -> DailyReportRecord:
        checked_at = now or self._utcnow()
        window_hours = validate_window_hours(window_hours)
        page = self._events.latest_operation_page(
            {"hours": window_hours, "limit": 1000}, now=checked_at
        )
        if page is None:
            raise ValueError("complete_event_snapshot_required")
        snapshot = event_snapshot_by_id(
            self.session, page.snapshot.operation_id, now=checked_at
        )
        if snapshot is None:
            raise ValueError("complete_event_snapshot_required")
        skipped_missing_time = _snapshot_missing_time_count(self.session, snapshot)
        version_by_event = {
            ref.event_id: ref.version_number
            for ref in snapshot.event_versions
        }
        drafts: list[DailyReportItemDraft] = []
        skipped_invalid = 0
        for section in (ReportSection.CONFIRMED, ReportSection.EMERGING):
            section_position = 0
            for row in _selected_rows(page.events, section):
                if section_position >= MAX_ITEMS_PER_SECTION:
                    break
                version_number = version_by_event.get(row.event_id)
                detail = (
                    self._events.get_operation_event(
                        row.event_id,
                        page.snapshot.operation_id,
                        version_number,
                        now=checked_at,
                    )
                    if version_number is not None
                    else None
                )
                if detail is None:
                    skipped_invalid += 1
                    continue
                section_position += 1
                drafts.append(
                    DailyReportItemDraft(
                        event_id=row.event_id,
                        event_version_number=version_number,
                        section=section,
                        position=section_position,
                        snapshot=_item_snapshot(detail, section),
                    )
                )
        window_end = page.snapshot.window_end
        report_date = window_end.astimezone(ZoneInfo(REPORT_TIMEZONE)).date()
        return self._reports.create_draft(
            DailyReportDraft(
                report_date=report_date,
                window_hours=window_hours,
                window_start=window_end - timedelta(hours=window_hours),
                window_end=window_end,
                source_operation_id=page.snapshot.operation_id,
                generation_summary={
                    "confirmed_count": sum(item.section is ReportSection.CONFIRMED for item in drafts),
                    "emerging_count": sum(item.section is ReportSection.EMERGING for item in drafts),
                    "skipped_invalid_event": skipped_invalid,
                    "skipped_missing_time": skipped_missing_time,
                    "minimax_degraded": any(
                        item.snapshot["enrichment_origin"] != "model" for item in drafts
                    ),
                },
                items=tuple(drafts),
            )
        )

    def revise(self, report_id: int) -> DailyReportRecord:
        return self._reports.revise(report_id)
```

实现 `_item_snapshot(detail, section)`，固定返回以下键，禁止额外复制完整 payload：

```python
{
    "zh_title": detail.event.zh_title,
    "zh_summary": detail.event.zh_summary,
    "why_it_matters": detail.why_it_matters,
    "status": detail.event.status,
    "unconfirmed": section is ReportSection.EMERGING,
    "display_tier": detail.event.display_tier,
    "category": detail.event.category,
    "rank_score": detail.event.rank_score,
    "occurred_at": detail.event.occurred_at.isoformat() if detail.event.occurred_at else None,
    "independent_root_count": detail.event.independent_root_count,
    "confirmation_summary": detail.event.confirmation_summary,
    "enrichment_origin": detail.event.enrichment_origin,
    "limitations": list(detail.limitations),
    "evidence": [
        {
            "title": item.title,
            "url": _public_url(item.original_url),
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "role": item.role,
            "independent": item.independent,
            "limitations": list(item.limitations),
        }
        for item in detail.evidence
    ],
}
```

在 `src/newsradar/daily_reports/__init__.py` 增加 `DailyReportService` 出口。

- [ ] **Step 5: 运行 service 与前序测试**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q tests/daily_reports tests/web/test_event_queries.py tests/events/test_operation_snapshots.py -x
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/newsradar/daily_reports/__init__.py src/newsradar/daily_reports/service.py tests/daily_reports/test_service.py
git commit -m "feat: generate daily reports from event snapshots"
```

---

### Task 4: 日报只读投影与网页操作

**Files:**
- Create: `src/newsradar/web/daily_report_queries.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/base.html`
- Create: `src/newsradar/web/templates/daily_reports.html`
- Create: `src/newsradar/web/templates/daily_report_detail.html`
- Create: `tests/web/test_daily_report_pages.py`

**Interfaces:**
- Consumes: `DailyReportService`、`DailyReportRepository`、日报 ORM 快照。
- Produces: `/daily-reports`、`/daily-reports/{id}` 与草稿写操作。

- [ ] **Step 1: 写网页失败测试**

在 `tests/web/test_daily_report_pages.py` 使用真实 test DB 和 `TestClient(create_app())` 覆盖：

```python
def safe_client_with_token(db_session, monkeypatch) -> tuple[TestClient, str]:
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    client = TestClient(create_app(), base_url="http://127.0.0.1")
    page = client.get("/operations")
    token = page.text.split('name="action_token" value="', 1)[1].split('"', 1)[0]
    return client, token


def seed_daily_report(
    session, *, report_date: date = date(2026, 7, 16), operation_id: int = 4101
) -> DailyReportRecord:
    if session.get(OperationRunRecord, operation_id) is None:
        session.add(
            OperationRunRecord(
                id=operation_id,
                operation_type="event_pipeline",
                trigger="test",
                status="succeeded",
                requested_scope={},
                result_summary={},
                created_at=NOW,
                finished_at=NOW,
            )
        )
    for event_id, status in ((operation_id * 10 + 1, "confirmed"), (operation_id * 10 + 2, "emerging")):
        session.add(
            EventRecord(
                id=event_id,
                canonical_key=f"web-daily-report-{event_id}",
                status=status,
                current_version_number=1,
                occurred_at=NOW,
            )
        )
    session.commit()
    return DailyReportRepository(session, utcnow=lambda: NOW).create_draft(
        DailyReportDraft(
            report_date=report_date,
            window_hours=24,
            window_start=NOW - timedelta(hours=24),
            window_end=NOW,
            source_operation_id=operation_id,
            generation_summary={
                "confirmed_count": 1,
                "emerging_count": 1,
                "skipped_invalid_event": 0,
                "skipped_missing_time": 0,
                "minimax_degraded": True,
            },
            items=(
                DailyReportItemDraft(
                    event_id=operation_id * 10 + 1,
                    event_version_number=1,
                    section=ReportSection.CONFIRMED,
                    position=1,
                    snapshot={
                        "zh_title": "确认事件",
                        "zh_summary": "确认摘要",
                        "why_it_matters": "确认影响",
                        "status": "confirmed",
                        "unconfirmed": False,
                        "evidence": [],
                    },
                ),
                DailyReportItemDraft(
                    event_id=operation_id * 10 + 2,
                    event_version_number=1,
                    section=ReportSection.EMERGING,
                    position=1,
                    snapshot={
                        "zh_title": "线索事件",
                        "zh_summary": "线索摘要",
                        "why_it_matters": "线索影响",
                        "status": "emerging",
                        "unconfirmed": True,
                        "evidence": [
                            {
                                "title": "公开证据",
                                "url": "https://example.com/evidence",
                                "published_at": NOW.isoformat(),
                                "role": "professional_media",
                                "independent": True,
                                "limitations": [],
                            }
                        ],
                    },
                ),
            ),
        )
    )


def seed_two_daily_reports(session) -> tuple[DailyReportRecord, DailyReportRecord]:
    return (
        seed_daily_report(session, report_date=date(2026, 7, 16), operation_id=4101),
        seed_daily_report(session, report_date=date(2026, 7, 17), operation_id=4102),
    )
```

然后覆盖：

```python
def test_daily_report_list_explains_generation_is_read_only(db_session, monkeypatch) -> None:
    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get("/daily-reports")
    assert response.status_code == 200
    assert "中文日报" in response.text
    assert "不会重新抓取" in response.text
    assert "24" in response.text and "48" in response.text and "72" in response.text


def test_daily_report_detail_separates_confirmed_and_unconfirmed(db_session, monkeypatch) -> None:
    report = seed_daily_report(db_session)
    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-reports/{report.id}")
    assert response.status_code == 200
    assert "今日确认要闻" in response.text
    assert "值得关注的线索" in response.text
    assert response.text.count("尚未确认") >= 2
    assert f"Operation #{report.source_operation_id}" in response.text


def test_daily_report_posts_require_safe_action_token(db_session, monkeypatch) -> None:
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    client = TestClient(create_app(), base_url="http://127.0.0.1")
    response = client.post("/daily-reports", data={"window_hours": "24"})
    assert response.status_code == 400
```

再加入具名路由测试并使用精确状态码：

```python
def test_generate_redirects_and_rejects_invalid_or_missing_snapshot(db_session, monkeypatch) -> None:
    client, token = safe_client_with_token(db_session, monkeypatch)
    invalid = client.post(
        "/daily-reports", data={"action_token": token, "window_hours": "12"}
    )
    assert invalid.status_code == 422
    client, token = safe_client_with_token(db_session, monkeypatch)
    missing = client.post(
        "/daily-reports", data={"action_token": token, "window_hours": "24"}
    )
    assert missing.status_code == 409


def test_generate_route_redirects_to_created_draft(db_session, monkeypatch) -> None:
    report = seed_daily_report(db_session)
    monkeypatch.setattr(
        "newsradar.web.app.DailyReportService.generate",
        lambda self, window_hours: report,
    )
    client, token = safe_client_with_token(db_session, monkeypatch)
    response = client.post(
        "/daily-reports",
        data={"action_token": token, "window_hours": "24"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/daily-reports/{report.id}"


def test_draft_actions_redirect_and_archive_locks_editing(db_session, monkeypatch) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[0]
    client, token = safe_client_with_token(db_session, monkeypatch)
    toggled = client.post(
        f"/daily-reports/{report.id}/items/{item.id}/included",
        data={"action_token": token, "included": "false"},
        follow_redirects=False,
    )
    assert toggled.status_code == 303
    client, token = safe_client_with_token(db_session, monkeypatch)
    archived = client.post(
        f"/daily-reports/{report.id}/archive",
        data={"action_token": token},
        follow_redirects=False,
    )
    assert archived.status_code == 303
    page = client.get(f"/daily-reports/{report.id}")
    assert "创建修订版" in page.text
    assert "上移" not in page.text and "排除" not in page.text


def test_daily_report_routes_enforce_ownership_and_not_found(db_session, monkeypatch) -> None:
    left, right = seed_two_daily_reports(db_session)
    foreign_item = DailyReportRepository(db_session).items(right.id)[0]
    client, token = safe_client_with_token(db_session, monkeypatch)
    response = client.post(
        f"/daily-reports/{left.id}/items/{foreign_item.id}/included",
        data={"action_token": token, "included": "false"},
    )
    assert response.status_code == 404
    assert client.get("/daily-reports/999999").status_code == 404


def test_archived_page_does_not_follow_event_current_pointer(db_session, monkeypatch) -> None:
    report = seed_daily_report(db_session)
    archived = DailyReportRepository(db_session, utcnow=lambda: NOW).archive(report.id)
    item = DailyReportRepository(db_session).items(archived.id)[0]
    event = db_session.get(EventRecord, item.event_id)
    event.current_version_number = 2
    db_session.add(
        EventVersionRecord(
            event_id=event.id,
            version_number=2,
            zh_title="后来修改的事件标题",
            zh_summary="后来修改的摘要",
            payload={},
            created_at=NOW + timedelta(minutes=1),
        )
    )
    db_session.commit()
    client, _token = safe_client_with_token(db_session, monkeypatch)
    page = client.get(f"/daily-reports/{archived.id}")
    assert "确认事件" in page.text
    assert "后来修改的事件标题" not in page.text
```

在现有安全 URL 测试中断言 `href` 不含 `?`、`#`、`@`；生成路由测试 monkeypatch `httpx.Client.request`、`httpx.AsyncClient.request` 和 MiniMax 客户端入口为 `pytest.fail`，成功303即证明未调用这些入口。

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q tests/web/test_daily_report_pages.py -x
```

Expected: FAIL，`/daily-reports` 返回404。

- [ ] **Step 3: 实现只读查询视图**

在 `src/newsradar/web/daily_report_queries.py` 定义：

```python
@dataclass(frozen=True, slots=True)
class DailyReportSummaryView:
    report_id: int
    report_date: date
    revision: int
    status: str
    window_hours: int
    window_end: datetime
    source_operation_id: int
    confirmed_count: int
    emerging_count: int


@dataclass(frozen=True, slots=True)
class DailyReportItemView:
    item_id: int
    event_id: int
    event_version_number: int
    section: str
    position: int
    included: bool
    snapshot: dict[str, object]


@dataclass(frozen=True, slots=True)
class DailyReportDetailView:
    report: DailyReportSummaryView
    generation_summary: dict[str, object]
    supersedes_report_id: int | None
    archived_at: datetime | None
    confirmed: tuple[DailyReportItemView, ...]
    emerging: tuple[DailyReportItemView, ...]


class DailyReportQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_reports(self, *, limit: int = 100) -> tuple[DailyReportSummaryView, ...]:
        records = self.session.scalars(
            select(DailyReportRecord)
            .order_by(
                DailyReportRecord.report_date.desc(),
                DailyReportRecord.revision.desc(),
                DailyReportRecord.id.desc(),
            )
            .limit(max(1, min(limit, 100)))
        )
        return tuple(self._summary(record) for record in records)

    def detail(self, report_id: int) -> DailyReportDetailView | None:
        record = self.session.get(DailyReportRecord, report_id)
        if record is None:
            return None
        rows = tuple(
            self.session.scalars(
                select(DailyReportItemRecord)
                .where(DailyReportItemRecord.daily_report_id == report_id)
                .order_by(
                    case((DailyReportItemRecord.section == "confirmed", 0), else_=1),
                    DailyReportItemRecord.position,
                    DailyReportItemRecord.id,
                )
            )
        )
        views = tuple(
            DailyReportItemView(
                item_id=row.id,
                event_id=row.event_id,
                event_version_number=row.event_version_number,
                section=row.section,
                position=row.position,
                included=row.included,
                snapshot=dict(row.snapshot) if isinstance(row.snapshot, dict) else {},
            )
            for row in rows
        )
        return DailyReportDetailView(
            report=self._summary(record, rows=rows),
            generation_summary=(
                dict(record.generation_summary)
                if isinstance(record.generation_summary, dict)
                else {}
            ),
            supersedes_report_id=record.supersedes_report_id,
            archived_at=record.archived_at,
            confirmed=tuple(row for row in views if row.section == "confirmed"),
            emerging=tuple(row for row in views if row.section == "emerging"),
        )

    def has_complete_event_snapshot(self, *, now: datetime | None = None) -> bool:
        return latest_complete_event_snapshot(self.session, now=now) is not None

    def _summary(
        self,
        record: DailyReportRecord,
        *,
        rows: tuple[DailyReportItemRecord, ...] | None = None,
    ) -> DailyReportSummaryView:
        loaded = rows or tuple(
            self.session.scalars(
                select(DailyReportItemRecord).where(
                    DailyReportItemRecord.daily_report_id == record.id,
                    DailyReportItemRecord.included.is_(True),
                )
            )
        )
        return DailyReportSummaryView(
            report_id=record.id,
            report_date=record.report_date,
            revision=record.revision,
            status=record.status,
            window_hours=record.window_hours,
            window_end=record.window_end,
            source_operation_id=record.source_operation_id,
            confirmed_count=sum(
                row.included and row.section == "confirmed" for row in loaded
            ),
            emerging_count=sum(
                row.included and row.section == "emerging" for row in loaded
            ),
        )
```

`list_reports()` 按 `report_date desc, revision desc, id desc`；计数只统计 `included=true`。`detail()` 读取固定 `snapshot` 并按 `section, position` 排序，不连接 Event/RawItem 获取展示内容。

- [ ] **Step 4: 实现网页路由**

在 `create_app()` 内加入以下薄路由。共同使用现有 `create_session()`、`require_safe_action()`、`issue_action_token()` 和 `database_error_response()`：

```python
@app.get("/daily-reports", response_class=HTMLResponse)
def daily_reports(request: Request) -> HTMLResponse:
    try:
        with create_session() as session:
            service = DailyReportQueryService(session)
            reports = service.list_reports()
            snapshot_available = service.has_complete_event_snapshot()
    except SQLAlchemyError as error:
        return database_error_response(request, error)
    return templates.TemplateResponse(
        request=request,
        name="daily_reports.html",
        context={
            "reports": reports,
            "snapshot_available": snapshot_available,
            "action_token": issue_action_token(request),
            "database_status": "数据库已连接",
            "database_status_tone": "healthy",
            "latest_probe_at": None,
        },
    )

@app.post("/daily-reports")
async def generate_daily_report(request: Request) -> RedirectResponse:
    values = await require_safe_action(request)
    try:
        window_hours = int(values.get("window_hours", "24"))
        with create_session() as session:
            report = DailyReportService(session).generate(window_hours)
    except (TypeError, ValueError) as error:
        status_code = 409 if str(error) == "complete_event_snapshot_required" else 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    except SQLAlchemyError as error:
        return database_error_response(request, error)
    return RedirectResponse(url=f"/daily-reports/{report.id}", status_code=303)

@app.get("/daily-reports/{report_id}", response_class=HTMLResponse)
def daily_report_detail(request: Request, report_id: int) -> HTMLResponse:
    try:
        with create_session() as session:
            detail = DailyReportQueryService(session).detail(report_id)
    except SQLAlchemyError as error:
        return database_error_response(request, error)
    if detail is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="daily_report_detail.html",
        context={
            "daily_report": detail,
            "action_token": issue_action_token(request),
            "database_status": "数据库已连接",
            "database_status_tone": "healthy",
            "latest_probe_at": detail.report.window_end,
        },
    )

@app.post("/daily-reports/{report_id}/items/{item_id}/included")
async def set_daily_report_item_included(
    request: Request, report_id: int, item_id: int
) -> RedirectResponse:
    values = await require_safe_action(request)
    included = values.get("included") == "true"
    try:
        with create_session() as session:
            DailyReportRepository(session).set_included(
                report_id, item_id, included=included
            )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SQLAlchemyError as error:
        return database_error_response(request, error)
    return RedirectResponse(url=f"/daily-reports/{report_id}", status_code=303)

@app.post("/daily-reports/{report_id}/items/{item_id}/move")
async def move_daily_report_item(
    request: Request, report_id: int, item_id: int
) -> RedirectResponse:
    values = await require_safe_action(request)
    try:
        with create_session() as session:
            DailyReportRepository(session).move_item(
                report_id, item_id, direction=values.get("direction", "")
            )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SQLAlchemyError as error:
        return database_error_response(request, error)
    return RedirectResponse(url=f"/daily-reports/{report_id}", status_code=303)

@app.post("/daily-reports/{report_id}/archive")
async def archive_daily_report(request: Request, report_id: int) -> RedirectResponse:
    await require_safe_action(request)
    try:
        with create_session() as session:
            DailyReportRepository(session).archive(report_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SQLAlchemyError as error:
        return database_error_response(request, error)
    return RedirectResponse(url=f"/daily-reports/{report_id}", status_code=303)

@app.post("/daily-reports/{report_id}/revise")
async def revise_daily_report(request: Request, report_id: int) -> RedirectResponse:
    await require_safe_action(request)
    try:
        with create_session() as session:
            revision = DailyReportService(session).revise(report_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SQLAlchemyError as error:
        return database_error_response(request, error)
    return RedirectResponse(url=f"/daily-reports/{revision.id}", status_code=303)
```

所有 POST 第一行调用 `values = await require_safe_action(request)`；把 `LookupError` 映射404，把非法窗口映射422，把无快照和归档冲突映射409，把 SQLAlchemyError 交给 `database_error_response()`。成功操作统一303回详情页。

- [ ] **Step 5: 实现模板与导航**

在 `base.html` 的事件导航后增加：

```html
<a href="/daily-reports"{% if request.url.path.startswith('/daily-reports') %} aria-current="page"{% endif %}>中文日报</a>
```

`daily_reports.html` 必须包含：

```html
<section class="panel">
  <p class="eyebrow">手动生成 · 固定事件快照</p>
  <h2>中文日报</h2>
  <p>生成日报只读取已完成的事件快照，不会重新抓取、重新聚类或调用 MiniMax。</p>
  {% if snapshot_available %}
  <form method="post" action="/daily-reports">
    <input type="hidden" name="action_token" value="{{ action_token }}">
    <label>时间窗口
      <select name="window_hours">
        <option value="24">最近24小时</option>
        <option value="48">最近48小时</option>
        <option value="72">最近72小时</option>
      </select>
    </label>
    <button type="submit">生成日报草稿</button>
  </form>
  {% else %}<p>尚无完整事件运行快照，请先完成事件构建。</p>{% endif %}
</section>
```

列表显示日期、修订、状态、截止时间、确认数、线索数。

`daily_report_detail.html` 必须把两个 section 写成两个独立 `<section>`；emerging 区顶部和每个条目都包含纯文本“尚未确认”。草稿 item 显示排除/恢复、上移/下移；归档后不渲染这些表单，只渲染“创建修订版”。证据 URL 使用 `target="_blank" rel="noopener noreferrer"`。

- [ ] **Step 6: 运行网页与安全测试**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q tests/web/test_daily_report_pages.py tests/web/test_event_routes.py tests/web/test_routes.py -x
```

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add src/newsradar/web/daily_report_queries.py src/newsradar/web/app.py src/newsradar/web/templates/base.html src/newsradar/web/templates/daily_reports.html src/newsradar/web/templates/daily_report_detail.html tests/web/test_daily_report_pages.py
git commit -m "feat: add manual Chinese daily report pages"
```

---

### Task 5: 真实 PostgreSQL、不可变性和浏览器验收

**Files:**
- Modify only if a failing acceptance test exposes a defect in files from Tasks 1–4.
- Do not create or edit files under `reports/`.

**Interfaces:**
- Consumes: 完整日报功能与现有本地 PostgreSQL/8766 服务。
- Produces: 可复现的测试输出、真实日报草稿/归档记录和浏览器验收证据。

- [ ] **Step 1: 运行针对性与完整自动化门禁**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q tests/daily_reports tests/web/test_daily_report_pages.py tests/test_migrations.py -x
..\..\.venv\Scripts\ruff.exe check .
..\..\.venv\Scripts\python.exe -m pytest
git diff --check
```

Expected: 所有命令退出码0；完整测试无失败；Ruff输出 `All checks passed!`。

- [ ] **Step 2: 在真实数据库升级迁移**

从主项目目录启动 Python，使 `Settings` 只按现有方式加载主项目配置；通过 `PYTHONPATH` 指向功能工作树代码。禁止读取或输出环境变量值：

```powershell
Set-Location 'D:\codex_project_work\news_codex'
$worktree = 'D:\codex_project_work\news_codex\.worktrees\manual-chinese-daily-report-mvp'
$env:PYTHONPATH = "$worktree\src"
@'
from pathlib import Path
from alembic import command
from alembic.config import Config

worktree = Path(r"D:\codex_project_work\news_codex\.worktrees\manual-chinese-daily-report-mvp")
config = Config(str(worktree / "alembic.ini"))
config.set_main_option("script_location", str(worktree / "migrations"))
command.upgrade(config, "head")
'@ | .\.venv\Scripts\python.exe -
```

随后只读验证表存在：

```powershell
@'
from sqlalchemy import inspect
from newsradar.db.session import create_database_engine
tables = set(inspect(create_database_engine()).get_table_names())
assert {"daily_reports", "daily_report_items"} <= tables
print("daily report tables ready")
'@ | .\.venv\Scripts\python.exe -
```

Expected: 输出 `daily report tables ready`，不显示连接串。

- [ ] **Step 3: 在隔离端口启动功能服务**

在主项目目录使用功能工作树 `PYTHONPATH` 和现有数据库配置，启动临时端口 `8879` 与唯一 worker ID；不得停止正常 `8766` 服务：

```powershell
Set-Location 'D:\codex_project_work\news_codex'
$worktree = 'D:\codex_project_work\news_codex\.worktrees\manual-chinese-daily-report-mvp'
$env:PYTHONPATH = "$worktree\src"
$process = Start-Process -FilePath '.\.venv\Scripts\newsradar.exe' -ArgumentList @('serve','--host','127.0.0.1','--port','8879','--worker-id','newsradar-daily-report-acceptance') -WorkingDirectory 'D:\codex_project_work\news_codex' -WindowStyle Hidden -PassThru
```

轮询 `http://127.0.0.1:8879/daily-reports`，最多30秒，直到返回200；禁止用固定长时间 sleep。

- [ ] **Step 4: 用真实页面生成并整理24小时日报**

使用 Browser 技能执行：

1. 打开 `/daily-reports`；
2. 确认页面写明“不重新抓取、重新聚类或调用 MiniMax”；
3. 选择24小时并点击“生成日报草稿”；
4. 确认跳转详情页；
5. 记录页面显示的 Operation 编号、确认要闻数、未确认线索数和跳过数；
6. 验证两区独立，每条线索均显示“尚未确认”；
7. 排除并恢复一条线索；
8. 上移或下移一条同区条目；
9. 归档日报；
10. 确认归档后编辑控件消失，显示“创建修订版”。

浏览器操作不得点击事件更新或来源抓取按钮。

- [ ] **Step 5: 验证归档不可变和修订**

真实数据库不修改任何 Event。归档后读取该日报 item snapshot 的哈希和详情页正文哈希；创建修订版后再次读取旧日报，断言两个哈希均不变。自动化测试另外在 SQLite 测试库中创建同一 Event 的新版本并移动 current 指针，证明归档页面仍只读日报 snapshot。随后断言：

- 新日报 `revision = old.revision + 1`；
- `supersedes_report_id` 指向旧日报；
- 旧日报仍为 archived；
- 新草稿初始条目快照与旧日报一致。

不得为此触发抓取、事件构建或模型调用。

- [ ] **Step 6: 验证运行无网络副作用**

对比生成日报前后的数据库计数：`fetch_runs`、`raw_items`、`event_versions`、`model_usage` 必须不变；只有 `daily_reports` 和 `daily_report_items` 增加。输出仅包含表名和计数差，不输出 payload 或密钥。

- [ ] **Step 7: 关闭临时服务并复核工作区**

只停止 Step 3 启动的进程树，确认端口8879关闭、正常8766仍返回200。然后执行：

```powershell
git status --short --branch
git diff --check
```

Expected: 仅包含本功能已提交内容；用户 `reports/` 文件不在该工作树中出现变更。

- [ ] **Step 8: 修复验收缺陷时执行TDD闭环并提交**

仅当 Steps 1–7 暴露实际缺陷时：先在对应测试文件加入最小失败用例，确认失败，再修正对应实现并重新运行完整门禁。提交范围只包含日报功能文件：

```powershell
git add migrations/versions/20260716_0023_daily_reports.py src/newsradar/daily_reports src/newsradar/db/models.py src/newsradar/web/daily_report_queries.py src/newsradar/web/app.py src/newsradar/web/templates/base.html src/newsradar/web/templates/daily_reports.html src/newsradar/web/templates/daily_report_detail.html tests/daily_reports tests/web/test_daily_report_pages.py tests/test_migrations.py
git commit -m "fix: close daily report acceptance gaps"
```

- [ ] **Step 9: 请求合并前审查并选择完成方式**

使用 `superpowers:requesting-code-review` 审查：规格覆盖、归档不可变、confirmed/emerging 分区、URL 清洗、无网络/模型副作用、CSRF、迁移和测试。修复所有 P0/P1/P2 后重新运行完整门禁，再使用 `superpowers:finishing-a-development-branch` 让用户选择本地合并、PR、保留或丢弃。

未经用户明确确认，不合并、不推送。

---

## Final Acceptance Checklist

- [ ] 24/48/72小时可手动生成日报，默认24小时。
- [ ] 生成只读取最近完整事件运行快照，不回退 current 目录。
- [ ] 生成不增加 FetchRun、RawItem、EventVersion 或 ModelUsage。
- [ ] confirmed 和 emerging 严格分区，emerging 逐条明文标记“尚未确认”。
- [ ] `audit_only`、窗口外、缺失时间和损坏事件按规则排除或计数。
- [ ] 每区最多20条，排序稳定，确认区不足不以线索补齐。
- [ ] 草稿可排除、恢复和同区排序，不能跨区或编辑事件内容。
- [ ] 归档不可修改，历史正文不随 Event current 指针变化。
- [ ] 修订创建新记录并指向被替代日报，旧日报保持不变。
- [ ] 每条日报内容固定事件ID、版本号和公开证据链接。
- [ ] 证据 URL 无用户信息、密码、查询参数和片段。
- [ ] MiniMax 未配置或降级时仍能生成。
- [ ] 所有写操作通过现有 loopback、same-origin 和动作令牌保护。
- [ ] SQLite迁移升级/降级和真实PostgreSQL升级通过。
- [ ] 完整pytest、Ruff、`git diff --check` 和真实浏览器验收通过。
- [ ] 不触碰用户保留报告，不读取或输出 `.env` 密钥。
