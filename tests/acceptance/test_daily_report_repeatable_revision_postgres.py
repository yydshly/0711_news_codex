"""PostgreSQL acceptance for complete, repeatable daily-report revisions."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, delete, func, select, text
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.exc import ArgumentError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from newsradar.daily_reports.purge_runtime import DailyReportPurgeHandler
from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.schema import (
    DailyReportDraft,
    DailyReportEditorialReviewDraft,
    DailyReportItemDraft,
    DailyReportOverviewEditorialReviewDraft,
    DailyReportOverviewItemDraft,
    ReportSection,
)
from newsradar.db.models import (
    DailyReportItemEditorialReviewRecord,
    DailyReportItemRecord,
    DailyReportOverviewEditorialReviewRecord,
    DailyReportOverviewItemRecord,
    DailyReportRecord,
    EventRecord,
    OperationRunRecord,
)
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus

_RUN_POSTGRES_ENV = "NEWSRADAR_RUN_POSTGRES_ACCEPTANCE"
_TEST_POSTGRES_URL_ENV = "NEWSRADAR_TEST_POSTGRES_URL"
_TEST_SCHEMA_PATTERN = re.compile(r"newsradar_revision_test_[0-9a-f]{32}")
_ALEMBIC_HEAD = "20260719_0032"
_ROOT = Path(__file__).parents[2]
NOW = datetime(2026, 7, 19, 4, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PostgreSQLHarness:
    engine: Engine
    schema_name: str

    def __call__(self) -> Session:
        return Session(self.engine)


def _safe_fail(code: str, error: BaseException | None = None) -> None:
    suffix = f":{error.__class__.__name__}" if error is not None else ""
    raise pytest.fail.Exception(f"{code}{suffix}", pytrace=False) from None


def _explicit_test_postgres_url_or_skip() -> str:
    if os.getenv(_RUN_POSTGRES_ENV) != "1":
        pytest.skip(f"set {_RUN_POSTGRES_ENV}=1 to run isolated PostgreSQL acceptance")
    raw_url = os.getenv(_TEST_POSTGRES_URL_ENV)
    if not raw_url:
        pytest.skip(f"set dedicated {_TEST_POSTGRES_URL_ENV}; project DATABASE_URL is ignored")
    try:
        parsed = make_url(raw_url)
    except ArgumentError as error:
        _safe_fail("test_postgres_url_invalid", error)
    database_name = parsed.database or ""
    if parsed.get_backend_name() != "postgresql" or "test" not in database_name.casefold():
        _safe_fail("test_postgres_database_not_safe")
    return raw_url


def _assert_test_connection(connection: Connection, *, expected_schema: str | None = None) -> None:
    database_name = connection.scalar(text("SELECT current_database()"))
    if not isinstance(database_name, str) or "test" not in database_name.casefold():
        _safe_fail("test_postgres_server_database_not_safe")
    if expected_schema is not None:
        current_schema = connection.scalar(text("SELECT current_schema()"))
        if current_schema != expected_schema:
            _safe_fail("test_postgres_schema_not_isolated")


def test_postgres_acceptance_never_falls_back_to_project_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_RUN_POSTGRES_ENV, raising=False)
    monkeypatch.setenv(
        _TEST_POSTGRES_URL_ENV,
        "postgresql://ignored:ignored@invalid/newsradar_test",
    )
    with pytest.raises(pytest.skip.Exception, match=_RUN_POSTGRES_ENV):
        _explicit_test_postgres_url_or_skip()

    monkeypatch.setenv(_RUN_POSTGRES_ENV, "1")
    monkeypatch.delenv(_TEST_POSTGRES_URL_ENV, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://ignored:ignored@invalid/project")
    with pytest.raises(pytest.skip.Exception, match=_TEST_POSTGRES_URL_ENV):
        _explicit_test_postgres_url_or_skip()

    monkeypatch.setenv(_TEST_POSTGRES_URL_ENV, "://")
    with pytest.raises(pytest.fail.Exception, match="test_postgres_url_invalid"):
        _explicit_test_postgres_url_or_skip()

    monkeypatch.setenv(
        _TEST_POSTGRES_URL_ENV,
        "postgresql://ignored:ignored@invalid/project",
    )
    with pytest.raises(pytest.fail.Exception, match="test_postgres_database_not_safe"):
        _explicit_test_postgres_url_or_skip()


def _upgrade_isolated_schema(isolated_url: URL) -> None:
    config = Config()
    config.set_main_option("script_location", str(_ROOT / "migrations"))
    rendered_url = isolated_url.render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", rendered_url.replace("%", "%%"))
    with patch(
        "newsradar.settings.get_settings",
        return_value=SimpleNamespace(database_url=None),
    ):
        command.upgrade(config, _ALEMBIC_HEAD)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[PostgreSQLHarness]:
    raw_url = _explicit_test_postgres_url_or_skip()
    schema_name = f"newsradar_revision_test_{uuid4().hex}"
    if _TEST_SCHEMA_PATTERN.fullmatch(schema_name) is None:
        _safe_fail("test_postgres_schema_name_invalid")
    try:
        admin_engine = create_engine(
            raw_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
    except Exception as error:
        _safe_fail("test_postgres_engine_create_failed", error)

    schema_created = False
    isolated_engine: Engine | None = None
    try:
        try:
            with admin_engine.begin() as connection:
                _assert_test_connection(connection)
                connection.execute(CreateSchema(schema_name))
                schema_created = True
        except SQLAlchemyError as error:
            _safe_fail("test_postgres_schema_create_failed", error)

        isolated_url = make_url(raw_url).update_query_dict(
            {"options": f"-csearch_path={schema_name}"}
        )
        try:
            _upgrade_isolated_schema(isolated_url)
            isolated_engine = create_engine(
                isolated_url,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 3},
            )
            with isolated_engine.connect() as connection:
                _assert_test_connection(connection, expected_schema=schema_name)
                migrated_head = connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                if migrated_head != _ALEMBIC_HEAD:
                    _safe_fail("test_postgres_schema_not_at_required_head")
        except Exception as error:
            _safe_fail("test_postgres_schema_prepare_failed", error)
        yield PostgreSQLHarness(isolated_engine, schema_name)
    finally:
        if isolated_engine is not None:
            isolated_engine.dispose()
        if schema_created:
            try:
                with admin_engine.begin() as connection:
                    _assert_test_connection(connection)
                    connection.execute(DropSchema(schema_name, cascade=True))
            except SQLAlchemyError as error:
                _safe_fail("test_postgres_schema_cleanup_failed", error)
        admin_engine.dispose()


def test_postgres_guard_allows_only_trashed_draft_purge(
    postgres_engine: PostgreSQLHarness,
    tmp_path: Path,
) -> None:
    with postgres_engine() as session:
        operation = OperationRunRecord(
            operation_type="event_pipeline",
            trigger="acceptance",
            status="succeeded",
            requested_scope={},
            result_summary={},
            created_at=NOW,
            finished_at=NOW,
        )
        session.add(operation)
        session.flush()
        draft = DailyReportRepository(session, utcnow=lambda: NOW).create_draft(
            DailyReportDraft(
                report_date=date(2026, 7, 20),
                window_hours=24,
                window_start=NOW - timedelta(hours=24),
                window_end=NOW,
                source_operation_id=operation.id,
                generation_summary={"acceptance": "draft-purge-guard"},
                items=(),
            )
        )
        draft_id = draft.id
        operation_id = operation.id

    with postgres_engine() as session:
        with pytest.raises(IntegrityError, match="daily_report_archived_immutable"):
            session.execute(
                delete(DailyReportRecord).where(DailyReportRecord.id == draft_id)
            )
        session.rollback()

    with postgres_engine() as session:
        result = DailyReportRepository(session, utcnow=lambda: NOW).move_to_trash(
            draft_id
        )
        assert result.outcome == "trashed"

    purge_result = DailyReportPurgeHandler(
        postgres_engine,
        audio_root=tmp_path / "audio",
    )(
        OperationLease(
            990_101,
            990_102,
            1,
            "postgres-draft-purge-worker",
            {"schema_version": 1, "report_ids": [draft_id]},
            "daily_report_purge",
        ),
        lambda _boundary: None,
    )

    assert purge_result.status is OperationStatus.SUCCEEDED
    with postgres_engine() as session:
        assert session.get(DailyReportRecord, draft_id) is None
        assert session.get(OperationRunRecord, operation_id) is not None
        replacement = DailyReportRepository(session, utcnow=lambda: NOW).create_draft(
            DailyReportDraft(
                report_date=date(2026, 7, 20),
                window_hours=24,
                window_start=NOW - timedelta(hours=24),
                window_end=NOW,
                source_operation_id=operation_id,
                generation_summary={"acceptance": "draft-purge-replacement"},
                items=(),
            )
        )
        assert replacement.revision == 2


def _seed_archived_parent(session: Session) -> tuple[int, dict[str, object]]:
    operation = OperationRunRecord(
        operation_type="event_pipeline",
        trigger="acceptance",
        status="succeeded",
        requested_scope={},
        result_summary={},
        created_at=NOW,
        finished_at=NOW,
    )
    session.add(operation)
    session.flush()
    event_ids = (81001, 81002)
    session.add_all(
        EventRecord(
            id=event_id,
            canonical_key=f"daily-revision-acceptance-{event_id}",
            status=status,
            current_version_number=1,
            occurred_at=NOW,
        )
        for event_id, status in zip(event_ids, ("confirmed", "emerging"), strict=True)
    )
    session.commit()

    repository = DailyReportRepository(session, utcnow=lambda: NOW)
    parent = repository.create_draft(
        DailyReportDraft(
            report_date=date(2026, 7, 19),
            window_hours=24,
            window_start=NOW - timedelta(hours=24),
            window_end=NOW,
            source_operation_id=operation.id,
            generation_summary={"acceptance": "complete-copy"},
            items=(
                DailyReportItemDraft(
                    event_id=event_ids[0],
                    event_version_number=1,
                    section=ReportSection.CONFIRMED,
                    position=1,
                    snapshot={"zh_title": "确认条目", "marker": "decision-confirmed"},
                ),
                DailyReportItemDraft(
                    event_id=event_ids[1],
                    event_version_number=1,
                    section=ReportSection.EMERGING,
                    position=1,
                    snapshot={"zh_title": "线索条目", "marker": "decision-emerging"},
                    included=False,
                ),
            ),
            overview_items=(
                DailyReportOverviewItemDraft(
                    event_id=event_ids[0],
                    event_version_number=1,
                    position=1,
                    snapshot={"zh_title": "确认全览", "marker": "overview-confirmed"},
                    decision_event_id=event_ids[0],
                ),
                DailyReportOverviewItemDraft(
                    event_id=event_ids[1],
                    event_version_number=1,
                    position=2,
                    snapshot={"zh_title": "线索全览", "marker": "overview-emerging"},
                    decision_event_id=event_ids[1],
                ),
            ),
        )
    )
    for index, item in enumerate(repository.items(parent.id), start=1):
        repository.save_editorial_review(
            parent.id,
            item.id,
            DailyReportEditorialReviewDraft.create(
                decision="keep" if index == 1 else "exclude",
                zh_title=f"决策审核标题 {index}",
                zh_summary=f"决策审核概述 {index}",
                review_recommendation=f"决策审核建议 {index}",
                evidence_assessment=f"决策证据评价 {index}",
            ),
        )
    for index, item in enumerate(repository.overview_items(parent.id), start=1):
        repository.save_overview_editorial_review(
            parent.id,
            item.id,
            DailyReportOverviewEditorialReviewDraft.create(
                decision="keep" if index == 1 else "needs_evidence",
                zh_title=f"全览审核标题 {index}",
                zh_summary=f"全览审核概述 {index}",
                review_recommendation=f"全览审核建议 {index}",
                evidence_assessment=f"全览证据评价 {index}",
            ),
        )
    repository.archive(parent.id)
    parent_items = repository.items(parent.id)
    parent_decision_event_by_id = {row.id: row.event_id for row in parent_items}
    expected = {
        "identity": (
            parent.report_date,
            parent.window_hours,
            parent.window_start,
            parent.window_end,
            parent.source_operation_id,
        ),
        "items": tuple(
            (
                row.event_id,
                row.event_version_number,
                row.section,
                row.position,
                row.included,
                row.snapshot,
            )
            for row in parent_items
        ),
        "overview": tuple(
            (
                row.event_id,
                row.event_version_number,
                row.position,
                row.snapshot,
                parent_decision_event_by_id.get(row.decision_item_id),
            )
            for row in repository.overview_items(parent.id)
        ),
    }
    return parent.id, expected


def _decision_review_values(row: DailyReportItemEditorialReviewRecord) -> tuple[object, ...]:
    return (
        row.decision,
        row.zh_title,
        row.zh_summary,
        row.review_recommendation,
        row.evidence_assessment,
    )


def _overview_review_values(
    row: DailyReportOverviewEditorialReviewRecord,
) -> tuple[object, ...]:
    return (
        row.decision,
        row.zh_title,
        row.zh_summary,
        row.review_recommendation,
        row.evidence_assessment,
    )


def test_concurrent_revision_requests_reuse_one_complete_active_draft(
    postgres_engine: PostgreSQLHarness,
) -> None:
    with postgres_engine() as setup:
        parent_id, expected = _seed_archived_parent(setup)
        repository = DailyReportRepository(setup, utcnow=lambda: NOW)
        parent_decision_review_rows = tuple(
            setup.scalars(
                select(DailyReportItemEditorialReviewRecord)
                .join(DailyReportItemRecord)
                .where(DailyReportItemRecord.daily_report_id == parent_id)
                .order_by(DailyReportItemRecord.section, DailyReportItemRecord.position)
            )
        )
        parent_decision_reviews = tuple(
            _decision_review_values(row) for row in parent_decision_review_rows
        )
        parent_decision_review_ids = tuple(row.id for row in parent_decision_review_rows)
        parent_overview_review_rows = tuple(
            setup.scalars(
                select(DailyReportOverviewEditorialReviewRecord)
                .join(DailyReportOverviewItemRecord)
                .where(DailyReportOverviewItemRecord.daily_report_id == parent_id)
                .order_by(DailyReportOverviewItemRecord.position)
            )
        )
        parent_overview_reviews = tuple(
            _overview_review_values(row) for row in parent_overview_review_rows
        )
        parent_overview_review_ids = tuple(row.id for row in parent_overview_review_rows)
        abandoned = repository.revise(parent_id)
        abandoned_id = abandoned.id
        abandoned_revision = abandoned.revision
        repository.move_to_trash(abandoned_id)

    barrier = Barrier(2)

    def revise() -> int:
        with postgres_engine() as session:
            barrier.wait(timeout=10)
            revision_id = DailyReportRepository(session, utcnow=lambda: NOW).revise(parent_id).id
            assert session.scalar(select(1)) == 1
            return revision_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        result_ids = tuple(executor.map(lambda _index: revise(), range(2)))

    assert result_ids[0] == result_ids[1]
    replacement_id = result_ids[0]
    assert replacement_id != abandoned_id

    with postgres_engine() as verify:
        all_children = tuple(
            verify.scalars(
                select(DailyReportRecord)
                .where(DailyReportRecord.supersedes_report_id == parent_id)
                .order_by(DailyReportRecord.revision, DailyReportRecord.id)
            )
        )
        assert [
            (row.id, row.revision, row.deleted_at is None) for row in all_children
        ] == [
            (abandoned_id, abandoned_revision, False),
            (replacement_id, abandoned_revision + 1, True),
        ]
        active_children = tuple(
            row for row in all_children if row.deleted_at is None
        )
        assert [row.id for row in active_children] == [replacement_id]
        replacement = active_children[0]
        assert replacement.status == "draft"
        assert (
            replacement.report_date,
            replacement.window_hours,
            replacement.window_start,
            replacement.window_end,
            replacement.source_operation_id,
        ) == expected["identity"]
        assert replacement.revision == abandoned_revision + 1
        assert verify.scalar(
            select(func.max(DailyReportRecord.revision)).where(
                DailyReportRecord.report_date == replacement.report_date,
                DailyReportRecord.window_hours == replacement.window_hours,
            )
        ) == replacement.revision
        assert replacement.generation_summary == {"acceptance": "complete-copy"}

        replacement_repository = DailyReportRepository(verify)
        replacement_item_rows = replacement_repository.items(replacement_id)
        replacement_decision_event_by_id = {
            row.id: row.event_id for row in replacement_item_rows
        }
        replacement_items = tuple(
            (
                row.event_id,
                row.event_version_number,
                row.section,
                row.position,
                row.included,
                row.snapshot,
            )
            for row in replacement_item_rows
        )
        replacement_overview = tuple(
            (
                row.event_id,
                row.event_version_number,
                row.position,
                row.snapshot,
                replacement_decision_event_by_id.get(row.decision_item_id),
            )
            for row in replacement_repository.overview_items(replacement_id)
        )
        assert replacement_items == expected["items"]
        assert replacement_overview == expected["overview"]

        assert verify.scalars(
            select(DailyReportRecord.id).where(
                DailyReportRecord.status == "draft",
                DailyReportRecord.report_date == replacement.report_date,
                DailyReportRecord.window_hours == replacement.window_hours,
                DailyReportRecord.deleted_at.is_(None),
            )
        ).all() == [replacement_id]

        decision_reviews = tuple(
            verify.scalars(
                select(DailyReportItemEditorialReviewRecord)
                .join(DailyReportItemRecord)
                .where(DailyReportItemRecord.daily_report_id == replacement_id)
                .order_by(DailyReportItemRecord.section, DailyReportItemRecord.position)
            )
        )
        overview_reviews = tuple(
            verify.scalars(
                select(DailyReportOverviewEditorialReviewRecord)
                .join(DailyReportOverviewItemRecord)
                .where(DailyReportOverviewItemRecord.daily_report_id == replacement_id)
                .order_by(DailyReportOverviewItemRecord.position)
            )
        )
        assert tuple(_decision_review_values(row) for row in decision_reviews) == (
            parent_decision_reviews
        )
        assert tuple(_overview_review_values(row) for row in overview_reviews) == (
            parent_overview_reviews
        )
        assert len(decision_reviews) == len(expected["items"])
        assert len(overview_reviews) == len(expected["overview"])
        assert tuple(
            row.copied_from_editorial_review_id for row in decision_reviews
        ) == parent_decision_review_ids
        assert tuple(
            row.copied_from_editorial_review_id for row in overview_reviews
        ) == parent_overview_review_ids

    with postgres_engine() as setup_restore_race:
        trashed = DailyReportRepository(setup_restore_race).move_to_trash(replacement_id)
        assert trashed.outcome == "trashed"

    restore_barrier = Barrier(2)

    def restore(report_id: int) -> tuple[str, str]:
        with postgres_engine() as session:
            restore_barrier.wait(timeout=10)
            result = DailyReportRepository(session, utcnow=lambda: NOW).restore(report_id)
            assert session.scalar(select(1)) == 1
            return result.outcome, result.diagnostic_zh

    with ThreadPoolExecutor(max_workers=2) as executor:
        restore_results = tuple(executor.map(restore, (abandoned_id, replacement_id)))

    assert sorted(outcome for outcome, _diagnostic in restore_results) == [
        "blocked",
        "restored",
    ]
    assert [
        diagnostic
        for outcome, diagnostic in restore_results
        if outcome == "blocked"
    ] == ["该日报已有新的有效修订版，不能直接恢复。"]
    with postgres_engine() as verify_restore_race:
        active_sibling_ids = tuple(
            verify_restore_race.scalars(
                select(DailyReportRecord.id).where(
                    DailyReportRecord.supersedes_report_id == parent_id,
                    DailyReportRecord.deleted_at.is_(None),
                )
            )
        )
        assert len(active_sibling_ids) == 1
        assert active_sibling_ids[0] in {abandoned_id, replacement_id}
