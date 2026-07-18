from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.orm.attributes import flag_modified

from newsradar.db.models import (
    EventVersionRecord,
    HighValueWaveMemberRecord,
    OperationRunRecord,
)
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS
from newsradar.web.app import create_app
from tests.web.test_event_routes import _add_event


def _add_wave_snapshot(session, refs: list[tuple[int, int]]) -> int:
    now = datetime.now(UTC)
    operation = OperationRunRecord(
        operation_type="high_value_news_wave",
        trigger="web",
        status="partial",
        requested_scope={
            "window_hours": 24,
            "window_end": now.isoformat(),
            "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
        },
        result_summary={
            "member_total": 2,
            "completed_members": 2,
            "evidence_capable_members": 1,
            "direct_evidence_fetch_succeeded": 1,
            "events_with_official_root": 1,
            "events_with_one_professional_root": 0,
            "events_with_two_professional_roots": 0,
            "confirmed_event_count": 1,
            "ambiguous_pairs_checked": 2,
            "model_pair_fallback_count": 1,
            "api_key": "page-secret",
            "Authorization": "Bearer page-secret",
            "Cookie": "session=page-secret",
            "event_manifest_complete": True,
            "event_manifest_count": len(refs),
            "event_version_snapshots": [
                {"event_id": event_id, "version_number": version_number}
                for event_id, version_number in refs
            ],
        },
        created_at=now,
        finished_at=now,
    )
    session.add(operation)
    session.flush()
    session.add_all(
        [
            HighValueWaveMemberRecord(
                operation_run_id=operation.id,
                source_id="github-openai-python",
                provider_id="github",
                definition_hash="a" * 64,
                roles_snapshot=["discovery"],
                availability_snapshot="ready",
                access_kind_snapshot="rss",
                fetchable=True,
                state="succeeded",
            ),
            HighValueWaveMemberRecord(
                operation_run_id=operation.id,
                source_id="search-ai",
                provider_id="github",
                definition_hash="b" * 64,
                roles_snapshot=["context"],
                availability_snapshot="ready",
                access_kind_snapshot="rss",
                fetchable=True,
                state="succeeded",
            ),
        ]
    )
    session.commit()
    return operation.id


def test_home_separates_confirmed_early_and_seven_day_trends(db_session, monkeypatch):
    _add_event(db_session, 201, "confirmed", "已确认模型发布")
    _add_event(db_session, 202, "emerging", "社区早期讨论")
    for event_id, direction in ((201, "rising"), (202, "sustained")):
        version = db_session.query(EventVersionRecord).filter_by(event_id=event_id).one()
        version.payload["trend"] = {"direction": direction, "delta": 12}
        version.payload["heat_breakdown"] = {"source_coverage": 70, "recency": 90}
        version.payload["evidence_summary"] = {
            "official_roots": 1 if event_id == 201 else 0,
            "professional_roots": 0,
            "community_signals": 0 if event_id == 201 else 1,
            "aggregator_pointers": 0,
            "missing_confirmation": [] if event_id == 201 else ["professional_media_needed"],
        }
        flag_modified(version, "payload")
    db_session.commit()
    _add_wave_snapshot(db_session, [(201, 1), (202, 1)])
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    for expected in (
        "最近 24 小时已确认热点",
        "早期信号",
        "7 天趋势",
        "为什么热门",
        "已确认模型发布",
        "社区早期讨论",
    ):
        assert expected in response.text


def test_event_detail_explains_roles_missing_confirmation_and_heat(db_session, monkeypatch):
    _add_event(db_session, 203, "emerging", "待确认的 AI 信号")
    version = db_session.query(EventVersionRecord).filter_by(event_id=203).one()
    version.payload.update(
        {
            "trend": {"direction": "rising", "delta": 15},
            "heat_breakdown": {
                "source_coverage": 60,
                "source_authority": 40,
                "recency": 90,
                "engagement_velocity": 80,
            },
            "evidence_summary": {
                "official_roots": 0,
                "professional_roots": 0,
                "community_signals": 1,
                "aggregator_pointers": 1,
                "missing_confirmation": ["professional_media_needed"],
            },
        }
    )
    flag_modified(version, "payload")
    db_session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        response = client.get("/events/203")

    assert response.status_code == 200
    for expected in ("热度拆解", "趋势", "来源角色", "缺失确认条件", "上升"):
        assert expected in response.text


def test_wave_operation_page_shows_allow_listed_coverage_without_secrets(
    db_session, monkeypatch
):
    operation_id = _add_wave_snapshot(db_session, [])
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        response = client.get(f"/operations/{operation_id}")

    assert response.status_code == 200
    for expected in ("证据型成员", "直接证据抓取成功", "已确认事件", "1"):
        assert expected in response.text
    for forbidden in ("api_key", "Authorization", "Cookie", "page-secret"):
        assert forbidden not in response.text


def test_event_update_only_enqueues_and_requires_safe_write(db_session, monkeypatch):
    calls: list[object] = []
    plan_windows: list[int] = []

    class Commands:
        def __init__(self, session):
            self.session = session

        def enqueue_high_value_wave(self, *, plan, trigger):
            calls.append((plan, trigger))
            return 77

    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    monkeypatch.setattr("newsradar.web.app.OperationCommandService", Commands)
    monkeypatch.setattr(
        "newsradar.web.app.build_local_wave_plan",
        lambda _session, *, profile_path, window_hours: (
            plan_windows.append(window_hours) or object()
        ),
    )
    monkeypatch.setattr(
        "newsradar.web.app.load_wave_profile", lambda _path: SimpleNamespace(window_hours=72)
    )

    with TestClient(create_app()) as client:
        page = client.get("/")
        token = page.text.split('name="action_token" value="', 1)[1].split('"', 1)[0]
        response = client.post(
            "/events/update",
            data={"action_token": token},
            headers={"Origin": "http://127.0.0.1", "Host": "127.0.0.1"},
            follow_redirects=False,
        )
        reused = client.post(
            "/events/update",
            data={"action_token": token},
            headers={"Origin": "http://127.0.0.1", "Host": "127.0.0.1"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/operations/77"
    assert calls and calls[0][1] == "web"
    assert plan_windows == [72]
    assert reused.status_code == 400
