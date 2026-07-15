from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    EventCandidateRecord,
    EventModelRunRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    ModelUsageRecord,
    OperationRunRecord,
)
from newsradar.events.reporting import (
    build_event_quality_report_view,
    render_event_quality_report,
)
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS

NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
GENERATED_AT = NOW + timedelta(hours=2)
SCORE_FIELDS = (
    "ai_relevance",
    "source_coverage",
    "source_authority",
    "recency",
    "engagement_velocity",
    "novelty",
)


def _event(
    session: Session,
    key: str,
    *,
    occurred_at: datetime,
    visibility: str = "current",
    status: str = "confirmed",
    breakdown: dict | None = None,
) -> EventRecord:
    event = EventRecord(
        canonical_key=key,
        visibility=visibility,
        status=status,
        occurred_at=occurred_at,
        current_version_number=1,
        created_at=occurred_at,
        updated_at=occurred_at,
    )
    session.add(event)
    session.flush()
    session.add(
        EventVersionRecord(
            event_id=event.id,
            version_number=1,
            payload={
                "status": status,
                "category": "product_model",
                "occurred_at": occurred_at.isoformat(),
            },
            created_at=occurred_at,
        )
    )
    if breakdown is not None:
        session.add(
            EventScoreRecord(
                event_id=event.id,
                version_number=1,
                heat=50,
                breakdown=breakdown,
                created_at=occurred_at,
            )
        )
    return event


def _score(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "ai_relevance": 95,
        "source_coverage": 35,
        "source_authority": 100,
        "recency": 100,
        "engagement_velocity": 20,
        "novelty": 100,
        "rule_version": "score-v2",
    }
    values.update(overrides)
    return values


def _operation(
    session: Session,
    *,
    event_ids: list[int],
    summary: dict[str, object] | None = None,
    versions: dict[str, str] | None = None,
    created_at: datetime = NOW,
) -> OperationRunRecord:
    operation = OperationRunRecord(
        operation_type="event_pipeline",
        trigger="manual",
        status="succeeded",
        requested_scope={
            "window_hours": 72,
            "window_end": NOW.isoformat(),
            "algorithm_versions": versions or dict(EVENT_ALGORITHM_VERSIONS),
        },
        result_summary=summary
        or {
            "selected_item_count": 2,
            "processed_item_count": 1,
            "included_item_count": 1,
            "excluded_item_count": 1,
            "exclusion_reasons": {"generic_technology": 1},
            "candidate_count": 1,
            "event_ids": event_ids,
            "event_version_snapshots": [
                {"event_id": event_id, "version_number": 1}
                for event_id in event_ids
            ],
            "model_success_count": 1,
            "model_fallback_count": 0,
            "model_error_counts": {},
        },
        started_at=NOW,
        finished_at=NOW + timedelta(minutes=1),
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(operation)
    session.flush()
    return operation


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_report_uses_operation_snapshot_not_mutable_or_future_database_rows() -> None:
    engine = _engine()
    with Session(engine) as session:
        included = _event(
            session,
            "included",
            occurred_at=NOW - timedelta(hours=1),
            breakdown=_score(),
        )
        future = _event(
            session,
            "future",
            occurred_at=NOW + timedelta(minutes=1),
            breakdown=_score(ai_relevance=100),
        )
        _event(
            session,
            "unrelated-legacy",
            occurred_at=NOW - timedelta(hours=1),
            visibility="legacy",
            breakdown=_score(),
        )
        operation = _operation(session, event_ids=[included.id, future.id])
        operation_id = operation.id
        for index in range(101):
            _operation(
                session,
                event_ids=[],
                versions={"relevance": f"wrong-{index}"},
                created_at=NOW + timedelta(seconds=index + 1),
            )
        session.add_all(
            EventCandidateRecord(
                candidate_key=f"mutable-{index}",
                algorithm_version="cluster-v2",
                title="mutable",
                updated_at=GENERATED_AT,
            )
            for index in range(3)
        )
        unrelated_usage = ModelUsageRecord(
            purpose="event_enrichment",
            model="MiniMax-M2.7-highspeed",
            outcome="fallback",
            error="invalid_response",
            created_at=NOW,
        )
        session.add(unrelated_usage)
        session.flush()
        session.add(
            EventModelRunRecord(
                event_id=included.id,
                model_usage_id=unrelated_usage.id,
                stage="event_enrichment",
                algorithm_version="MiniMax-M2.7-highspeed",
                created_at=NOW,
            )
        )
        session.commit()

        view = build_event_quality_report_view(
            session, window_hours=72, now=GENERATED_AT
        )

    assert view.latest_operation_id == operation_id
    assert view.snapshot_at == NOW + timedelta(minutes=1)
    assert view.selected_count == 2
    assert view.processed_count == 1
    assert view.included_count == 1
    assert view.excluded_count == 1
    assert view.candidate_count == 1
    assert view.exclusion_reasons == (("generic_technology", 1),)
    assert view.visibility_counts == (("current", 1),)
    assert view.status_counts == (("confirmed", 1),)
    assert view.category_counts == (("product_model", 1),)
    assert view.score_snapshot_count == 1
    assert view.score_averages.ai_relevance == 95
    assert view.minimax_success_count == 1
    assert view.minimax_fallback_count == 0
    assert view.minimax_error_counts == ()


def test_historical_report_uses_version_and_score_at_operation_completion() -> None:
    engine = _engine()
    with Session(engine) as session:
        event = _event(
            session,
            "historical",
            occurred_at=NOW - timedelta(hours=1),
            status="emerging",
            breakdown=_score(**{field: 10 for field in SCORE_FIELDS}),
        )
        operation = _operation(
            session,
            event_ids=[event.id],
            summary={
                "selected_item_count": 1,
                "processed_item_count": 1,
                "included_item_count": 1,
                "excluded_item_count": 0,
                "exclusion_reasons": {},
                "candidate_count": 1,
                "event_ids": [event.id],
                "event_version_snapshots": [
                    {"event_id": event.id, "version_number": 1}
                ],
                "model_success_count": 1,
                "model_fallback_count": 0,
                "model_error_counts": {},
            },
        )
        session.flush()

        event.status = "confirmed"
        event.current_version_number = 2
        event.updated_at = NOW + timedelta(minutes=2)
        session.add(
            EventVersionRecord(
                event_id=event.id,
                version_number=2,
                payload={
                    "status": "confirmed",
                    "category": "research",
                    "occurred_at": (NOW - timedelta(hours=1)).isoformat(),
                },
                created_at=NOW + timedelta(minutes=2),
            )
        )
        session.add(
            EventScoreRecord(
                event_id=event.id,
                version_number=2,
                heat=100,
                breakdown=_score(**{field: 100 for field in SCORE_FIELDS}),
                created_at=NOW + timedelta(minutes=2),
            )
        )
        session.commit()

        view = build_event_quality_report_view(
            session, window_hours=72, now=GENERATED_AT
        )

    assert view.latest_operation_id == operation.id
    assert view.snapshot_at == NOW + timedelta(minutes=1)
    assert view.status_counts == (("emerging", 1),)
    assert view.category_counts == (("product_model", 1),)
    assert view.score_snapshot_count == 1
    assert view.score_averages.ai_relevance == 10


def test_historical_report_uses_manifested_score_when_score_write_is_retried_later() -> None:
    engine = _engine()
    with Session(engine) as session:
        event = _event(
            session,
            "late-score-write",
            occurred_at=NOW - timedelta(hours=1),
            breakdown=None,
        )
        operation = _operation(session, event_ids=[event.id])
        session.add(
            EventScoreRecord(
                event_id=event.id,
                version_number=1,
                heat=50,
                breakdown=_score(**{field: 10 for field in SCORE_FIELDS}),
                created_at=NOW + timedelta(hours=24),
            )
        )
        session.commit()

        view = build_event_quality_report_view(
            session, window_hours=72, now=NOW + timedelta(hours=48)
        )

    assert view.latest_operation_id == operation.id
    assert view.snapshot_at == NOW + timedelta(minutes=1)
    assert view.score_snapshot_count == 1
    assert view.score_averages.ai_relevance == 10


def test_report_accepts_zero_score_v2_but_rejects_v1_and_malformed_snapshots() -> None:
    engine = _engine()
    with Session(engine) as session:
        zero = _event(
            session,
            "zero-v2",
            occurred_at=NOW,
            breakdown=_score(**{field: 0 for field in SCORE_FIELDS}),
        )
        v1 = _event(
            session,
            "score-v1",
            occurred_at=NOW,
            breakdown=_score(rule_version="score-v1"),
        )
        malformed = _event(
            session,
            "malformed-v2",
            occurred_at=NOW,
            breakdown=_score(ai_relevance=True),
        )
        incomplete = _event(
            session,
            "incomplete-v2",
            occurred_at=NOW,
            breakdown={"rule_version": "score-v2", "ai_relevance": 90},
        )
        _operation(session, event_ids=[zero.id, v1.id, malformed.id, incomplete.id])
        session.commit()

        view = build_event_quality_report_view(
            session, window_hours=72, now=GENERATED_AT
        )

    assert view.score_snapshot_count == 1
    assert all(getattr(view.score_averages, field) == 0 for field in SCORE_FIELDS)
    assert "score_snapshot_incomplete" in view.remaining_issue_codes


def test_report_marks_empty_database_as_no_input_with_zero_coverage() -> None:
    with Session(_engine()) as session:
        view = build_event_quality_report_view(
            session, window_hours=72, now=GENERATED_AT
        )
        report = render_event_quality_report(view)

    assert view.selected_count == 0
    assert view.snapshot_at is None
    assert "no_input" in view.remaining_issue_codes
    assert "规则处理覆盖率：0.0%" in report


def test_report_does_not_guess_model_errors_from_concurrent_usage() -> None:
    engine = _engine()
    with Session(engine) as session:
        operation = _operation(
            session,
            event_ids=[],
            summary={
                "selected_item_count": 1,
                "processed_item_count": 0,
                "included_item_count": 0,
                "excluded_item_count": 1,
                "exclusion_reasons": {"generic_technology": 1},
                "candidate_count": 0,
                "event_ids": [],
                "event_version_snapshots": [],
                "model_success_count": 0,
                "model_fallback_count": 2,
            },
        )
        usage = ModelUsageRecord(
            purpose="event_enrichment",
            model="MiniMax-M2.7-highspeed",
            outcome="fallback",
            error="invalid_response",
            created_at=NOW,
        )
        session.add(usage)
        session.flush()
        session.add(
            EventModelRunRecord(
                event_id=None,
                model_usage_id=usage.id,
                stage="event_enrichment",
                algorithm_version="MiniMax-M2.7-highspeed",
                created_at=NOW,
            )
        )
        session.commit()

        view = build_event_quality_report_view(
            session, window_hours=72, now=GENERATED_AT
        )

    assert view.latest_operation_id == operation.id
    assert view.minimax_error_counts == (("error_attribution_unavailable", 2),)
    assert "model_error_attribution_unavailable" in view.remaining_issue_codes


def test_legacy_summary_without_errors_is_valid_when_no_model_fallback_occurred() -> None:
    engine = _engine()
    with Session(engine) as session:
        _operation(
            session,
            event_ids=[],
            summary={
                "selected_item_count": 1,
                "processed_item_count": 0,
                "included_item_count": 0,
                "excluded_item_count": 1,
                "exclusion_reasons": {"generic_technology": 1},
                "candidate_count": 0,
                "event_ids": [],
                "event_version_snapshots": [],
                "model_success_count": 0,
                "model_fallback_count": 0,
            },
        )
        session.commit()

        view = build_event_quality_report_view(
            session, window_hours=72, now=GENERATED_AT
        )

    assert "operation_snapshot_invalid" not in view.remaining_issue_codes
    assert "model_error_attribution_unavailable" not in view.remaining_issue_codes


def test_report_bounds_and_validates_operation_event_ids() -> None:
    engine = _engine()
    with Session(engine) as session:
        _operation(
            session,
            event_ids=[],
            summary={
                "selected_item_count": 1,
                "processed_item_count": 0,
                "included_item_count": 0,
                "excluded_item_count": 1,
                "exclusion_reasons": {},
                "candidate_count": 0,
                "event_ids": list(range(1, 10_002)),
                "model_success_count": 0,
                "model_fallback_count": 0,
                "model_error_counts": {},
            },
        )
        session.commit()

        view = build_event_quality_report_view(
            session, window_hours=72, now=GENERATED_AT
        )

    assert view.visibility_counts == ()
    assert "operation_snapshot_invalid" in view.remaining_issue_codes


def test_report_rejects_incomplete_version_manifest_without_current_fallback() -> None:
    engine = _engine()
    with Session(engine) as session:
        event = _event(
            session,
            "manifest-gap",
            occurred_at=NOW - timedelta(hours=1),
            breakdown=_score(),
        )
        _operation(
            session,
            event_ids=[event.id],
            summary={
                "selected_item_count": 1,
                "processed_item_count": 1,
                "included_item_count": 1,
                "excluded_item_count": 0,
                "exclusion_reasons": {},
                "candidate_count": 1,
                "event_ids": [event.id],
                "event_version_snapshots": [],
                "model_success_count": 1,
                "model_fallback_count": 0,
                "model_error_counts": {},
            },
        )
        session.commit()

        view = build_event_quality_report_view(
            session, window_hours=72, now=GENERATED_AT
        )

    assert view.visibility_counts == ()
    assert view.score_snapshot_count == 0
    assert "operation_snapshot_invalid" in view.remaining_issue_codes
    assert "event_snapshot_incomplete" in view.remaining_issue_codes
