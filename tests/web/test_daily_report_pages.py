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
    DailyReportEditorialReviewDraft,
    DailyReportItemDraft,
    ReportSection,
)
from newsradar.db.models import (
    DailyReportRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    OperationRunRecord,
)
from newsradar.web.app import create_app
from newsradar.web.daily_report_queries import DailyReportQueryService
from tests.web.test_event_queries import _event, _pipeline_snapshot

NOW = datetime(2026, 7, 16, 4, tzinfo=UTC)

REVIEW_NEEDS_EVIDENCE = DailyReportEditorialReviewDraft.create(
    decision="needs_evidence",
    zh_title="人工标题",
    zh_summary="人工中文概述",
    review_recommendation="保留为线索并补充第一方证据",
    evidence_assessment="现有链接可发现，独立根数仍不足。",
)

REVIEW_EXCLUDE = DailyReportEditorialReviewDraft.create(
    decision="exclude",
    zh_title="排除标题",
    zh_summary="排除后的中文概述",
    review_recommendation="不纳入本期日报",
    evidence_assessment="后续证据不足以支持收录。",
)


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
    evidence_url: str = "https://example.com/evidence",
    minimax_degraded: bool = True,
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
                "minimax_degraded": minimax_degraded,
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
                        "independent_root_count": 2,
                        "confirmation_summary": "两条独立证据已交叉确认",
                        "limitations": ["仅覆盖公开资料"],
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
                                "url": evidence_url,
                                "published_at": NOW.isoformat(),
                                "role": "professional_media",
                                "independent": True,
                                "limitations": ["原始来源尚未回应"],
                            }
                        ],
                        "independent_root_count": 1,
                        "confirmation_summary": "仍需第一方来源确认",
                        "limitations": ["发布时间仍待复核"],
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
    older_row = response.text.split(f'href="/daily-reports/{older_id}"', 1)[1].split("</tr>", 1)[0]
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


def test_detail_projects_latest_editorial_review_and_ordered_history(
    db_session: Session,
) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    item = repository.items(report.id)[1]
    first = repository.save_editorial_review(report.id, item.id, REVIEW_NEEDS_EVIDENCE)
    latest = repository.save_editorial_review(report.id, item.id, REVIEW_EXCLUDE)

    detail = DailyReportQueryService(db_session).detail(report.id)

    assert detail is not None
    view = next(row for row in detail.emerging if row.item_id == item.id)
    assert view.snapshot["evidence"] == [
        {
            "title": "公开证据",
            "url": "https://example.com/evidence",
            "published_at": NOW.isoformat(),
            "role": "professional_media",
            "independent": True,
            "limitations": ["原始来源尚未回应"],
        }
    ]
    assert view.editorial_review is not None
    assert (
        view.editorial_review.review_id,
        view.editorial_review.revision,
        view.editorial_review.decision,
        view.editorial_review.zh_summary,
    ) == (latest.id, 2, "exclude", "排除后的中文概述")
    assert [review.review_id for review in view.editorial_history] == [
        first.id,
        latest.id,
    ]


def test_daily_report_detail_projects_and_renders_decision_brief(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    item = repository.items(report.id)[1]
    repository.save_editorial_review(report.id, item.id, REVIEW_NEEDS_EVIDENCE)

    detail = DailyReportQueryService(db_session).detail(report.id)
    assert detail is not None
    assert "News Codex" in detail.decision_script
    assert "待补证" in detail.decision_script
    assert REVIEW_NEEDS_EVIDENCE.zh_title in detail.decision_script

    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-reports/{report.id}")
    assert response.status_code == 200
    assert "今日决策简报" in response.text
    assert REVIEW_NEEDS_EVIDENCE.zh_title in response.text


def test_daily_report_detail_overview_uses_bound_operation_snapshot_versions(
    db_session: Session,
) -> None:
    confirmed = _event(
        db_session,
        event_id=8301,
        status="confirmed",
        title="快照已确认事件",
        occurred_at=NOW - timedelta(hours=1),
        display_tier="audit_only",
    )
    hotspot = _event(
        db_session,
        event_id=8302,
        status="emerging",
        title="快照热点事件",
        occurred_at=NOW - timedelta(hours=2),
        display_tier="hotspot",
    )
    signal = _event(
        db_session,
        event_id=8303,
        status="emerging",
        title="快照信号事件",
        occurred_at=NOW - timedelta(hours=3),
        display_tier="signal",
    )
    _event(
        db_session,
        event_id=8304,
        status="emerging",
        title="不应展示的审计事件",
        occurred_at=NOW - timedelta(hours=4),
        display_tier="audit_only",
    )
    operation = _pipeline_snapshot(
        db_session,
        refs=[(8301, 1), (8302, 1), (8303, 1), (8304, 1)],
        now=NOW,
    )
    report = DailyReportRepository(db_session, utcnow=lambda: NOW).create_draft(
        DailyReportDraft(
            report_date=NOW.date(),
            window_hours=24,
            window_start=NOW - timedelta(hours=24),
            window_end=NOW,
            source_operation_id=operation.id,
            generation_summary={},
            items=(),
        )
    )
    version = db_session.scalar(
        select(EventVersionRecord).where(
            EventVersionRecord.event_id == confirmed.id,
            EventVersionRecord.version_number == 1,
        )
    )
    assert version is not None
    db_session.add(
        EventVersionRecord(
            event_id=confirmed.id,
            version_number=2,
            zh_title="可变当前事件标题",
            zh_summary="不应进入全览。",
            payload={**version.payload, "status": "rejected"},
            created_at=NOW + timedelta(minutes=1),
        )
    )
    db_session.add(
        EventScoreRecord(
            event_id=confirmed.id,
            version_number=2,
            heat=1,
            breakdown={},
            created_at=NOW + timedelta(minutes=1),
        )
    )
    confirmed.current_version_number = 2
    confirmed.status = "rejected"
    confirmed.display_tier = "audit_only"
    db_session.commit()

    detail = DailyReportQueryService(db_session).detail(report.id)

    assert detail is not None
    assert [item.event_id for item in detail.overview.items] == [
        confirmed.id,
        hotspot.id,
        signal.id,
    ]
    assert [item.event_id for item in detail.overview.confirmed] == [confirmed.id]
    assert [item.event_id for item in detail.overview.hotspots] == [hotspot.id]
    assert [item.event_id for item in detail.overview.signals] == [signal.id]
    assert "快照已确认事件" in detail.overview.script
    assert "可变当前事件标题" not in detail.overview.script
    assert "不应展示的审计事件" not in detail.overview.script


def test_detail_projects_empty_editorial_review_fields_for_unreviewed_item(
    db_session: Session,
) -> None:
    report = seed_daily_report(db_session)

    detail = DailyReportQueryService(db_session).detail(report.id)

    assert detail is not None
    view = detail.confirmed[0]
    assert view.editorial_review is None
    assert view.editorial_history == ()


def test_archived_detail_retains_editorial_review_history(db_session: Session) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    item = repository.items(report.id)[1]
    review = repository.save_editorial_review(report.id, item.id, REVIEW_NEEDS_EVIDENCE)
    repository.archive(report.id)

    detail = DailyReportQueryService(db_session).detail(report.id)

    assert detail is not None
    view = next(row for row in detail.emerging if row.item_id == item.id)
    assert view.editorial_review is not None
    assert view.editorial_review.review_id == review.id
    assert view.editorial_history == (view.editorial_review,)


@pytest.mark.parametrize(
    ("minimax_degraded", "model_status"),
    ((True, "MiniMax：已降级"), (False, "MiniMax：未降级")),
)
def test_daily_report_detail_explains_model_and_evidence_quality(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    minimax_degraded: bool,
    model_status: str,
) -> None:
    report = seed_daily_report(db_session, minimax_degraded=minimax_degraded)
    report_id = report.id
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-reports/{report_id}")

    assert response.status_code == 200
    assert model_status in response.text
    assert "证据 1 条" in response.text
    assert "独立证据根 2" in response.text
    assert "确认说明：两条独立证据已交叉确认" in response.text
    assert "来源角色：专业媒体" in response.text
    assert "独立证据：是" in response.text
    assert "证据限制：原始来源尚未回应" in response.text
    assert "事件限制：发布时间仍待复核" in response.text


@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1/evidence",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.8/evidence",
        "http://[::1]/evidence",
        "http://2130706433/evidence",
        "http://0x7f000001/evidence",
        "http://127.1/evidence",
        "http://0177.0.0.1/evidence",
        "http://127.0.0.1\\foo",
        "http://10.0.0.1\\foo",
        "http://100.64.0.1/evidence",
    ),
)
def test_daily_report_detail_never_renders_non_public_snapshot_href(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    report = seed_daily_report(db_session, evidence_url=url)
    report_id = report.id
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-reports/{report_id}")

    assert response.status_code == 200
    assert f'href="{url}"' not in response.text


def test_daily_report_posts_require_safe_action_token(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    client = TestClient(create_app(), base_url="http://127.0.0.1")
    response = client.post("/daily-reports", data={"window_hours": "24"})
    assert response.status_code == 400


EDITORIAL_FORM = {
    "decision": "keep",
    "zh_title": "人工标题",
    "zh_summary": "人工中文概述",
    "review_recommendation": "建议保留并持续补证。",
    "evidence_assessment": "公开证据可追溯，但尚未达到独立确认门槛。",
}


def test_editorial_review_post_requires_token_and_writes_draft(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        data={"action_token": token, **EDITORIAL_FORM},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/daily-reports/{report.id}"
    saved = DailyReportQueryService(db_session).detail(report.id)
    assert saved is not None
    assert saved.emerging[0].editorial_review is not None
    assert saved.emerging[0].editorial_review.zh_title == "人工标题"


@pytest.mark.parametrize(
    ("values", "detail"),
    (
        (
            {"decision": "discard"},
            "审核结论仅支持保留、待补证、排除或合并重复。",
        ),
        ({"zh_title": ""}, "中文标题不能为空且不能超过 240 个字符。"),
        (
            {"zh_summary": "长" * 4001},
            "中文文章概述不能为空且不能超过 4000 个字符。",
        ),
    ),
)
def test_editorial_review_post_returns_mapped_chinese_validation_errors(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, str],
    detail: str,
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[0]
    client, token = safe_client_with_token(db_session, monkeypatch)

    response = client.post(
        f"/daily-reports/{report.id}/items/{item.id}/editorial-reviews",
        data={"action_token": token, **EDITORIAL_FORM, **values},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    current = DailyReportQueryService(db_session).detail(report.id)
    assert current is not None
    assert current.confirmed[0].editorial_review is None


def test_archived_editorial_review_post_returns_chinese_conflict(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[0]
    report_id, item_id = report.id, item.id
    DailyReportRepository(db_session).archive(report_id)
    client, token = safe_client_with_token(db_session, monkeypatch)

    response = client.post(
        f"/daily-reports/{report_id}/items/{item_id}/editorial-reviews",
        data={"action_token": token, **EDITORIAL_FORM},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "该日报已归档，不能再修改。"


def test_draft_detail_renders_editorial_form_without_quick_inclusion_actions(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[1]
    report_id, item_id = report.id, item.id
    DailyReportRepository(db_session).save_editorial_review(
        report_id, item_id, REVIEW_NEEDS_EVIDENCE
    )
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-reports/{report_id}")

    assert response.status_code == 200
    assert "编辑中文审核内容" in response.text
    assert f"/daily-reports/{report_id}/items/{item_id}/editorial-reviews" in response.text
    assert "人工审核版本" in response.text
    assert "人工标题" in response.text
    assert f"/daily-reports/{report_id}/items/{item_id}/included" not in response.text
    assert "上移" in response.text and "下移" in response.text


def test_archived_detail_shows_read_only_editorial_history(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[1]
    report_id, item_id = report.id, item.id
    repository = DailyReportRepository(db_session)
    repository.save_editorial_review(report_id, item_id, REVIEW_NEEDS_EVIDENCE)
    repository.save_editorial_review(report_id, item_id, REVIEW_EXCLUDE)
    repository.archive(report_id)
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-reports/{report_id}")

    assert response.status_code == 200
    assert "审核历史" in response.text
    assert "编辑中文审核内容" not in response.text
    history = response.text.split("<h4>审核历史</h4>", 1)[1]
    assert history.index("人工标题") < history.index("排除标题")


def test_duplicate_editorial_review_marks_item_not_included_on_detail_page(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[1]
    report_id, item_id = report.id, item.id
    client, token = safe_client_with_token(db_session, monkeypatch)

    response = client.post(
        f"/daily-reports/{report_id}/items/{item_id}/editorial-reviews",
        data={"action_token": token, **EDITORIAL_FORM, "decision": "duplicate"},
        follow_redirects=False,
    )
    page = client.get(f"/daily-reports/{report_id}")

    assert response.status_code == 303
    assert "本版未收录" in page.text


def test_generate_redirects_and_rejects_invalid_or_missing_snapshot(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, token = safe_client_with_token(db_session, monkeypatch)
    invalid = client.post("/daily-reports", data={"action_token": token, "window_hours": "12"})
    assert invalid.status_code == 422, invalid.text
    assert invalid.json()["detail"] == "时间窗口仅支持 24、48 或 72 小时。"
    assert "invalid_daily_report_window" not in invalid.text
    client, token = safe_client_with_token(db_session, monkeypatch)
    missing = client.post("/daily-reports", data={"action_token": token, "window_hours": "24"})
    assert missing.status_code == 409
    assert missing.json()["detail"] == "尚无完整事件运行快照，请先完成事件构建。"
    assert "complete_event_snapshot_required" not in missing.text


@pytest.mark.parametrize("included", (None, "yes", "1", "TRUE", ""))
def test_included_route_rejects_missing_or_invalid_boolean_without_mutation(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    included: str | None,
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[0]
    report_id, item_id = report.id, item.id
    client, token = safe_client_with_token(db_session, monkeypatch)
    data = {"action_token": token}
    if included is not None:
        data["included"] = included

    response = client.post(f"/daily-reports/{report_id}/items/{item_id}/included", data=data)

    assert response.status_code == 422
    assert response.json()["detail"] == "收录状态必须明确为 true 或 false。"
    assert DailyReportRepository(db_session).items(report_id)[0].included is True


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

    monkeypatch.setattr("httpx.Client.request", reject_non_test_client)
    monkeypatch.setattr("httpx.AsyncClient.request", lambda *args, **kwargs: pytest.fail("network"))
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
        select(DailyReportRecord).where(DailyReportRecord.supersedes_report_id == report_id)
    )
    assert revision is not None
    assert revised.headers["location"] == f"/daily-reports/{revision.id}"


def test_revise_route_from_older_parent_reuses_archived_direct_child(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    parent = seed_daily_report(db_session)
    parent_id = parent.id
    repository.archive(parent_id)
    child = repository.revise(parent_id)
    child_id = child.id
    repository.archive(child_id)
    client, token = safe_client_with_token(db_session, monkeypatch)

    response = client.post(
        f"/daily-reports/{parent_id}/revise",
        data={"action_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/daily-reports/{child_id}"
    assert [
        row.id
        for row in db_session.scalars(
            select(DailyReportRecord).where(DailyReportRecord.supersedes_report_id == parent_id)
        )
    ] == [child_id]


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
    assert "日报条目不存在或不属于当前日报。" in response.text
    assert "daily_report_item_not_found" not in response.text
    assert client.get("/daily-reports/999999").status_code == 404


def test_daily_report_routes_translate_known_conflicts_to_chinese(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[0]
    report_id, item_id = report.id, item.id
    DailyReportRepository(db_session).archive(report_id)

    client, token = safe_client_with_token(db_session, monkeypatch)
    archived = client.post(
        f"/daily-reports/{report_id}/items/{item_id}/included",
        data={"action_token": token, "included": "false"},
    )
    assert archived.status_code == 409
    assert archived.json()["detail"] == "该日报已归档，不能再修改。"
    assert "daily_report_archived" not in archived.text

    draft = seed_daily_report(db_session, report_date=date(2026, 7, 18), operation_id=4103)
    draft_id = draft.id
    draft_item_id = DailyReportRepository(db_session).items(draft_id)[0].id
    client, token = safe_client_with_token(db_session, monkeypatch)
    invalid_move = client.post(
        f"/daily-reports/{draft_id}/items/{draft_item_id}/move",
        data={"action_token": token, "direction": "sideways"},
    )
    assert invalid_move.status_code == 422
    assert invalid_move.json()["detail"] == "移动方向只能是上移或下移。"
    assert "invalid_daily_report_move" not in invalid_move.text


def test_generate_route_translates_ambiguous_snapshot_to_chinese(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_ambiguous(self, window_hours):
        raise ValueError("ambiguous_event_snapshot_versions")

    monkeypatch.setattr(
        "newsradar.daily_reports.service.DailyReportService.generate", reject_ambiguous
    )
    client, token = safe_client_with_token(db_session, monkeypatch)
    response = client.post("/daily-reports", data={"action_token": token, "window_hours": "24"})

    assert response.status_code == 409
    assert response.json()["detail"] == "事件运行快照包含冲突版本，暂时无法生成日报。"
    assert "ambiguous_event_snapshot_versions" not in response.text


@pytest.mark.parametrize("route", ("generate", "revise"))
def test_daily_report_routes_translate_exact_revision_conflict_only(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    if route == "revise":
        DailyReportRepository(db_session).archive(report_id)
        method = "newsradar.daily_reports.service.DailyReportService.revise"
        path = f"/daily-reports/{report_id}/revise"
        data: dict[str, str] = {}
    else:
        method = "newsradar.daily_reports.service.DailyReportService.generate"
        path = "/daily-reports"
        data = {"window_hours": "24"}

    def reject_conflict(*args, **kwargs):
        raise RuntimeError("daily_report_revision_conflict")

    monkeypatch.setattr(method, reject_conflict)
    client, token = safe_client_with_token(db_session, monkeypatch)
    response = client.post(path, data={"action_token": token, **data})

    assert response.status_code == 409
    assert response.json()["detail"] == "日报修订发生冲突，请刷新页面后重试。"
    assert "daily_report_revision_conflict" not in response.text


@pytest.mark.parametrize("route", ("generate", "revise"))
def test_daily_report_routes_do_not_swallow_unknown_runtime_error(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    if route == "revise":
        DailyReportRepository(db_session).archive(report_id)
        method = "newsradar.daily_reports.service.DailyReportService.revise"
        path = f"/daily-reports/{report_id}/revise"
        data: dict[str, str] = {}
    else:
        method = "newsradar.daily_reports.service.DailyReportService.generate"
        path = "/daily-reports"
        data = {"window_hours": "24"}

    def reject_unknown(*args, **kwargs):
        raise RuntimeError("unexpected_runtime_failure")

    monkeypatch.setattr(method, reject_unknown)
    client, token = safe_client_with_token(db_session, monkeypatch)
    with pytest.raises(RuntimeError, match="unexpected_runtime_failure"):
        client.post(path, data={"action_token": token, **data})


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
