from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.schema import (
    DailyReportDraft,
    DailyReportItemDraft,
    ReportSection,
)
from newsradar.db.models import (
    DailyReportRecord,
    EventRecord,
    EventVersionRecord,
    OperationRunRecord,
)
from newsradar.web.app import create_app

NOW = datetime(2026, 7, 16, 4, tzinfo=UTC)


def safe_client_with_token(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, str]:
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    client = TestClient(
        create_app(),
        base_url="http://127.0.0.1",
        headers={"Origin": "http://127.0.0.1"},
    )
    page = client.get("/operations")
    token = page.text.split('name="action_token" value="', 1)[1].split('"', 1)[0]
    return client, token


def seed_daily_report(
    session: Session,
    *,
    report_date: date = date(2026, 7, 16),
    operation_id: int = 4101,
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
    for event_id, status in (
        (operation_id * 10 + 1, "confirmed"),
        (operation_id * 10 + 2, "emerging"),
    ):
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


def seed_two_daily_reports(
    session: Session,
) -> tuple[DailyReportRecord, DailyReportRecord]:
    return (
        seed_daily_report(session, report_date=date(2026, 7, 16), operation_id=4101),
        seed_daily_report(session, report_date=date(2026, 7, 17), operation_id=4102),
    )


def test_daily_report_list_explains_generation_is_read_only(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get("/daily-reports")
    assert response.status_code == 200
    assert "中文日报" in response.text
    assert "不会重新抓取" in response.text
    assert "24" in response.text and "48" in response.text and "72" in response.text


def test_daily_report_list_orders_newest_first_and_counts_only_included(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    older, newer = seed_two_daily_reports(db_session)
    excluded = DailyReportRepository(db_session).items(older.id)[0]
    DailyReportRepository(db_session).set_included(older.id, excluded.id, included=False)
    older_id, newer_id = older.id, newer.id
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get("/daily-reports")

    assert response.status_code == 200
    assert response.text.index("2026-07-17") < response.text.index("2026-07-16")
    older_row = response.text.split(f'href="/daily-reports/{older_id}"', 1)[1].split(
        "</tr>", 1
    )[0]
    assert ">0<" in older_row
    assert f'href="/daily-reports/{newer_id}"' in response.text


def test_daily_report_detail_separates_confirmed_and_unconfirmed(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    report_id, operation_id = report.id, report.source_operation_id
    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-reports/{report_id}")
    assert response.status_code == 200
    assert "今日确认要闻" in response.text
    assert "值得关注的线索" in response.text
    assert response.text.count("尚未确认") >= 2
    assert f"Operation #{operation_id}" in response.text
    assert 'href="https://example.com/evidence"' in response.text
    assert 'target="_blank" rel="noopener noreferrer"' in response.text


def test_daily_report_posts_require_safe_action_token(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    client = TestClient(create_app(), base_url="http://127.0.0.1")
    response = client.post("/daily-reports", data={"window_hours": "24"})
    assert response.status_code == 400


def test_generate_redirects_and_rejects_invalid_or_missing_snapshot(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, token = safe_client_with_token(db_session, monkeypatch)
    invalid = client.post(
        "/daily-reports", data={"action_token": token, "window_hours": "12"}
    )
    assert invalid.status_code == 422, invalid.text
    client, token = safe_client_with_token(db_session, monkeypatch)
    missing = client.post(
        "/daily-reports", data={"action_token": token, "window_hours": "24"}
    )
    assert missing.status_code == 409


def test_generate_route_redirects_to_created_draft_without_external_calls(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    monkeypatch.setattr(
        "newsradar.daily_reports.service.DailyReportService.generate",
        lambda self, window_hours: report,
    )
    original_request = httpx.Client.request

    def reject_non_test_client(self, *args, **kwargs):
        if isinstance(self, TestClient):
            return original_request(self, *args, **kwargs)
        pytest.fail("network")

    monkeypatch.setattr(
        "httpx.Client.request", reject_non_test_client
    )
    monkeypatch.setattr(
        "httpx.AsyncClient.request", lambda *args, **kwargs: pytest.fail("network")
    )
    monkeypatch.setattr(
        "newsradar.ai.minimax.MiniMaxClient.structured",
        lambda *args, **kwargs: pytest.fail("model"),
    )
    client, token = safe_client_with_token(db_session, monkeypatch)
    response = client.post(
        "/daily-reports",
        data={"action_token": token, "window_hours": "24"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/daily-reports/{report_id}"


def test_draft_actions_redirect_and_archive_locks_editing(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[0]
    report_id, item_id = report.id, item.id
    client, token = safe_client_with_token(db_session, monkeypatch)
    toggled = client.post(
        f"/daily-reports/{report_id}/items/{item_id}/included",
        data={"action_token": token, "included": "false"},
        follow_redirects=False,
    )
    assert toggled.status_code == 303
    client, token = safe_client_with_token(db_session, monkeypatch)
    archived = client.post(
        f"/daily-reports/{report_id}/archive",
        data={"action_token": token},
        follow_redirects=False,
    )
    assert archived.status_code == 303
    page = client.get(f"/daily-reports/{report_id}")
    assert "创建修订版" in page.text
    assert "上移" not in page.text and "排除" not in page.text


def test_move_and_revise_routes_redirect_to_expected_report(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[0]
    report_id, item_id = report.id, item.id
    client, token = safe_client_with_token(db_session, monkeypatch)
    moved = client.post(
        f"/daily-reports/{report_id}/items/{item_id}/move",
        data={"action_token": token, "direction": "down"},
        follow_redirects=False,
    )
    assert moved.status_code == 303
    client, token = safe_client_with_token(db_session, monkeypatch)
    client.post(
        f"/daily-reports/{report_id}/archive",
        data={"action_token": token},
        follow_redirects=False,
    )
    client, token = safe_client_with_token(db_session, monkeypatch)
    revised = client.post(
        f"/daily-reports/{report_id}/revise",
        data={"action_token": token},
        follow_redirects=False,
    )
    assert revised.status_code == 303
    revision = db_session.scalar(
        select(DailyReportRecord).where(
            DailyReportRecord.supersedes_report_id == report_id
        )
    )
    assert revision is not None
    assert revised.headers["location"] == f"/daily-reports/{revision.id}"


def test_daily_report_routes_enforce_ownership_and_not_found(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    left, right = seed_two_daily_reports(db_session)
    foreign_item = DailyReportRepository(db_session).items(right.id)[0]
    left_id, foreign_item_id = left.id, foreign_item.id
    client, token = safe_client_with_token(db_session, monkeypatch)
    response = client.post(
        f"/daily-reports/{left_id}/items/{foreign_item_id}/included",
        data={"action_token": token, "included": "false"},
    )
    assert response.status_code == 404
    assert client.get("/daily-reports/999999").status_code == 404


def test_archived_page_does_not_follow_event_current_pointer(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    archived = DailyReportRepository(db_session, utcnow=lambda: NOW).archive(report.id)
    item = DailyReportRepository(db_session).items(archived.id)[0]
    archived_id = archived.id
    event = db_session.get(EventRecord, item.event_id)
    assert event is not None
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
    page = client.get(f"/daily-reports/{archived_id}")
    assert "确认事件" in page.text
    assert "后来修改的事件标题" not in page.text
