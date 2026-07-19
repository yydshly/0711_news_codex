from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.schema import (
    REPORT_TIMEZONE,
    DailyReportDraft,
    DailyReportOverviewItemDraft,
)
from newsradar.db.models import (
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    OperationRunRecord,
)
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS
from newsradar.web.app import create_app


def _add_event(
    session,
    event_id=41,
    status="confirmed",
    title="确认事件",
    visibility="current",
    display_tier=None,
    rank_score=80,
):
    occurred_at = datetime.now(UTC)
    session.add(
        EventRecord(
            id=event_id,
            canonical_key=f"e-{event_id}",
            visibility=visibility,
            display_tier=display_tier or ("hotspot" if status == "confirmed" else "signal"),
            rank_score=rank_score,
            status=status,
            occurred_at=occurred_at,
            current_version_number=1,
        )
    )
    session.add(
        EventVersionRecord(
            event_id=event_id,
            version_number=1,
            zh_title=title,
            zh_summary="已核验摘要",
            payload={
                "status": status,
                "category": "uncategorized",
                "occurred_at": occurred_at.isoformat(),
                "publication": {
                    "tier": display_tier
                    or ("hotspot" if status == "confirmed" else "signal")
                },
                "enrichment": {
                    "why_it_matters": "影响行业采用。",
                    "limitations": [],
                    "origin": "model",
                },
                "evidence": [
                    {
                        "raw_item_id": event_id,
                        "role": "official",
                        "root_evidence_key": f"official:{event_id}",
                        "independent": True,
                    }
                ],
            },
        )
    )
    session.add(
        EventScoreRecord(
            event_id=event_id,
            version_number=1,
            heat=88,
            breakdown={
                "ai_relevance": 90,
                "source_coverage": 70,
                "source_authority": 90,
                "recency": 100,
                "engagement_velocity": 50,
                "novelty": 70,
                "importance": 83,
                "credibility": 90,
                "heat": 88,
                "rule_version": "score-v2",
                "reasons": ["official_evidence"],
            },
        )
    )
    session.commit()


def _add_pipeline_snapshot(session, refs: list[tuple[int, int]]):
    now = datetime.now(UTC)
    operation = OperationRunRecord(
        operation_type="event_pipeline",
        trigger="manual",
        status="succeeded",
        requested_scope={
            "window_hours": 72,
            "window_end": now.isoformat(),
            "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
        },
        result_summary={
            "event_version_snapshots": [
                {"event_id": event_id, "version_number": version_number}
                for event_id, version_number in refs
            ]
        },
        created_at=now,
        finished_at=now,
    )
    session.add(operation)
    session.commit()
    return operation.id


def _add_cumulative_report(session, operation_id: int, event_ids: tuple[int, ...]) -> int:
    operation = session.get(OperationRunRecord, operation_id)
    window_end = datetime.fromisoformat(operation.requested_scope["window_end"])
    report = DailyReportRepository(session).create_draft(
        DailyReportDraft(
            report_date=window_end.astimezone(ZoneInfo(REPORT_TIMEZONE)).date(),
            window_hours=72,
            window_start=window_end - timedelta(hours=72),
            window_end=window_end,
            source_operation_id=operation_id,
            generation_summary={"overview_count": len(event_ids)},
            items=(),
            overview_items=tuple(
                DailyReportOverviewItemDraft(
                    event_id=event_id,
                    event_version_number=1,
                    position=position,
                    snapshot={
                        "zh_title": f"累计事件 {event_id}",
                        "zh_summary": "累计日报固定事件。",
                        "status": "confirmed",
                        "display_tier": "hotspot",
                        "rank_score": 80,
                    },
                )
                for position, event_id in enumerate(event_ids, start=1)
            ),
        )
    )
    return report.id


def test_event_pages_distinguish_latest_operation_from_daily_cumulative(
    db_session, monkeypatch
):
    event_ids = tuple(range(101, 111))
    for event_id in event_ids:
        _add_event(db_session, event_id, title=f"事件 {event_id}")
    operation_id = _add_pipeline_snapshot(
        db_session, [(event_id, 1) for event_id in event_ids[:6]]
    )
    operation = db_session.get(OperationRunRecord, operation_id)
    operation.requested_scope = {
        **operation.requested_scope,
        "window_end": (operation.finished_at - timedelta(milliseconds=1)).isoformat(),
    }
    db_session.commit()
    report_id = _add_cumulative_report(db_session, operation_id, event_ids)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        home = client.get("/")
        events = client.get("/events")

    for response in (home, events):
        assert response.status_code == 200
        assert "最新运行事件 6 条 · 今日累计日报 10 条 · 沿用历史 4 条" in response.text
        assert f'href="/daily-reports/{report_id}"' in response.text
        assert "事件 101" in response.text
        assert "事件 106" in response.text
        assert "事件 107" not in response.text


def test_home_separates_confirmed_events_from_early_social_signals(db_session, monkeypatch):
    _add_event(db_session)
    _add_event(db_session, 42, "emerging", "社交线索")
    operation_id = _add_pipeline_snapshot(db_session, [(41, 1), (42, 1)])
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    with TestClient(create_app()) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert f"Operation #{operation_id}" in response.text
    assert "确认事件" in response.text
    assert "最近 24 小时已确认热点" in response.text
    assert "早期信号" in response.text
    assert "社交线索" in response.text


def test_emerging_page_labels_unconfirmed_social_signal(db_session, monkeypatch):
    _add_event(db_session, 42, "emerging", "社交线索")
    operation_id = _add_pipeline_snapshot(db_session, [(42, 1)])
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    with TestClient(create_app()) as client:
        response = client.get("/emerging")
    assert response.status_code == 200
    assert f"Operation #{operation_id}" in response.text
    assert "仅线索" in response.text
    assert "社交线索" in response.text


def test_events_can_filter_hotspots_and_signals(db_session, monkeypatch):
    _add_event(db_session, 45, "confirmed", "热点事件", display_tier="hotspot")
    _add_event(db_session, 46, "emerging", "信号事件", display_tier="signal")
    _add_pipeline_snapshot(db_session, [(45, 1), (46, 1)])
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        response = client.get("/events?tier=signal")

    assert response.status_code == 200
    assert "信号事件" in response.text
    assert "热点事件" not in response.text


def test_events_defaults_to_latest_operation_and_keeps_catalog_entry(db_session, monkeypatch):
    _add_event(db_session, 43, "confirmed", "当前事件")
    _add_event(db_session, 44, "confirmed", "历史事件", visibility="legacy")
    operation_id = _add_pipeline_snapshot(db_session, [(43, 1)])
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        current = client.get("/events")
        catalog = client.get("/events?scope=current_catalog")
        legacy = client.get("/events?visibility=legacy")

    assert "当前事件" in current.text
    assert "历史事件" not in current.text
    assert f"Operation #{operation_id}" in current.text
    assert 'name="status"' in current.text
    assert 'name="category"' in current.text
    assert 'name="hours"' in current.text
    assert "全局 current 目录" in catalog.text
    assert "历史事件" in legacy.text
    assert '<h2><a href="/events/43">当前事件</a></h2>' not in legacy.text
    assert "旧版算法结果，不参与当前首页" in legacy.text


def test_event_detail_requires_complete_operation_version_pair(db_session, monkeypatch):
    _add_event(db_session, 47, "confirmed", "固定详情事件")
    operation_id = _add_pipeline_snapshot(db_session, [(47, 1)])
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        fixed = client.get(f"/events/47?operation={operation_id}&version=1")
        partial = client.get(f"/events/47?operation={operation_id}")
        missing = client.get(f"/events/47?operation={operation_id}&version=2")

    assert fixed.status_code == 200
    assert f"Operation #{operation_id}" in fixed.text
    assert partial.status_code == 400
    assert missing.status_code == 404


def test_recluster_post_only_enqueues_operation(db_session, monkeypatch):
    _add_event(db_session)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    with TestClient(create_app()) as client:
        token = (
            client.get("/events/41").text.split('name="action_token" value="')[1].split('"', 1)[0]
        )
        response = client.post(
            "/events/41/recluster",
            data={"action_token": token},
            headers={"Origin": "http://127.0.0.1", "Host": "127.0.0.1"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    operation = db_session.query(OperationRunRecord).one()
    assert operation.operation_type == "event_recluster"
    assert operation.trigger == "web"
    assert operation.requested_scope["actor"] == "web"


def test_current_event_detail_links_to_candidate_search_without_target_input(
    db_session, monkeypatch
):
    _add_event(db_session)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        response = client.get("/events/41")

    assert response.status_code == 200
    assert "/event-merge-candidates?status=pending&amp;event_id=41" in response.text
    assert 'name="target_event_id"' not in response.text


def test_bare_event_id_merge_is_rejected_without_enqueuing(db_session, monkeypatch):
    _add_event(db_session)
    _add_event(db_session, 42)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    with TestClient(create_app()) as client:
        token = (
            client.get("/events/41").text.split('name="action_token" value="')[1].split('"', 1)[0]
        )
        response = client.post(
            "/events/merge",
            data={
                "event_id": "41",
                "target_event_id": "42",
                "action_token": token,
            },
            headers={"Origin": "http://127.0.0.1", "Host": "127.0.0.1"},
        )

    assert response.status_code in {409, 422}
    assert "候选" in response.text
    assert db_session.query(OperationRunRecord).count() == 0


def test_event_detail_does_not_render_unsafe_evidence_href(db_session, monkeypatch):
    from newsradar.db.models import EventItemRecord, RawItemRecord

    _add_event(db_session)
    raw = RawItemRecord(
        source_id="github-openai-python",
        external_id="unsafe-link",
        canonical_url="javascript:alert(1)",
        payload={},
        title="不安全链接",
    )
    db_session.add(raw)
    db_session.flush()
    db_session.add(EventItemRecord(event_id=41, raw_item_id=raw.id, added_version_number=1))
    db_session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        response = client.get("/events/41")

    assert response.status_code == 200
    assert 'href="javascript:' not in response.text
