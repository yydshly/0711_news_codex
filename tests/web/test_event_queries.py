from datetime import UTC, datetime, timedelta

from newsradar.db.models import (
    EventItemRecord,
    EventModelRunRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    ModelUsageRecord,
    RawItemRecord,
)

COMPLETE_BREAKDOWN = {
    "ai_relevance": 80,
    "source_coverage": 70,
    "source_authority": 90,
    "recency": 100,
    "engagement_velocity": 40,
    "novelty": 60,
    "importance": 78,
    "credibility": 90,
    "heat": 83,
    "rule_version": "score-v2",
    "reasons": ["official_evidence", "engagement_unavailable"],
}


def _event(
    session,
    *,
    event_id: int,
    status: str,
    title: str,
    occurred_at: datetime,
    visibility: str = "current",
    breakdown: dict | None = None,
):
    record = EventRecord(
        id=event_id,
        canonical_key=f"event-{event_id}",
        visibility=visibility,
        status=status,
        occurred_at=occurred_at,
        current_version_number=1,
    )
    session.add(record)
    raw = RawItemRecord(
        source_id="github-openai-python",
        external_id=f"event-evidence-{event_id}",
        canonical_url=f"https://example.com/evidence/{event_id}",
        original_url=f"https://example.com/evidence/{event_id}",
        payload={},
        title=f"证据 {event_id}",
        published_at=occurred_at,
    )
    session.add(raw)
    session.flush()
    session.add(
        EventVersionRecord(
            event_id=event_id,
            version_number=1,
            zh_title=title,
            zh_summary="摘要",
            payload={
                "enrichment": {
                    "why_it_matters": "影响开发者采用路径。",
                    "limitations": ["not_peer_reviewed"],
                    "origin": "model",
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
            },
        )
    )
    session.add(EventItemRecord(event_id=event_id, raw_item_id=raw.id, added_version_number=1))
    session.add(
        EventScoreRecord(
            event_id=event_id,
            version_number=1,
            heat=83,
            breakdown=breakdown or COMPLETE_BREAKDOWN,
        )
    )
    session.commit()
    return record


def test_event_query_defaults_to_current_and_can_show_legacy(db_session):
    from newsradar.web.event_queries import EventQueryService

    now = datetime.now(UTC)
    current = _event(
        db_session,
        event_id=6,
        status="confirmed",
        title="当前事件",
        occurred_at=now,
    )
    legacy = _event(
        db_session,
        event_id=7,
        status="confirmed",
        title="旧版事件",
        occurred_at=now,
        visibility="legacy",
    )

    service = EventQueryService(db_session)
    assert [row.event_id for row in service.list_events().events] == [current.id]
    assert [row.event_id for row in service.list_events({"visibility": "legacy"}).events] == [
        legacy.id
    ]


def test_home_only_returns_current_recent_confirmed_complete_relevant_events(db_session):
    from newsradar.web.event_queries import EventQueryService

    now = datetime.now(UTC)
    confirmed = _event(
        db_session, event_id=1, status="confirmed", title="已确认事件", occurred_at=now
    )
    _event(db_session, event_id=2, status="emerging", title="社交线索", occurred_at=now)
    _event(
        db_session,
        event_id=8,
        status="confirmed",
        title="旧版事件",
        occurred_at=now,
        visibility="legacy",
    )
    low_relevance = dict(COMPLETE_BREAKDOWN, ai_relevance=59)
    _event(
        db_session,
        event_id=9,
        status="confirmed",
        title="弱相关事件",
        occurred_at=now,
        breakdown=low_relevance,
    )
    _event(
        db_session,
        event_id=3,
        status="confirmed",
        title="过期事件",
        occurred_at=now - timedelta(hours=25),
    )

    home = EventQueryService(db_session).home(now=now)

    assert [event.event_id for event in home.events] == [confirmed.id]
    assert home.events[0].zh_title == "已确认事件"
    assert home.events[0].visibility == "current"
    assert home.events[0].importance == 78
    assert home.events[0].credibility == 90
    assert home.events[0].independent_root_count == 1
    assert home.events[0].enrichment_origin == "model"


def test_detail_exposes_score_and_degradation_state(db_session):
    from newsradar.web.event_queries import EventQueryService

    now = datetime.now(UTC)
    record = _event(db_session, event_id=4, status="confirmed", title="详情事件", occurred_at=now)
    detail = EventQueryService(db_session).get_event(record.id)

    assert detail is not None
    assert [score.key for score in detail.scores] == [
        "ai_relevance",
        "source_coverage",
        "source_authority",
        "recency",
        "engagement_velocity",
        "novelty",
    ]
    assert [score.label for score in detail.scores] == [
        "AI 相关性",
        "来源覆盖",
        "来源权威性",
        "时效",
        "互动热度",
        "新颖性",
    ]
    assert all(score.reason for score in detail.scores)
    assert detail.why_it_matters == "影响开发者采用路径。"
    assert detail.limitations == ("未经同行评审",)
    assert detail.minimax_degraded is False


def test_detail_model_run_summary_only_projects_safe_fields(db_session):
    from newsradar.web.event_queries import EventQueryService

    record = _event(
        db_session,
        event_id=10,
        status="confirmed",
        title="模型审计事件",
        occurred_at=datetime.now(UTC),
    )
    usage = ModelUsageRecord(
        purpose="event_enrichment",
        model="MiniMax-M2.7-highspeed",
        input_tokens=123,
        output_tokens=45,
        latency_ms=321.5,
        outcome="success",
        error="Authorization: Bearer must-not-leak prompt=full-secret",
    )
    db_session.add(usage)
    db_session.flush()
    db_session.add(
        EventModelRunRecord(
            event_id=record.id,
            model_usage_id=usage.id,
            stage="event_enrichment",
            algorithm_version="MiniMax-M2.7-highspeed",
        )
    )
    db_session.commit()

    detail = EventQueryService(db_session).get_event(record.id)

    assert detail is not None
    assert detail.model_runs[0].model == "MiniMax-M2.7-highspeed"
    assert detail.model_runs[0].purpose == "event_enrichment"
    assert detail.model_runs[0].outcome == "success"
    assert detail.model_runs[0].latency_ms == 321.5
    assert "Authorization" not in repr(detail)
    assert "must-not-leak" not in repr(detail)
    assert "input_tokens" not in repr(detail)


def test_detail_treats_malformed_evidence_payload_as_untrusted_data(db_session):
    from newsradar.web.event_queries import EventQueryService

    record = _event(
        db_session,
        event_id=11,
        status="confirmed",
        title="异常证据快照",
        occurred_at=datetime.now(UTC),
    )
    version = db_session.query(EventVersionRecord).filter_by(event_id=record.id).one()
    version.payload = {
        "enrichment": {"origin": "rule_fallback", "why_it_matters": "规则说明"},
        "evidence": None,
    }
    db_session.commit()

    detail = EventQueryService(db_session).get_event(record.id)

    assert detail is not None
    assert detail.evidence[0].role == "unknown"
    assert detail.event.independent_root_count == 0


def test_display_sanitizer_preserves_generic_model_terms_without_secret_assignments():
    from newsradar.web.event_queries import _safe_display_text

    ordinary = "Prompt engineering 会影响 token 预算与模型表现。"

    assert _safe_display_text(ordinary, "") == ordinary
    assert "query-secret" not in _safe_display_text("token=query-secret", "")


def test_detail_only_exposes_safe_evidence_links_and_evidence_audit_fields(db_session):
    from newsradar.web.event_queries import EventQueryService

    record = _event(
        db_session,
        event_id=5,
        status="confirmed",
        title="安全链接事件",
        occurred_at=datetime.now(UTC),
    )
    source_id = "github-openai-python"
    raw = RawItemRecord(
        source_id=source_id,
        external_id="unsafe-url",
        canonical_url="javascript:alert(1)",
        original_url="https://example.com/report?token=must-not-leak#fragment",
        payload={},
        title="不安全链接",
    )
    db_session.add(raw)
    db_session.flush()
    db_session.add(EventItemRecord(event_id=record.id, raw_item_id=raw.id, added_version_number=1))
    version = db_session.query(EventVersionRecord).filter_by(event_id=record.id).one()
    version.payload = {
        "enrichment": {"origin": "rule_fallback"},
        "evidence": [
            {"raw_item_id": raw.id, "root_evidence_key": "root:official", "independent": True}
        ],
    }
    db_session.commit()

    detail = EventQueryService(db_session).get_event(record.id)

    assert detail is not None
    unsafe_evidence = next(row for row in detail.evidence if row.title == "不安全链接")
    assert unsafe_evidence.original_url == "https://example.com/report"
    assert unsafe_evidence.root_evidence_key == "root:official"
    assert unsafe_evidence.independent is True
    assert detail.minimax_degraded is True
