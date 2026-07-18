from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.daily_reports import chinese_enrichment
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
    DailyReportAudioArtifactRecord,
    DailyReportOverviewEditorialReviewRecord,
    DailyReportOverviewItemRecord,
    DailyReportRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    OperationRunRecord,
)
from newsradar.operations.commands import OperationCommandService
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


def test_detail_projects_daily_chinese_enrichment_per_item(db_session: Session) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session)
    confirmed, emerging = repository.items(report.id)
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": {
            "candidate_total": 2,
            "processed": 2,
            "model_success": 1,
            "rule_fallback": 1,
            "budget_fallback": 0,
            "error_counts": {"http_429": 1},
            "items": {
                f"{confirmed.event_id}:1": {"origin": "model", "error_code": None},
                f"{emerging.event_id}:1": {
                    "origin": "rule_fallback",
                    "error_code": "http_429",
                },
            },
        },
    }
    db_session.commit()

    view = DailyReportQueryService(db_session).detail(report.id)

    assert view is not None
    assert view.chinese_enrichment.model_success == 1
    assert view.confirmed[0].chinese_origin is not None
    assert view.confirmed[0].chinese_origin.label_zh == "MiniMax"
    assert view.emerging[0].chinese_origin is not None
    assert view.emerging[0].chinese_origin.label_zh == "规则回退（请求频率受限）"


def test_detail_projects_partial_field_fallback_with_specific_reason(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = seed_daily_report(db_session)
    confirmed, emerging = DailyReportRepository(db_session).items(report.id)
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": {
            "candidate_total": 2,
            "processed": 2,
            "model_success": 1,
            "partial_fallback": 1,
            "rule_fallback": 0,
            "budget_fallback": 0,
            "error_counts": {"review_recommendation_non_chinese_output": 1},
            "items": {
                f"{confirmed.event_id}:1": {"origin": "model", "error_code": None},
                f"{emerging.event_id}:1": {
                    "origin": "model_partial",
                    "error_code": "review_recommendation_non_chinese_output",
                    "field_errors": ["review_recommendation_non_chinese_output"],
                },
            },
        },
    }
    db_session.commit()

    view = DailyReportQueryService(db_session).detail(report.id)

    assert view is not None
    assert view.chinese_enrichment.partial_fallback == 1
    assert view.emerging[0].chinese_origin is not None
    assert view.emerging[0].chinese_origin.label_zh == (
        "MiniMax 部分成功（中文审核建议不是有效简体中文）"
    )
    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-reports/{report.id}")
    assert "部分字段回退 1 条" in response.text


def test_daily_report_page_replaces_legacy_model_degraded_copy(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    items = DailyReportRepository(db_session).items(report.id)
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": {
            "candidate_total": 2,
            "processed": 2,
            "model_success": 1,
            "rule_fallback": 1,
            "budget_fallback": 0,
            "error_counts": {"http_429": 1},
            "items": {
                f"{items[0].event_id}:1": {"origin": "model", "error_code": None},
                f"{items[1].event_id}:1": {
                    "origin": "rule_fallback",
                    "error_code": "http_429",
                },
            },
        },
    }
    db_session.commit()
    report_id = report.id

    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-reports/{report_id}")

    assert "中文增强：MiniMax" in response.text
    assert "中文增强：规则回退（请求频率受限）" in response.text
    assert "MiniMax：已降级，本版使用规则中文内容" not in response.text


@pytest.mark.parametrize("audit", ({}, {"items": []}))
def test_malformed_chinese_enrichment_audit_keeps_legacy_display(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    audit: dict[str, object],
) -> None:
    report = seed_daily_report(db_session)
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": audit,
    }
    db_session.commit()
    report_id = report.id

    view = DailyReportQueryService(db_session).detail(report_id)
    assert view is not None
    assert view.chinese_enrichment.recorded is False

    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-reports/{report_id}")
    assert "MiniMax：已降级" in response.text
    assert "本版使用规则中文内容" in response.text


def test_detail_normalizes_unknown_chinese_enrichment_error_code(
    db_session: Session,
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[0]
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": {
            "candidate_total": 1,
            "processed": 1,
            "model_success": 0,
            "rule_fallback": 1,
            "budget_fallback": 0,
            "error_counts": {"untrusted": 1},
            "items": {
                f"{item.event_id}:{item.event_version_number}": {
                    "origin": "rule_fallback",
                    "error_code": "untrusted",
                }
            },
        },
    }
    db_session.commit()

    view = DailyReportQueryService(db_session).detail(report.id)

    assert view is not None
    assert view.chinese_enrichment.recorded is False
    assert view.confirmed[0].chinese_origin is None


def test_detail_rejects_non_string_partial_field_errors_without_crashing(
    db_session: Session,
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).items(report.id)[0]
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": {
            "candidate_total": 1,
            "processed": 1,
            "model_success": 0,
            "partial_fallback": 1,
            "rule_fallback": 0,
            "budget_fallback": 0,
            "error_counts": {"zh_summary_non_chinese_output": 1},
            "items": {
                f"{item.event_id}:{item.event_version_number}": {
                    "origin": "model_partial",
                    "error_code": "zh_summary_non_chinese_output",
                    "field_errors": [{"not": "a string"}],
                }
            },
        },
    }
    db_session.commit()

    view = DailyReportQueryService(db_session).detail(report.id)

    assert view is not None
    assert view.chinese_enrichment.recorded is False
    assert view.confirmed[0].chinese_origin is None


@pytest.mark.parametrize(
    "audit_update",
    [
        {"processed": 0},
        {"model_success": 0, "rule_fallback": 0},
        {"candidate_total": 0},
        {"model_budget": 1001},
        {"error_counts": {"timeout": 1}},
        {"items": {"not-an-event-version": {"origin": "model", "error_code": None}}},
        {"items": {"1:1": {"origin": "unknown", "error_code": None}}},
        {"items": {"1:1": {"origin": "model", "error_code": "timeout"}}},
        {"items": {"1:1": {"origin": "rule_fallback", "error_code": "private text"}}},
        {"items": {"1:1": {"origin": "budget_limit", "error_code": None}}},
    ],
)
def test_inconsistent_chinese_enrichment_audit_is_unrecorded(
    audit_update: dict[str, object],
) -> None:
    audit = {
        "candidate_total": 1,
        "processed": 1,
        "model_success": 1,
        "rule_fallback": 0,
        "budget_fallback": 0,
        "error_counts": {},
        "items": {"1:1": {"origin": "model", "error_code": None}},
    }
    audit.update(audit_update)

    from newsradar.web.daily_report_queries import _chinese_enrichment_view

    view, origins = _chinese_enrichment_view({"daily_chinese_enrichment": audit})

    assert view.recorded is False
    assert origins == {}


def test_every_persistable_chinese_enrichment_error_has_safe_chinese_label() -> None:
    daily_chinese_error_labels = chinese_enrichment.DAILY_CHINESE_ERROR_LABELS
    items = {
        f"{index}:1": {
            "origin": "budget_limit" if code == "budget_limit" else "rule_fallback",
            "error_code": code,
        }
        for index, code in enumerate(daily_chinese_error_labels, start=1)
    }
    audit = {
        "candidate_total": len(items),
        "processed": len(items),
        "model_success": 0,
        "rule_fallback": len(items) - 1,
        "budget_fallback": 1,
        "error_counts": {code: 1 for code in daily_chinese_error_labels},
        "items": items,
    }

    from newsradar.web.daily_report_queries import _chinese_enrichment_view

    view, origins = _chinese_enrichment_view({"daily_chinese_enrichment": audit})

    assert view.recorded is True
    assert set(view.error_labels) == set(daily_chinese_error_labels)
    assert all(
        label and any("\u3400" <= char <= "\u9fff" for char in label)
        for label in view.error_labels.values()
    )
    assert {origin.error_code for origin in origins.values()} == set(daily_chinese_error_labels)
    assert all("private" not in origin.label_zh for origin in origins.values())


def test_daily_report_page_shows_pending_and_budget_limit_enrichment_states(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    confirmed, emerging = DailyReportRepository(db_session).items(report.id)
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": {
            "candidate_total": 3,
            "processed": 2,
            "model_success": 1,
            "rule_fallback": 0,
            "budget_fallback": 1,
            "error_counts": {"budget_limit": 1},
            "items": {
                f"{confirmed.event_id}:{confirmed.event_version_number}": {
                    "origin": "model",
                    "error_code": None,
                },
                f"{emerging.event_id}:{emerging.event_version_number}": {
                    "origin": "budget_limit",
                    "error_code": "budget_limit",
                },
            },
        },
    }
    db_session.commit()
    report_id = report.id

    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-reports/{report_id}")

    assert "安全上限回退 1 条" in response.text
    assert "待处理 1 条" in response.text
    assert "中文增强：安全上限回退（本期安全上限）" in response.text


def test_detail_matches_chinese_audit_by_event_id_and_version(
    db_session: Session,
) -> None:
    report = seed_daily_report(db_session)
    confirmed, emerging = DailyReportRepository(db_session).items(report.id)
    emerging.event_id = confirmed.event_id
    emerging.event_version_number = confirmed.event_version_number + 1
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": {
            "candidate_total": 1,
            "processed": 1,
            "model_success": 1,
            "rule_fallback": 0,
            "budget_fallback": 0,
            "error_counts": {},
            "items": {
                f"{emerging.event_id}:{emerging.event_version_number}": {
                    "origin": "model",
                    "error_code": None,
                }
            },
        },
    }
    db_session.commit()

    view = DailyReportQueryService(db_session).detail(report.id)

    assert view is not None
    assert view.confirmed[0].chinese_origin is None
    assert view.emerging[0].chinese_origin is not None
    assert view.emerging[0].chinese_origin.label_zh == "MiniMax"


def test_model_enrichment_projection_replaces_stale_event_fallback_copy(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session)
    model_item, fallback_item = repository.items(report.id)
    model_overview, fallback_overview = repository.overview_items(report.id)
    stale_reason = "已按可追溯规则汇总；中文增强暂不可用。"
    stale_limitation = "中文模型不可用，当前使用规则回退"
    retained_limitation = "仅覆盖公开资料"
    model_item.snapshot = {
        **model_item.snapshot,
        "why_it_matters": stale_reason,
        "limitations": [stale_limitation, retained_limitation],
    }
    model_overview.snapshot = {
        **model_overview.snapshot,
        "why_it_matters": stale_reason,
        "limitations": [stale_limitation, retained_limitation],
    }
    fallback_item.snapshot = {
        **fallback_item.snapshot,
        "why_it_matters": "规则回退原因必须保留",
        "limitations": [stale_limitation, "发布时间仍待复核"],
    }
    fallback_overview.snapshot = {
        **fallback_overview.snapshot,
        "why_it_matters": "规则回退原因必须保留",
        "limitations": [stale_limitation, "发布时间仍待复核"],
    }
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": {
            "candidate_total": 2,
            "processed": 2,
            "model_success": 1,
            "rule_fallback": 1,
            "budget_fallback": 0,
            "error_counts": {"no_api_key": 1},
            "items": {
                f"{model_item.event_id}:{model_item.event_version_number}": {
                    "origin": "model",
                    "error_code": None,
                },
                f"{fallback_item.event_id}:{fallback_item.event_version_number}": {
                    "origin": "rule_fallback",
                    "error_code": "no_api_key",
                },
            },
        },
    }
    repository.save_editorial_review(
        report.id,
        model_item.id,
        DailyReportEditorialReviewDraft.create(
            decision="keep",
            zh_title="模型中文标题",
            zh_summary="模型中文文章概述。",
            review_recommendation="继续核验公开材料。",
            evidence_assessment="确认状态和证据未由模型改变。",
        ),
    )
    repository.save_overview_editorial_review(
        report.id,
        model_overview.id,
        DailyReportOverviewEditorialReviewDraft.create(
            decision="keep",
            zh_title="模型中文标题",
            zh_summary="模型中文文章概述。",
            review_recommendation="继续核验公开材料。",
            evidence_assessment="确认状态和证据未由模型改变。",
        ),
    )
    db_session.commit()

    detail = DailyReportQueryService(db_session).detail(report.id)

    assert detail is not None
    model_view = detail.confirmed[0]
    fallback_view = detail.emerging[0]
    assert model_view.snapshot["why_it_matters"] == (
        "本条中文标题和概述已完成日报增强；确认状态、证据与收录范围仍以固定快照为准。"
    )
    assert model_view.snapshot["limitations"] == [retained_limitation]
    assert fallback_view.snapshot["why_it_matters"] == "规则回退原因必须保留"
    assert fallback_view.snapshot["limitations"] == [
        stale_limitation,
        "发布时间仍待复核",
    ]
    model_overview_view = detail.overview.items[0]
    assert model_overview_view.why_it_matters == model_view.snapshot["why_it_matters"]
    assert model_overview_view.snapshot["limitations"] == [retained_limitation]

    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-reports/{report.id}")

    assert response.status_code == 200
    assert "模型中文标题" in response.text
    assert "中文增强：MiniMax" in response.text
    assert stale_reason not in response.text
    assert "规则回退原因必须保留" in response.text
    assert retained_limitation in response.text
    assert "发布时间仍待复核" in response.text


def test_model_enrichment_projection_preserves_event_specific_reason(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session)
    model_item = repository.items(report.id)[0]
    model_overview = repository.overview_items(report.id)[0]
    event_specific_reason = "该事件会直接影响开发者部署节奏。"
    stale_limitation = "中文模型不可用，当前使用规则回退"
    retained_limitation = "仅覆盖公开资料"
    model_item.snapshot = {
        **model_item.snapshot,
        "why_it_matters": event_specific_reason,
        "limitations": [stale_limitation, retained_limitation],
    }
    model_overview.snapshot = {
        **model_overview.snapshot,
        "why_it_matters": event_specific_reason,
        "limitations": [stale_limitation, retained_limitation],
    }
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": {
            "candidate_total": 1,
            "processed": 1,
            "model_success": 1,
            "rule_fallback": 0,
            "budget_fallback": 0,
            "error_counts": {},
            "items": {
                f"{model_item.event_id}:{model_item.event_version_number}": {
                    "origin": "model",
                    "error_code": None,
                }
            },
        },
    }
    db_session.commit()

    detail = DailyReportQueryService(db_session).detail(report.id)

    assert detail is not None
    assert detail.confirmed[0].snapshot["why_it_matters"] == event_specific_reason
    assert detail.confirmed[0].snapshot["limitations"] == [retained_limitation]
    assert detail.overview.items[0].why_it_matters == event_specific_reason
    assert detail.overview.items[0].snapshot["limitations"] == [retained_limitation]

    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-reports/{report.id}")
    assert response.status_code == 200
    assert event_specific_reason in response.text
    assert "本条中文标题和概述已完成日报增强" not in response.text


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
            overview_items=(
                DailyReportOverviewItemDraft(
                    event_id=operation_id * 10 + 1,
                    event_version_number=1,
                    position=1,
                    snapshot={
                        "zh_title": "确认事件",
                        "zh_summary": "确认摘要",
                        "why_it_matters": "确认影响",
                        "status": "confirmed",
                        "unconfirmed": False,
                        "display_tier": "hotspot",
                        "rank_score": 90.0,
                        "independent_root_count": 2,
                        "confirmation_summary": "两条独立证据已交叉确认",
                        "limitations": ["仅覆盖公开资料"],
                        "evidence": [],
                    },
                    decision_event_id=operation_id * 10 + 1,
                ),
                DailyReportOverviewItemDraft(
                    event_id=operation_id * 10 + 2,
                    event_version_number=1,
                    position=2,
                    snapshot={
                        "zh_title": "线索事件",
                        "zh_summary": "线索摘要",
                        "why_it_matters": "线索影响",
                        "status": "emerging",
                        "unconfirmed": True,
                        "display_tier": "signal",
                        "rank_score": 80.0,
                        "independent_root_count": 1,
                        "confirmation_summary": "仍需第一方来源确认",
                        "limitations": ["发布时间仍待复核"],
                        "evidence": [],
                    },
                    decision_event_id=operation_id * 10 + 2,
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


def review_overview_for_audio(session: Session, report_id: int) -> None:
    repository = DailyReportRepository(session, utcnow=lambda: NOW)
    for index, item in enumerate(repository.overview_items(report_id)):
        repository.save_overview_editorial_review(
            report_id,
            item.id,
            DailyReportOverviewEditorialReviewDraft.create(
                decision="keep" if index == 0 else "needs_evidence",
                zh_title=f"已审核全览标题 {index + 1}",
                zh_summary=f"已审核全览概述 {index + 1}",
                review_recommendation="继续关注并核验后续。",
                evidence_assessment=(
                    "已有可靠公开证据。" if index == 0 else "尚待进一步确认第一方来源。"
                ),
            ),
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


def test_detail_projects_editorial_summary_counts(db_session: Session) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    emerging = repository.items(report.id)[1]
    repository.save_editorial_review(report.id, emerging.id, REVIEW_NEEDS_EVIDENCE)

    detail = DailyReportQueryService(db_session).detail(report.id)

    assert detail is not None
    assert detail.editorial_summary.total_count == 2
    assert detail.editorial_summary.included_count == 2
    assert detail.editorial_summary.needs_evidence_count == 1
    assert detail.editorial_summary.excluded_count == 0
    assert detail.editorial_summary.duplicate_count == 0
    assert detail.editorial_summary.unreviewed_count == 1


def test_daily_report_detail_renders_readable_summary_and_decision_cards(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    emerging = repository.items(report.id)[1]
    repository.save_editorial_review(report.id, emerging.id, REVIEW_NEEDS_EVIDENCE)
    report_id = report.id
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-reports/{report_id}")

    assert response.status_code == 200
    assert 'class="daily-report-page"' in response.text
    assert "本期条目" in response.text and ">2</dd>" in response.text
    assert "决策收录" in response.text
    assert "待补证" in response.text
    assert "未收录" in response.text
    assert response.text.count('class="decision-item-card') == 2
    assert "中文文章概述" in response.text
    assert "中文审核建议" in response.text
    assert "中文证据评价" in response.text
    assert "<summary>查看决策版播报稿</summary>" in response.text

    styles = client.get("/static/styles.css")
    assert styles.status_code == 200
    assert ".daily-report-page" in styles.text
    assert ".daily-report-metrics" in styles.text
    assert ".decision-item-card" in styles.text
    assert ".overview-item-card" in styles.text


def test_archived_daily_report_renders_audio_actions_and_latest_player(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    review_overview_for_audio(db_session, report.id)
    DailyReportRepository(db_session, utcnow=lambda: NOW).archive(report.id)
    report_id = report.id
    artifact = DailyReportAudioArtifactRecord(
        daily_report_id=report_id,
        rendition="decision",
        status="succeeded",
        script="固定决策文稿",
        script_sha256="a" * 64,
        model="speech-2.8-hd",
        voice_id="male-qn-qingse",
        audio_format="mp3",
        sample_rate=32000,
        bitrate=128000,
        channel=1,
        relative_audio_path=f"{report_id}/existing.mp3",
        audio_sha256="b" * 64,
    )
    db_session.add(artifact)
    db_session.commit()
    artifact_id = artifact.id
    client, token = safe_client_with_token(db_session, monkeypatch)

    page = client.get(f"/daily-reports/{report_id}")

    assert page.status_code == 200
    assert f'action="/daily-reports/{report_id}/audio/decision"' in page.text
    assert f'action="/daily-reports/{report_id}/audio/overview"' in page.text
    assert f'src="/daily-reports/{report_id}/audio-artifacts/{artifact_id}"' in page.text
    assert "生成失败" not in page.text

    response = client.post(
        f"/daily-reports/{report_id}/audio/overview",
        data={"action_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    operation = db_session.scalar(
        select(OperationRunRecord)
        .where(OperationRunRecord.operation_type == "daily_report_audio")
        .order_by(OperationRunRecord.id.desc())
    )
    assert operation is not None
    assert operation.requested_scope == {
        "daily_report_id": report_id,
        "rendition": "overview",
    }


def test_overview_audio_enqueue_requires_all_candidates_reviewed(
    db_session: Session,
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    DailyReportRepository(db_session, utcnow=lambda: NOW).archive(report_id)

    with pytest.raises(ValueError, match="daily_report_overview_review_incomplete"):
        OperationCommandService(db_session).enqueue_daily_report_audio(
            report_id=report_id,
            rendition="overview",
            trigger="test",
        )


def test_overview_audio_enqueue_rejects_fully_reviewed_report_with_no_included_items(
    db_session: Session,
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    for item in repository.overview_items(report_id):
        repository.save_overview_editorial_review(
            report_id,
            item.id,
            DailyReportOverviewEditorialReviewDraft.create(
                decision="exclude",
                zh_title="排除全览标题",
                zh_summary="排除全览概述",
                review_recommendation="不进入全览",
                evidence_assessment="当前证据无法验证。",
            ),
        )
    repository.archive(report_id)

    with pytest.raises(ValueError, match="daily_report_overview_has_no_included_items"):
        OperationCommandService(db_session).enqueue_daily_report_audio(
            report_id=report_id,
            rendition="overview",
            trigger="test",
        )


def test_overview_audio_enqueue_accepts_completed_review_and_decision_is_unaffected(
    db_session: Session,
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    review_overview_for_audio(db_session, report_id)
    DailyReportRepository(db_session, utcnow=lambda: NOW).archive(report_id)

    overview_operation = OperationCommandService(db_session).enqueue_daily_report_audio(
        report_id=report_id,
        rendition="overview",
        trigger="test",
    )
    decision_operation = OperationCommandService(db_session).enqueue_daily_report_audio(
        report_id=report_id,
        rendition="decision",
        trigger="test",
    )

    assert overview_operation != decision_operation


def test_archiving_daily_report_automatically_queues_decision_audio(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    client, token = safe_client_with_token(db_session, monkeypatch)

    response = client.post(
        f"/daily-reports/{report_id}/archive",
        data={"action_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    operation = db_session.scalar(
        select(OperationRunRecord)
        .where(OperationRunRecord.operation_type == "daily_report_audio")
        .order_by(OperationRunRecord.id.desc())
    )
    assert operation is not None
    assert operation.trigger == "daily_archive"
    assert len(operation.trigger) <= 16
    assert operation.requested_scope == {
        "daily_report_id": report_id,
        "rendition": "decision",
    }


def test_daily_report_audio_enqueue_reuses_active_operation_and_page_explains_queue(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    DailyReportRepository(db_session, utcnow=lambda: NOW).archive(report_id)

    first = OperationCommandService(db_session).enqueue_daily_report_audio(
        report_id=report_id, rendition="decision", trigger="test"
    )
    second = OperationCommandService(db_session).enqueue_daily_report_audio(
        report_id=report_id, rendition="decision", trigger="test"
    )

    assert first == second
    assert db_session.scalars(
        select(OperationRunRecord).where(OperationRunRecord.operation_type == "daily_report_audio")
    ).all() == [db_session.get(OperationRunRecord, first)]
    client, _token = safe_client_with_token(db_session, monkeypatch)
    page = client.get(f"/daily-reports/{report_id}")
    assert "语音任务已排队" in page.text
    assert f'action="/daily-reports/{report_id}/audio/decision"' not in page.text


def test_daily_report_audio_enqueue_rejects_trashed_report_with_safe_diagnostic(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    repository.archive(report_id)
    repository.move_to_trash(report_id)
    client, token = safe_client_with_token(db_session, monkeypatch)

    response = client.post(
        f"/daily-reports/{report_id}/audio/decision",
        data={"action_token": token},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "日报已在回收站中，不能创建语音任务。"
    assert db_session.scalars(
        select(OperationRunRecord).where(OperationRunRecord.operation_type == "daily_report_audio")
    ).all() == []


def test_archive_rolls_back_when_automatic_audio_enqueue_fails(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id

    def fail_enqueue(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr("newsradar.operations.repository.OperationRepository.enqueue", fail_enqueue)

    with pytest.raises(RuntimeError, match="queue unavailable"):
        OperationCommandService(db_session).archive_and_enqueue_daily_report_audio(
            report_id=report_id, trigger="test"
        )

    restored = db_session.get(DailyReportRecord, report_id)
    assert restored is not None
    assert restored.status == "draft"


def test_daily_report_audio_artifact_route_serves_only_matching_safe_file(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    DailyReportRepository(db_session, utcnow=lambda: NOW).archive(report_id)
    artifact = DailyReportAudioArtifactRecord(
        daily_report_id=report_id,
        rendition="decision",
        status="succeeded",
        script="固定决策文稿",
        script_sha256="a" * 64,
        model="speech-2.8-hd",
        voice_id="male-qn-qingse",
        audio_format="mp3",
        sample_rate=32000,
        bitrate=128000,
        channel=1,
        relative_audio_path=f"{report_id}/ready.mp3",
        audio_sha256="b" * 64,
    )
    db_session.add(artifact)
    db_session.commit()
    artifact_id = artifact.id
    path = tmp_path / str(report_id) / "ready.mp3"
    path.parent.mkdir()
    path.write_bytes(b"ID3-safe-audio")
    monkeypatch.setattr("newsradar.web.app._DAILY_REPORT_AUDIO_ROOT", tmp_path)
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-reports/{report_id}/audio-artifacts/{artifact_id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"ID3-safe-audio"

    stored = db_session.get(DailyReportAudioArtifactRecord, artifact_id)
    assert stored is not None
    stored.relative_audio_path = "../escape.mp3"
    db_session.commit()
    rejected = client.get(f"/daily-reports/{report_id}/audio-artifacts/{artifact_id}")
    assert rejected.status_code == 404


def test_daily_report_detail_overview_uses_bound_operation_snapshot_versions(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
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
    assert detail.overview.legacy_unreviewed is True
    assert "快照已确认事件" not in detail.overview.script
    assert "可变当前事件标题" not in detail.overview.script
    assert "不应展示的审计事件" not in detail.overview.script

    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-reports/{report.id}")
    assert response.status_code == 200
    assert "全部 3 条" in response.text
    assert "快照已确认事件" in response.text
    assert "快照热点事件" in response.text
    assert "快照信号事件" in response.text
    assert response.text.count('class="overview-audit-card') == 3
    assert "<summary>查看全览版播报稿</summary>" in response.text


def test_detail_projects_all_overview_candidates_but_scripts_only_reviewed_included(
    db_session: Session,
) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original_items = repository.overview_items(report.id)
    for offset in range(3):
        event_id = report.source_operation_id * 10 + 3 + offset
        db_session.add(
            EventRecord(
                id=event_id,
                canonical_key=f"web-overview-extra-{event_id}",
                status="emerging",
                current_version_number=1,
                occurred_at=NOW,
            )
        )
        db_session.flush()
        db_session.add(
            DailyReportOverviewItemRecord(
                daily_report_id=report.id,
                event_id=event_id,
                event_version_number=1,
                position=3 + offset,
                snapshot={
                    "zh_title": f"额外事件 {offset + 1}",
                    "zh_summary": "额外事件概述",
                    "why_it_matters": "用于审核投影测试",
                    "status": "emerging",
                    "display_tier": "signal",
                    "rank_score": 70.0 - offset,
                    "confirmation_summary": "尚待核验",
                    "evidence": [],
                    "limitations": [],
                },
            )
        )
    db_session.commit()
    items = repository.overview_items(report.id)

    repository.save_overview_editorial_review(
        report.id,
        items[0].id,
        DailyReportOverviewEditorialReviewDraft.create(
            decision="keep",
            zh_title="人工保留标题",
            zh_summary="人工保留概述",
            review_recommendation="继续关注",
            evidence_assessment="已有可靠公开证据。",
        ),
    )
    repository.save_overview_editorial_review(
        report.id,
        items[1].id,
        DailyReportOverviewEditorialReviewDraft.create(
            decision="needs_evidence",
            zh_title="人工待补证标题",
            zh_summary="人工待补证概述",
            review_recommendation="寻找第一方来源",
            evidence_assessment="目前只有单一来源。",
        ),
    )
    repository.save_overview_editorial_review(
        report.id,
        items[2].id,
        DailyReportOverviewEditorialReviewDraft.create(
            decision="exclude",
            zh_title="人工排除标题",
            zh_summary="人工排除概述",
            review_recommendation="不纳入全览",
            evidence_assessment="无法验证原始事实。",
        ),
    )
    repository.save_overview_editorial_review(
        report.id,
        items[3].id,
        DailyReportOverviewEditorialReviewDraft.create(
            decision="duplicate",
            zh_title="人工重复标题",
            zh_summary="人工重复概述",
            review_recommendation="合并到保留事件",
            evidence_assessment="原始事实一致。",
            duplicate_of_overview_item_id=items[0].id,
        ),
    )

    detail = DailyReportQueryService(db_session).detail(report.id)

    assert detail is not None
    assert len(original_items) == 2
    assert len(detail.overview.items) == 5
    assert detail.overview.summary.total_count == 5
    assert detail.overview.summary.included_count == 2
    assert detail.overview.summary.needs_evidence_count == 1
    assert detail.overview.summary.excluded_count == 1
    assert detail.overview.summary.duplicate_count == 1
    assert detail.overview.summary.unreviewed_count == 1
    assert "人工保留标题" in detail.overview.script
    assert "尚待进一步确认：人工待补证标题" in detail.overview.script
    assert "人工排除标题" not in detail.overview.script
    assert "人工重复标题" not in detail.overview.script
    assert "额外事件 3" not in detail.overview.script
    assert detail.overview.items[3].duplicate_of_overview_item_id == items[0].id


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


def test_daily_brief_and_overview_render_safe_original_article_links(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_url = "https://example.com/original-article"
    report = seed_daily_report(db_session, evidence_url=source_url)
    report_id = report.id
    decision_item = DailyReportRepository(db_session).items(report.id)[0]
    decision_item.snapshot = {
        **decision_item.snapshot,
        "evidence": [{"title": "官方原文", "url": source_url}],
    }
    overview_item = DailyReportRepository(db_session).overview_items(report.id)[0]
    overview_item.snapshot = {
        **overview_item.snapshot,
        "evidence": [{"title": "官方原文", "url": source_url}],
    }
    db_session.commit()
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-reports/{report_id}")

    assert response.status_code == 200
    assert response.text.count(f'href="{source_url}"') >= 3
    assert "查看原文" in response.text
    assert 'target="_blank" rel="noopener noreferrer"' in response.text


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

OVERVIEW_EDITORIAL_FORM = {
    "decision": "needs_evidence",
    "zh_title": "全览人工标题",
    "zh_summary": "全览中文文章概述",
    "review_recommendation": "继续寻找第一方公告。",
    "evidence_assessment": "目前只有单一公开来源。",
    "duplicate_of_overview_item_id": "",
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


def test_overview_editorial_review_post_requires_token_and_writes_draft(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).overview_items(report.id)[1]
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    forbidden = client.post(
        f"/daily-reports/{report.id}/overview-items/{item.id}/editorial-reviews",
        data=OVERVIEW_EDITORIAL_FORM,
    )

    assert forbidden.status_code == 400
    client, token = safe_client_with_token(db_session, monkeypatch)
    response = client.post(
        f"/daily-reports/{report.id}/overview-items/{item.id}/editorial-reviews",
        data={"action_token": token, **OVERVIEW_EDITORIAL_FORM},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (f"/daily-reports/{report.id}#overview-item-{item.id}")
    saved = DailyReportQueryService(db_session).detail(report.id)
    assert saved is not None
    saved_item = next(row for row in saved.overview.items if row.item_id == item.id)
    assert saved_item.editorial_review is not None
    assert saved_item.editorial_review.zh_title == "全览人工标题"


def test_page_warns_about_corrupted_review_text_and_exposes_report_sections(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).overview_items(report.id)[0]
    db_session.add(
        DailyReportOverviewEditorialReviewRecord(
            daily_report_overview_item_id=item.id,
            revision=1,
            decision="keep",
            zh_title="中文标题",
            zh_summary="中文概述。",
            review_recommendation="????",
            evidence_assessment="当前证据可供审核。",
            created_at=NOW,
        )
    )
    db_session.commit()

    detail = DailyReportQueryService(db_session).detail(report.id)
    assert detail is not None
    assert detail.text_integrity.corrupted_review_count == 1

    client, _token = safe_client_with_token(db_session, monkeypatch)
    page = client.get(f"/daily-reports/{report.id}")

    assert page.status_code == 200
    assert "检测到疑似编码损坏" in page.text
    assert 'href="#decision-brief-heading"' in page.text
    assert 'href="#overview-heading"' in page.text
    assert 'href="#complete-report-heading"' in page.text
    assert "完整报告与证据" in page.text


def test_overview_editorial_review_post_returns_chinese_integrity_error(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    item = DailyReportRepository(db_session).overview_items(report.id)[0]
    client, token = safe_client_with_token(db_session, monkeypatch)

    response = client.post(
        f"/daily-reports/{report.id}/overview-items/{item.id}/editorial-reviews",
        data={"action_token": token, **OVERVIEW_EDITORIAL_FORM, "zh_summary": "????"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "检测到疑似编码损坏的连续问号，请修正中文内容后再继续。"


def test_page_hides_corrupted_editorial_history_text_after_repair(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    item = repository.overview_items(report.id)[0]
    report_id = report.id
    db_session.add(
        DailyReportOverviewEditorialReviewRecord(
            daily_report_overview_item_id=item.id,
            revision=1,
            decision="keep",
            zh_title="????",
            zh_summary="中文概述。",
            review_recommendation="继续关注。",
            evidence_assessment="当前证据可供审核。",
            created_at=NOW,
        )
    )
    db_session.commit()
    repository.save_overview_editorial_review(
        report.id,
        item.id,
        DailyReportOverviewEditorialReviewDraft.create(
            decision="keep",
            zh_title="修复后的中文标题",
            zh_summary="修复后的中文概述。",
            review_recommendation="继续关注后续公开材料。",
            evidence_assessment="当前证据可供审核。",
        ),
    )
    repository.archive(report_id)

    client, _token = safe_client_with_token(db_session, monkeypatch)
    page = client.get(f"/daily-reports/{report_id}")

    assert "????" not in page.text
    assert "历史审核内容因编码损坏未展示" in page.text


def test_draft_page_renders_overview_summary_all_candidates_and_chinese_review_form(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    first, second = repository.overview_items(report.id)
    report_id, first_id, second_id = report.id, first.id, second.id
    repository.save_overview_editorial_review(
        report.id,
        first.id,
        DailyReportOverviewEditorialReviewDraft.create(
            decision="keep",
            zh_title="<script>人工保留标题</script>",
            zh_summary="人工保留概述\n第二段",
            review_recommendation="继续关注",
            evidence_assessment="已有第一方证据。",
        ),
    )
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-reports/{report_id}")

    assert response.status_code == 200
    assert "情报全览审核" in response.text
    assert "候选总数" in response.text and ">2<" in response.text
    assert "进入全览" in response.text and ">1<" in response.text
    assert "未审核" in response.text and "尚有 1 条" in response.text
    assert response.text.count('class="overview-audit-card') == 2
    assert f'id="overview-item-{first_id}"' in response.text
    assert f'id="overview-item-{second_id}"' in response.text
    assert (
        f"/daily-reports/{report_id}/overview-items/{second_id}/editorial-reviews" in response.text
    )
    assert "中文文章概述" in response.text
    assert "中文审核建议" in response.text
    assert "中文证据评价" in response.text
    assert "<script>人工保留标题</script>" not in response.text
    assert "&lt;script&gt;人工保留标题&lt;/script&gt;" in response.text


def test_overview_body_marks_needs_evidence_items_with_explicit_warning(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    item = repository.overview_items(report.id)[0]
    report_id = report.id
    repository.save_overview_editorial_review(
        report.id,
        item.id,
        DailyReportOverviewEditorialReviewDraft.create(
            decision="needs_evidence",
            zh_title="待补证全览标题",
            zh_summary="待补证全览概述",
            review_recommendation="继续查找第一方公告。",
            evidence_assessment="当前只有单一公开来源。",
        ),
    )
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-reports/{report_id}")

    assert response.status_code == 200
    assert '<span class="overview-brief-warning">尚待进一步确认</span>' in response.text


def test_archived_page_keeps_overview_audit_history_read_only(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    item = repository.overview_items(report.id)[0]
    report_id, item_id = report.id, item.id
    repository.save_overview_editorial_review(
        report.id,
        item.id,
        DailyReportOverviewEditorialReviewDraft.create(
            decision="keep",
            zh_title="归档全览标题",
            zh_summary="归档全览概述",
            review_recommendation="继续关注",
            evidence_assessment="已有第一方证据。",
        ),
    )
    repository.archive(report.id)
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-reports/{report_id}")

    assert response.status_code == 200
    assert "全览审核历史" in response.text
    assert "编辑全览中文审核" not in response.text
    assert (
        f"/daily-reports/{report_id}/overview-items/{item_id}/editorial-reviews"
        not in response.text
    )


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
    assert "上移" not in page.text
    assert '<option value="exclude"' not in page.text


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


def test_archive_page_shows_pin_and_trash_controls(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    DailyReportRepository(db_session).archive(report.id)
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get("/daily-reports")

    assert response.status_code == 200
    assert "置顶保护" in response.text
    assert "移入回收站" in response.text
    assert 'href="/daily-reports/trash"' in response.text


def test_trashed_detail_redirects_to_private_body_free_trash_page(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    report.generation_summary = {"private_marker": "private report body must not render"}
    db_session.commit()
    DailyReportRepository(db_session).move_to_trash(report_id)
    client, _token = safe_client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-reports/{report_id}", follow_redirects=False)
    trash = client.get("/daily-reports/trash")

    assert response.status_code == 303
    assert response.headers["location"] == "/daily-reports/trash"
    assert trash.status_code == 200
    assert "恢复" in trash.text
    assert "private report body must not render" not in trash.text


def test_bulk_trash_rejects_more_than_fifty_unique_positive_ids(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, token = safe_client_with_token(db_session, monkeypatch)

    response = client.post(
        "/daily-reports/bulk/trash",
        content=urlencode(
            [("action_token", token), *(("report_ids", str(value)) for value in range(1, 52))]
        ),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "一次最多操作 50 份日报。"


def test_safe_bulk_trash_and_restore_reach_their_static_handlers(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = seed_two_daily_reports(db_session)
    report_ids = (first.id, second.id)
    client, token = safe_client_with_token(db_session, monkeypatch)

    trashed = client.post(
        "/daily-reports/bulk/trash",
        content=urlencode(
            [("action_token", token), *(("report_ids", str(report_id)) for report_id in report_ids)]
        ),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )

    assert trashed.status_code == 303
    assert trashed.headers["location"].startswith("/daily-reports?")
    assert all(
        db_session.get(DailyReportRecord, report_id).deleted_at is not None
        for report_id in report_ids
    )

    client, token = safe_client_with_token(db_session, monkeypatch)
    restored = client.post(
        "/daily-reports/bulk/restore",
        content=urlencode(
            [("action_token", token), *(("report_ids", str(report_id)) for report_id in report_ids)]
        ),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )

    assert restored.status_code == 303
    assert restored.headers["location"].startswith("/daily-reports/trash?")
    assert all(
        db_session.get(DailyReportRecord, report_id).deleted_at is None
        for report_id in report_ids
    )


def test_trash_page_purge_requires_confirmation_and_enqueues_only(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    DailyReportRepository(db_session).move_to_trash(report_id)
    client, token = safe_client_with_token(db_session, monkeypatch)

    trash = client.get("/daily-reports/trash")
    unconfirmed = client.post(
        f"/daily-reports/{report_id}/purge",
        data={"action_token": token},
        follow_redirects=False,
    )
    fresh_page = client.get("/operations")
    token = fresh_page.text.split('name="action_token" value="', 1)[1].split('"', 1)[0]
    confirmed = client.post(
        f"/daily-reports/{report_id}/purge",
        data={"action_token": token, "confirm_purge": "true"},
        follow_redirects=False,
    )

    operation = db_session.scalar(
        select(OperationRunRecord)
        .where(OperationRunRecord.operation_type == "daily_report_purge")
        .order_by(OperationRunRecord.id.desc())
    )
    assert trash.status_code == 200
    assert f'action="/daily-reports/{report_id}/purge"' in trash.text
    assert 'name="confirm_purge" value="true"' in trash.text
    assert "永久删除" in trash.text
    assert unconfirmed.status_code == 422
    assert confirmed.status_code == 303
    assert confirmed.headers["location"] == "/daily-reports/trash"
    assert operation is not None
    assert operation.status == "queued"
    assert operation.requested_scope == {"schema_version": 1, "report_ids": [report_id]}
    assert db_session.get(DailyReportRecord, report_id) is not None


def test_purge_post_requires_safe_action_token(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = seed_daily_report(db_session)
    DailyReportRepository(db_session).move_to_trash(report.id)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    client = TestClient(
        create_app(),
        base_url="http://127.0.0.1",
        headers={"Origin": "http://127.0.0.1"},
    )

    response = client.post(
        f"/daily-reports/{report.id}/purge",
        data={"confirm_purge": "true"},
    )

    assert response.status_code == 400
    assert db_session.scalar(
        select(OperationRunRecord).where(
            OperationRunRecord.operation_type == "daily_report_purge"
        )
    ) is None


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
