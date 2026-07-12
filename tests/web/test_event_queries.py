from datetime import UTC, datetime, timedelta

from newsradar.db.models import EventRecord, EventScoreRecord, EventVersionRecord


def _event(session, *, event_id: int, status: str, title: str, occurred_at: datetime):
    record = EventRecord(
        id=event_id,
        canonical_key=f"event-{event_id}",
        status=status,
        occurred_at=occurred_at,
        current_version_number=1,
    )
    session.add(record)
    session.add(
        EventVersionRecord(
            event_id=event_id, version_number=1, zh_title=title, zh_summary="摘要", payload={}
        )
    )
    session.add(
        EventScoreRecord(
            event_id=event_id,
            version_number=1,
            heat=80,
            breakdown={"importance": 80, "reasons": ["多源印证"]},
        )
    )
    session.commit()
    return record


def test_home_only_returns_recent_confirmed_complete_events(db_session):
    from newsradar.web.event_queries import EventQueryService

    now = datetime.now(UTC)
    confirmed = _event(
        db_session, event_id=1, status="confirmed", title="已确认事件", occurred_at=now
    )
    _event(db_session, event_id=2, status="emerging", title="社交线索", occurred_at=now)
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


def test_detail_exposes_score_and_degradation_state(db_session):
    from newsradar.web.event_queries import EventQueryService

    now = datetime.now(UTC)
    record = _event(db_session, event_id=4, status="confirmed", title="详情事件", occurred_at=now)
    detail = EventQueryService(db_session).get_event(record.id)

    assert detail is not None
    assert detail.score_reasons == ("多源印证",)
    assert detail.minimax_degraded is False


def test_detail_only_exposes_safe_evidence_links_and_evidence_audit_fields(db_session):
    from newsradar.db.models import EventItemRecord, RawItemRecord
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
        original_url="javascript:alert(1)",
        payload={},
        title="不安全链接",
    )
    db_session.add(raw)
    db_session.flush()
    db_session.add(EventItemRecord(event_id=record.id, raw_item_id=raw.id, added_version_number=1))
    score = db_session.query(EventScoreRecord).filter_by(event_id=record.id).one()
    version = db_session.query(EventVersionRecord).filter_by(event_id=record.id).one()
    version.payload = {"enrichment": {"origin": "rule_fallback"}}
    score.breakdown = {
        "reasons": ["多源印证"],
        "evidence": [
            {"raw_item_id": raw.id, "root_evidence_key": "root:official", "independent": True}
        ],
    }
    db_session.commit()

    detail = EventQueryService(db_session).get_event(record.id)

    assert detail is not None
    assert detail.evidence[0].original_url is None
    assert detail.evidence[0].root_evidence_key == "root:official"
    assert detail.evidence[0].independent is True
    assert detail.minimax_degraded is True
