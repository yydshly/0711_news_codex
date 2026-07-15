from datetime import UTC, datetime, timedelta

from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql

from newsradar.db.models import (
    EventItemRecord,
    EventModelRunRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    ModelUsageRecord,
    OperationRunRecord,
    RawItemRecord,
)
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS

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
    display_tier: str = "hotspot",
    rank_score: float = 80,
    category: str | None = None,
):
    record = EventRecord(
        id=event_id,
        canonical_key=f"event-{event_id}",
        visibility=visibility,
        display_tier=display_tier,
        rank_score=rank_score,
        status=status,
        category=category,
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
            created_at=occurred_at,
            payload={
                "status": status,
                "category": category or "uncategorized",
                "occurred_at": occurred_at.isoformat(),
                "publication": {"tier": display_tier},
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
            created_at=occurred_at,
        )
    )
    session.commit()
    return record


def _pipeline_snapshot(session, *, refs: list[tuple[int, int]], now: datetime):
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
    return operation


def test_latest_operation_page_uses_exact_version_not_current_pointer(db_session):
    from newsradar.web.event_queries import EventQueryService

    now = datetime.now(UTC)
    record = _event(
        db_session,
        event_id=41,
        status="confirmed",
        title="Operation 标题",
        occurred_at=now - timedelta(hours=1),
        category="product_model",
    )
    first = db_session.query(EventVersionRecord).filter_by(event_id=record.id).one()
    db_session.add(
        EventVersionRecord(
            event_id=record.id,
            version_number=2,
            zh_title="后来更新的标题",
            zh_summary="后来更新的摘要",
            payload={
                **first.payload,
                "status": "emerging",
                "category": "research",
                "publication": {"tier": "audit_only"},
            },
            created_at=now,
        )
    )
    db_session.add(
        EventScoreRecord(
            event_id=record.id,
            version_number=2,
            heat=10,
            breakdown=COMPLETE_BREAKDOWN,
            created_at=now,
        )
    )
    record.current_version_number = 2
    record.status = "emerging"
    record.category = "research"
    record.display_tier = "audit_only"
    db_session.commit()
    operation = _pipeline_snapshot(db_session, refs=[(record.id, 1)], now=now)

    page = EventQueryService(db_session).latest_operation_page(now=now)

    assert page is not None
    assert page.snapshot.operation_id == operation.id
    assert [row.zh_title for row in page.events] == ["Operation 标题"]
    assert page.events[0].detail_href == f"/events/{record.id}?operation={operation.id}&version=1"


def test_operation_detail_rejects_event_not_in_operation(db_session):
    from newsradar.web.event_queries import EventQueryService

    now = datetime.now(UTC)
    record = _event(
        db_session,
        event_id=42,
        status="confirmed",
        title="不在快照内的事件",
        occurred_at=now - timedelta(hours=1),
    )
    operation = _pipeline_snapshot(db_session, refs=[], now=now)

    assert (
        EventQueryService(db_session).get_operation_event(
            record.id, operation.id, 1, now=now
        )
        is None
    )


def test_home_returns_ranked_hotspots_and_category_sections(db_session):
    from newsradar.web.event_queries import EventQueryService

    now = datetime.now(UTC)
    product = _event(
        db_session,
        event_id=101,
        status="confirmed",
        title="产品热点",
        occurred_at=now,
        category="product_model",
        rank_score=90,
    )
    research = _event(
        db_session,
        event_id=102,
        status="emerging",
        title="研究热点",
        occurred_at=now,
        category="research",
        rank_score=75,
    )
    _event(
        db_session,
        event_id=103,
        status="emerging",
        title="高分信号",
        occurred_at=now,
        category="product_model",
        display_tier="signal",
        rank_score=99,
    )

    view = EventQueryService(db_session).home(now=now)

    assert [row.event_id for row in view.hotspots] == [product.id, research.id]
    assert [row.event_id for row in view.events] == [product.id, research.id]
    assert {section.category for section in view.sections} == {
        "product_model",
        "research",
    }
    assert view.signal_count == 1


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
    _event(
        db_session,
        event_id=2,
        status="emerging",
        title="社交线索",
        occurred_at=now,
        display_tier="signal",
    )
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
        display_tier="audit_only",
    )
    incomplete = _event(
        db_session,
        event_id=12,
        status="confirmed",
        title="评分未完成事件",
        occurred_at=now,
    )
    db_session.delete(
        db_session.scalar(
            select(EventScoreRecord).where(EventScoreRecord.event_id == incomplete.id)
        )
    )
    _event(
        db_session,
        event_id=13,
        status="confirmed",
        title="未来事件",
        occurred_at=now + timedelta(minutes=1),
    )
    db_session.commit()
    _event(
        db_session,
        event_id=3,
        status="confirmed",
        title="过期事件",
        occurred_at=now - timedelta(hours=25),
    )

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        home = EventQueryService(db_session).home(now=now)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert [event.event_id for event in home.events] == [confirmed.id]
    assert home.current_confirmed_count == 3
    assert home.current_emerging_count == 1
    assert home.events[0].zh_title == "已确认事件"
    assert home.events[0].visibility == "current"
    assert home.events[0].importance == 78
    assert home.events[0].credibility == 90
    assert home.events[0].independent_root_count == 1
    assert home.events[0].enrichment_origin == "model"
    eligible_queries = [
        statement
        for statement in statements
        if "join event_versions" in statement and "join event_scores" in statement
    ]
    assert len(eligible_queries) == 1
    assert " limit " not in eligible_queries[0]


def test_postgres_home_relevance_gate_checks_json_type_before_numeric_cast():
    from newsradar.web.event_queries import _safe_ai_relevance_expression

    expression = _safe_ai_relevance_expression("postgresql") >= 60
    compiled = str(
        expression.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).lower()

    assert "case when" in compiled
    assert "json_typeof" in compiled
    assert "cast" in compiled


def test_malformed_score_json_is_excluded_without_breaking_event_pages(db_session):
    from newsradar.web.event_queries import EventQueryService

    now = datetime.now(UTC)
    valid = _event(
        db_session,
        event_id=20,
        status="confirmed",
        title="有效评分事件",
        occurred_at=now,
    )
    malformed_values = ("80", True, None, [80], float("nan"), float("inf"))
    malformed_ids: list[int] = []
    for offset, value in enumerate(malformed_values, start=21):
        record = _event(
            db_session,
            event_id=offset,
            status="confirmed",
            title=f"畸形分数 {offset}",
            occurred_at=now,
        )
        score = db_session.scalar(
            select(EventScoreRecord).where(EventScoreRecord.event_id == record.id)
        )
        score.breakdown = {**COMPLETE_BREAKDOWN, "ai_relevance": value}
        malformed_ids.append(record.id)
    for event_id, value in ((30, None), (31, ["not", "a", "mapping"])):
        record = _event(
            db_session,
            event_id=event_id,
            status="confirmed",
            title=f"畸形快照 {event_id}",
            occurred_at=now,
        )
        score = db_session.scalar(
            select(EventScoreRecord).where(EventScoreRecord.event_id == record.id)
        )
        score.breakdown = value
        malformed_ids.append(record.id)
    db_session.commit()

    service = EventQueryService(db_session)
    home = service.home(now=now)
    page = service.list_events()

    assert [row.event_id for row in home.events] == [valid.id]
    assert valid.id in {row.event_id for row in page.events}
    for event_id in malformed_ids:
        assert service.get_event(event_id) is None


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
    version = db_session.query(EventVersionRecord).filter_by(event_id=record.id).one()
    version.payload = {
        **version.payload,
        "model_runs": [
            {
                "model": "MiniMax-current",
                "purpose": "event_enrichment",
                "outcome": "success",
                "latency_ms": 12.5,
                "error": "must-not-render",
                "input_tokens": 999,
            }
        ],
    }
    db_session.commit()

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        detail = EventQueryService(db_session).get_event(record.id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert detail is not None
    assert detail.model_runs[0].model == "MiniMax-current"
    assert detail.model_runs[0].purpose == "event_enrichment"
    assert detail.model_runs[0].outcome == "success"
    assert detail.model_runs[0].latency_ms == 12.5
    assert "Authorization" not in repr(detail)
    assert "must-not-leak" not in repr(detail)
    assert "input_tokens" not in repr(detail)
    assert not any("model_usage" in statement for statement in statements)


def test_current_detail_rejects_malformed_evidence_snapshot(db_session):
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

    assert detail is None


def test_current_detail_rejects_missing_score(db_session):
    from newsradar.web.event_queries import EventQueryService

    record = _event(
        db_session,
        event_id=14,
        status="confirmed",
        title="缺少评分",
        occurred_at=datetime.now(UTC),
    )
    score = db_session.scalar(
        select(EventScoreRecord).where(EventScoreRecord.event_id == record.id)
    )
    db_session.delete(score)
    db_session.commit()

    assert EventQueryService(db_session).get_event(record.id) is None


def test_evidence_members_respect_current_version_interval(db_session):
    from newsradar.web.event_queries import EventQueryService

    record = _event(
        db_session,
        event_id=15,
        status="confirmed",
        title="成员版本区间",
        occurred_at=datetime.now(UTC),
    )
    rows = []
    for suffix in ("future", "scheduled-removal"):
        raw = RawItemRecord(
            source_id="github-openai-python",
            external_id=f"interval-{suffix}",
            canonical_url=f"https://example.com/{suffix}",
            payload={},
            title=suffix,
        )
        db_session.add(raw)
        db_session.flush()
        rows.append(raw)
    db_session.add_all(
        [
            EventItemRecord(
                event_id=record.id, raw_item_id=rows[0].id, added_version_number=2
            ),
            EventItemRecord(
                event_id=record.id,
                raw_item_id=rows[1].id,
                added_version_number=1,
                removed_version_number=2,
            ),
        ]
    )
    version = db_session.query(EventVersionRecord).filter_by(event_id=record.id).one()
    payload = dict(version.payload)
    payload["evidence"] = [*payload["evidence"], *(
        {
            "raw_item_id": raw.id,
            "role": "professional_media",
            "root_evidence_key": f"root:{raw.external_id}",
            "independent": True,
            "limitations": [],
        }
        for raw in rows
    )]
    version.payload = payload
    db_session.commit()

    detail = EventQueryService(db_session).get_event(record.id)

    assert detail is not None
    titles = {row.title for row in detail.evidence}
    assert "future" not in titles
    assert "scheduled-removal" in titles


def test_evidence_limitation_is_localized_once(db_session):
    from newsradar.web.event_queries import EventQueryService

    record = _event(
        db_session,
        event_id=16,
        status="confirmed",
        title="限制本地化",
        occurred_at=datetime.now(UTC),
    )
    version = db_session.query(EventVersionRecord).filter_by(event_id=record.id).one()
    enrichment = {**version.payload["enrichment"], "limitations": []}
    evidence = [{**version.payload["evidence"][0], "limitations": ["not_peer_reviewed"]}]
    version.payload = {**version.payload, "enrichment": enrichment, "evidence": evidence}
    db_session.commit()

    detail = EventQueryService(db_session).get_event(record.id)

    assert detail is not None
    assert detail.evidence[0].limitations == ("未经同行评审",)
    assert detail.limitations == ("未经同行评审",)


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
        "enrichment": {
            "origin": "rule_fallback",
            "why_it_matters": "安全链接验证",
            "limitations": [],
        },
        "evidence": [
            {
                "raw_item_id": raw.id,
                "role": "official",
                "root_evidence_key": "root:official",
                "independent": True,
                "limitations": [],
            }
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
