from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from newsradar.daily_reports import chinese_enrichment
from newsradar.daily_reports.autopilot import (
    DailyAutopilotStage,
    serialize_catalog_plan,
    serialize_wave_plan,
)
from newsradar.daily_reports.autopilot_repository import DailyAutopilotRepository
from newsradar.db.models import DailyReportRecord, FetchRunRecord, OperationRunRecord
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.sources.catalog_refresh import (
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
)
from newsradar.waves.planning import WaveMemberSnapshot, wave_plan_from_members
from newsradar.web.app import create_app


def _plan() -> CatalogRefreshPlan:
    return CatalogRefreshPlan.from_members(
        [
            CatalogRefreshMemberSnapshot(
                source_id="source-a",
                provider_id="provider-a",
                definition_hash="source-hash",
                availability="ready",
                coverage_mode="direct",
                access_kind="rss",
                lane=CatalogRefreshLane.CONTENT,
            )
        ]
    )


def _wave_plan(window_hours: int):
    return wave_plan_from_members(
        profile_id="high-value",
        members=(
            WaveMemberSnapshot(
                "source-a",
                "provider-a",
                "source-hash",
                ("evidence",),
                "ready",
                "rss",
                True,
                None,
            ),
        ),
        window_hours=window_hours,
        trend_days=7,
    )


def _client_with_token(
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


def test_automatic_task_page_shows_linked_report_enrichment_metrics(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation = OperationRunRecord(
        operation_type=OperationType.HIGH_VALUE_NEWS_WAVE.value,
        trigger="test",
        status=OperationStatus.SUCCEEDED.value,
        requested_scope={},
        result_summary={},
    )
    db_session.add(operation)
    db_session.flush()
    report = DailyReportRecord(
        report_date=date(2026, 7, 18),
        timezone="Asia/Shanghai",
        window_hours=24,
        window_start=datetime(2026, 7, 17, tzinfo=UTC),
        window_end=datetime(2026, 7, 18, tzinfo=UTC),
        source_operation_id=operation.id,
        status="draft",
        revision=1,
        generation_summary={
            "daily_chinese_enrichment": {
                "candidate_total": 2,
                "processed": 2,
                "model_success": 1,
                "rule_fallback": 1,
                "budget_fallback": 0,
                "error_counts": {"http_429": 1},
                "items": {
                    "1:1": {"origin": "model", "error_code": None},
                    "2:1": {
                        "origin": "rule_fallback",
                        "error_code": "http_429",
                    },
                },
            },
        },
        generated_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    db_session.add(report)
    db_session.flush()
    run = DailyAutopilotRepository(db_session).create_run(
        window_hours=24,
        trigger="test",
        requested_scope={"wave_plan": serialize_wave_plan(_wave_plan(24))},
    )
    DailyAutopilotRepository(db_session).transition(
        run.id,
        stage=DailyAutopilotStage.WRITE_REVIEWS,
        event_operation_id=operation.id,
        daily_report_id=report.id,
    )
    db_session.commit()
    run_id = run.id

    client, _token = _client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-autopilot/{run_id}")

    assert response.status_code == 200
    assert "中文增强候选 2" in response.text
    assert "MiniMax 完整成功 1" in response.text
    assert "整条规则回退 1" in response.text


def test_automatic_task_page_hides_inconsistent_enrichment_audit(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation = OperationRunRecord(
        operation_type=OperationType.HIGH_VALUE_NEWS_WAVE.value,
        trigger="test",
        status=OperationStatus.SUCCEEDED.value,
        requested_scope={},
        result_summary={},
    )
    db_session.add(operation)
    db_session.flush()
    report = DailyReportRecord(
        report_date=date(2026, 7, 18),
        timezone="Asia/Shanghai",
        window_hours=24,
        window_start=datetime(2026, 7, 17, tzinfo=UTC),
        window_end=datetime(2026, 7, 18, tzinfo=UTC),
        source_operation_id=operation.id,
        status="draft",
        revision=1,
        generation_summary={
            "daily_chinese_enrichment": {
                "candidate_total": 1,
                "processed": 1,
                "model_success": 1,
                "rule_fallback": 0,
                "budget_fallback": 0,
                "model_budget": 1001,
                "error_counts": {},
                "items": {"1:1": {"origin": "model", "error_code": None}},
            }
        },
        generated_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    db_session.add(report)
    db_session.flush()
    run = DailyAutopilotRepository(db_session).create_run(
        window_hours=24,
        trigger="test",
        requested_scope={"wave_plan": serialize_wave_plan(_wave_plan(24))},
    )
    DailyAutopilotRepository(db_session).transition(
        run.id,
        stage=DailyAutopilotStage.WRITE_REVIEWS,
        event_operation_id=operation.id,
        daily_report_id=report.id,
    )
    run_id = run.id
    db_session.commit()

    client, _token = _client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-autopilot/{run_id}")

    assert response.status_code == 200
    assert "中文增强候选" not in response.text


def test_automatic_task_page_uses_complete_safe_chinese_error_labels(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation = OperationRunRecord(
        operation_type=OperationType.HIGH_VALUE_NEWS_WAVE.value,
        trigger="test",
        status=OperationStatus.SUCCEEDED.value,
        requested_scope={},
        result_summary={},
    )
    db_session.add(operation)
    db_session.flush()
    daily_chinese_error_labels = chinese_enrichment.DAILY_CHINESE_ERROR_LABELS
    items = {
        f"{index}:1": {
            "origin": "budget_limit" if code == "budget_limit" else "rule_fallback",
            "error_code": code,
        }
        for index, code in enumerate(daily_chinese_error_labels, start=1)
    }
    report = DailyReportRecord(
        report_date=date(2026, 7, 18),
        timezone="Asia/Shanghai",
        window_hours=24,
        window_start=datetime(2026, 7, 17, tzinfo=UTC),
        window_end=datetime(2026, 7, 18, tzinfo=UTC),
        source_operation_id=operation.id,
        status="draft",
        revision=1,
        generation_summary={
            "daily_chinese_enrichment": {
                "candidate_total": len(items),
                "processed": len(items),
                "model_success": 0,
                "rule_fallback": len(items) - 1,
                "budget_fallback": 1,
                "error_counts": {code: 1 for code in daily_chinese_error_labels},
                "items": items,
            }
        },
        generated_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    db_session.add(report)
    db_session.flush()
    run = DailyAutopilotRepository(db_session).create_run(
        window_hours=24,
        trigger="test",
        requested_scope={"wave_plan": serialize_wave_plan(_wave_plan(24))},
    )
    DailyAutopilotRepository(db_session).transition(
        run.id,
        stage=DailyAutopilotStage.WRITE_REVIEWS,
        event_operation_id=operation.id,
        daily_report_id=report.id,
    )
    run_id = run.id
    db_session.commit()

    client, _token = _client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-autopilot/{run_id}")

    assert response.status_code == 200
    for code, label in daily_chinese_error_labels.items():
        assert label in response.text
        assert code not in response.text


def test_autopilot_post_queues_then_redirects_to_task_page(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "newsradar.web.app.build_local_wave_plan",
        lambda _session, *, window_hours: _wave_plan(window_hours),
    )
    client, token = _client_with_token(db_session, monkeypatch)

    response = client.post(
        "/daily-reports/autopilot",
        data={"action_token": token, "window_hours": "72"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/daily-autopilot/1"
    run = DailyAutopilotRepository(db_session).get(1)
    assert run.window_hours == 72
    assert run.stage == DailyAutopilotStage.ENQUEUE_CONTENT_WAVE.value
    assert run.requested_scope["wave_plan"]["window_hours"] == 72
    assert "catalog_plan" not in run.requested_scope


def test_task_page_shows_child_links_and_chinese_partial_reason(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = OperationRunRecord(
        operation_type=OperationType.SOURCE_CATALOG_REFRESH.value,
        trigger="test",
        status=OperationStatus.PARTIAL.value,
        requested_scope={},
        result_summary={},
    )
    db_session.add(source)
    db_session.flush()
    run = DailyAutopilotRepository(db_session).create_run(
        window_hours=24,
        trigger="web",
        requested_scope={"catalog_plan": serialize_catalog_plan(_plan())},
    )
    DailyAutopilotRepository(db_session).transition(
        run.id,
        stage=DailyAutopilotStage.WAIT_SOURCE_REFRESH,
        source_operation_id=source.id,
    )
    run_id = run.id
    db_session.commit()
    client, _token = _client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-autopilot/{run_id}")

    assert response.status_code == 200
    assert "来源刷新" in response.text
    assert f'href="/operations/{source.id}"' in response.text
    assert "部分来源未成功" in response.text


def test_content_wave_task_page_shows_real_collection_stage_and_counts(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = OperationRunRecord(
        operation_type=OperationType.HIGH_VALUE_NEWS_WAVE.value,
        trigger="test",
        status=OperationStatus.PARTIAL.value,
        requested_scope={},
        result_summary={
            "member_total": 41,
            "fetch_succeeded": 34,
            "blocked": 7,
            "event_manifest_count": 36,
            "confirmed_event_count": 4,
        },
    )
    db_session.add(child)
    db_session.flush()
    db_session.add_all(
        (
            FetchRunRecord(
                source_id="source-a",
                operation_run_id=child.id,
                outcome="succeeded",
                items_received=10,
                items_inserted=3,
                items_updated=0,
                items_unchanged=7,
            ),
            FetchRunRecord(
                source_id="source-b",
                operation_run_id=child.id,
                outcome="no_change",
                items_received=5,
                items_inserted=0,
                items_updated=0,
                items_unchanged=5,
            ),
        )
    )
    decision_audio = OperationRunRecord(
        operation_type=OperationType.DAILY_REPORT_AUDIO.value,
        trigger="test",
        status=OperationStatus.SUCCEEDED.value,
        requested_scope={"daily_report_id": 1, "rendition": "decision"},
        result_summary={},
    )
    overview_audio = OperationRunRecord(
        operation_type=OperationType.DAILY_REPORT_AUDIO.value,
        trigger="test",
        status=OperationStatus.QUEUED.value,
        requested_scope={"daily_report_id": 1, "rendition": "overview"},
        result_summary={},
    )
    db_session.add_all((decision_audio, overview_audio))
    db_session.flush()
    run = DailyAutopilotRepository(db_session).create_run(
        window_hours=24,
        trigger="web",
        requested_scope={"wave_plan": serialize_wave_plan(_wave_plan(24))},
    )
    DailyAutopilotRepository(db_session).transition(
        run.id,
        stage=DailyAutopilotStage.WAIT_CONTENT_WAVE,
        event_operation_id=child.id,
        decision_audio_operation_id=decision_audio.id,
        overview_audio_operation_id=overview_audio.id,
    )
    run_id = run.id
    db_session.commit()
    client, _token = _client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-autopilot/{run_id}")

    assert response.status_code == 200
    assert "等待内容抓取与事件处理" in response.text
    assert "内容抓取与事件处理" in response.text
    assert "目标：41" in response.text
    assert "成功抓取：34" in response.text
    assert "阻塞：7" in response.text
    assert "事件：36" in response.text
    assert "抓取批次" in response.text and ">2<" in response.text
    assert "接收条目" in response.text and ">15<" in response.text
    assert "新增条目" in response.text and ">3<" in response.text
    assert "未变化" in response.text and ">12<" in response.text
    assert "确认事件" in response.text and ">4<" in response.text
    assert "决策版语音" in response.text and "succeeded" in response.text
    assert "情报全览语音" in response.text and "queued" in response.text
    assert "部分目标受阻" in response.text


def test_content_wave_task_page_shows_daily_report_coverage_funnel(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = OperationRunRecord(
        operation_type=OperationType.HIGH_VALUE_NEWS_WAVE.value,
        trigger="test",
        status=OperationStatus.PARTIAL.value,
        requested_scope={},
        result_summary={
            "member_total": 41,
            "fetch_succeeded": 35,
            "blocked": 6,
            "event_manifest_count": 25,
        },
    )
    db_session.add(child)
    db_session.flush()
    report = DailyReportRecord(
        report_date=date(2026, 7, 18),
        timezone="Asia/Shanghai",
        window_hours=24,
        window_start=datetime(2026, 7, 17, tzinfo=UTC),
        window_end=datetime(2026, 7, 18, tzinfo=UTC),
        source_operation_id=child.id,
        status="draft",
        revision=1,
        generation_summary={
            "confirmed_count": 4,
            "emerging_count": 11,
            "overview_count": 22,
        },
        generated_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    db_session.add(report)
    db_session.flush()
    run = DailyAutopilotRepository(db_session).create_run(
        window_hours=24,
        trigger="web",
        requested_scope={"wave_plan": serialize_wave_plan(_wave_plan(24))},
    )
    DailyAutopilotRepository(db_session).transition(
        run.id,
        stage=DailyAutopilotStage.WRITE_REVIEWS,
        event_operation_id=child.id,
        daily_report_id=report.id,
    )
    run_id = run.id
    db_session.commit()
    client, _token = _client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-autopilot/{run_id}")

    assert response.status_code == 200
    assert "日报覆盖漏斗" in response.text
    assert "计划目标" in response.text and ">41<" in response.text
    assert "成功抓取" in response.text and ">35<" in response.text
    assert "受阻目标" in response.text and ">6<" in response.text
    assert "形成事件" in response.text and ">25<" in response.text
    assert "进入决策简报" in response.text and ">15<" in response.text
    assert "进入情报全览" in response.text and ">22<" in response.text
    assert "未进入全览" in response.text and ">3<" in response.text


def test_completed_task_does_not_claim_that_partial_collection_is_still_running(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = OperationRunRecord(
        operation_type=OperationType.HIGH_VALUE_NEWS_WAVE.value,
        trigger="test",
        status=OperationStatus.PARTIAL.value,
        requested_scope={},
        result_summary={"member_total": 41, "fetch_succeeded": 34, "blocked": 7},
    )
    db_session.add(child)
    db_session.flush()
    run = DailyAutopilotRepository(db_session).create_run(
        window_hours=24,
        trigger="web",
        requested_scope={"wave_plan": serialize_wave_plan(_wave_plan(24))},
    )
    DailyAutopilotRepository(db_session).transition(
        run.id,
        stage=DailyAutopilotStage.COMPLETED,
        status="succeeded",
        event_operation_id=child.id,
    )
    run_id = run.id
    db_session.commit()
    client, _token = _client_with_token(db_session, monkeypatch)

    response = client.get(f"/daily-autopilot/{run_id}")

    assert response.status_code == 200
    assert "自动日报已完成" in response.text
    assert "会继续生成中文日报" not in response.text
