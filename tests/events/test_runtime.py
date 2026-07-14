from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    Base,
    EventItemRecord,
    EventModelRunRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    ModelUsageRecord,
    OperationRunRecord,
    RawItemProcessingRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.minimax import EventModelRun
from newsradar.events.pipeline import EventPipeline, PipelineResult
from newsradar.events.publishing import rule_enrichment
from newsradar.events.repository import EventModelAuditError, EventRepository
from newsradar.events.runtime import EventOperationHandler
from newsradar.events.schema import (
    EventEnrichment,
    EventStatus,
    EvidenceAssessment,
    EvidenceRole,
    ProcessingStage,
    PublishedEvent,
    ScoreBreakdown,
)
from newsradar.operations.deadlines import OperationDeadline, OperationTimedOut
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus


def _score() -> ScoreBreakdown:
    return ScoreBreakdown(
        ai_relevance=80,
        source_coverage=50,
        source_authority=90,
        recency=90,
        engagement_velocity=0,
        novelty=50,
        importance=70,
        credibility=90,
        heat=78,
        rule_version="score-v1",
        reasons=("fixture",),
    )


def _seed_published_event(
    engine,
    titles: tuple[str, ...],
    *,
    origin: str = "rule_fallback",
    missing_relevance_ids: frozenset[int] = frozenset(),
) -> int:
    with Session(engine) as db:
        now = datetime(2026, 7, 14, 12, tzinfo=UTC)
        db.add(
            OperationRunRecord(
                id=1,
                operation_type="event_recluster",
                trigger="manual",
                status="running",
                requested_scope={"window_end": now.isoformat()},
                created_at=now,
            )
        )
        db.add(
            SourceDefinitionRecord(
                id="official",
                name="Official",
                status="active",
                nature="first_party",
                language="en",
                roles=["evidence"],
                topics=["ai"],
                authority_score=90,
                poll_interval_minutes=60,
                expected_fields=[],
                definition_hash="official",
            )
        )
        raw_ids = []
        for index, title in enumerate(titles, start=1):
            raw = RawItemRecord(
                source_id="official",
                external_id=str(index),
                canonical_url=f"https://official.test/{index}",
                payload={},
                title=title,
                title_fingerprint=f"title-{index}",
                published_at=now - timedelta(hours=index),
                fetched_at=now,
                engagement={"score": 1_000 if index == 1 else 0},
            )
            db.add(raw)
            db.flush()
            raw_ids.append(raw.id)
            if raw.id not in missing_relevance_ids:
                db.add(
                    RawItemProcessingRecord(
                        raw_item_id=raw.id,
                        stage=ProcessingStage.RELEVANCE.value,
                        algorithm_version="relevance-v2",
                        outcome="included",
                        score=100 if index == 1 else 60,
                        reason_codes=[],
                        details={},
                        created_at=now,
                    )
                )
        event = EventRepository(db).publish_complete_event(
            PublishedEvent(
                canonical_key="legacy-combined",
                status=EventStatus.CONFIRMED,
                enrichment=EventEnrichment(
                    zh_title="Current title",
                    zh_summary="Current summary",
                    why_it_matters="Current reason",
                    origin=origin,
                    confidence=0.8 if origin == "model" else 0,
                ),
                score=_score(),
                evidence=tuple(
                    EvidenceAssessment(
                        raw_item_id=raw_id,
                        role=EvidenceRole.OFFICIAL,
                        root_evidence_key=f"https://official.test/{raw_id}",
                        independent=True,
                    )
                    for raw_id in raw_ids
                ),
                source_item_ids=tuple(raw_ids),
            ),
            operation_id=1,
        )
        db.commit()
        return event.id


def test_event_handler_rejects_invalid_pipeline_scope() -> None:
    handler = EventOperationHandler(lambda: None)
    result = handler(OperationLease(1, 1, 1, "worker", {}, "event_pipeline"), lambda _: None)

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "invalid_event_scope"


def test_pipeline_worker_result_summary_contains_complete_quality_counts(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    class FakePipeline:
        def run(self, **kwargs):
            del kwargs
            return PipelineResult(
                current_event_ids=(10, 11),
                created_event_versions=2,
                candidate_count=3,
                processed_item_count=4,
                selected_item_count=7,
                included_item_count=4,
                excluded_item_count=3,
                exclusion_reasons={"generic_technology": 2, "insufficient_text": 1},
                duplicate_root_suppressed_count=1,
                model_success_count=1,
                model_fallback_count=1,
            )

    monkeypatch.setattr(
        EventPipeline,
        "production",
        classmethod(lambda cls, session: FakePipeline()),
    )
    deadline = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1,
            1,
            1,
            "worker",
            {"window_hours": 72, "deadline_at": deadline},
            "event_pipeline",
        ),
        lambda _: None,
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert result.result_summary == {
        "event_ids": [10, 11],
        "selected_item_count": 7,
        "included_item_count": 4,
        "excluded_item_count": 3,
        "exclusion_reasons": {
            "generic_technology": 2,
            "insufficient_text": 1,
        },
        "candidate_count": 3,
        "created_event_versions": 2,
        "model_success_count": 1,
        "model_fallback_count": 1,
        "processed_item_count": 4,
        "duplicate_root_suppressed_count": 1,
        "duration_ms": result.result_summary["duration_ms"],
        "retry_count": 0,
    }


def test_event_action_rejects_unknown_event_id() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    handler = EventOperationHandler(lambda: Session(engine))

    result = handler(
        OperationLease(1, 1, 1, "worker", {"event_id": 99}, "event_exclude"), lambda _: None
    )

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "unknown_event"
    assert result.retryable is False


def test_recluster_splits_incompatible_members_and_publishes_changed_versions() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    event_id = _seed_published_event(
        engine,
        ("OpenAI launches Alpha model", "OpenAI launches Beta model"),
    )

    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1, 1, 1, "worker", {"event_id": event_id, "actor": "web"}, "event_recluster"
        ),
        lambda _: None,
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert result.result_summary["action"] == "event_recluster"
    assert result.result_summary["changed"] is True
    assert result.result_summary["candidate_count"] == 2
    assert len(result.result_summary["created_event_ids"]) == 1
    with Session(engine) as db:
        target = db.get(EventRecord, event_id)
        assert target is not None
        assert target.current_version_number == 2
        active_target = set(
            db.scalars(
                select(EventItemRecord.raw_item_id).where(
                    EventItemRecord.event_id == event_id,
                    EventItemRecord.removed_version_number.is_(None),
                )
            )
        )
        assert active_target == {1}
        split_id = result.result_summary["created_event_ids"][0]
        active_split = set(
            db.scalars(
                select(EventItemRecord.raw_item_id).where(
                    EventItemRecord.event_id == split_id,
                    EventItemRecord.removed_version_number.is_(None),
                )
            )
        )
        assert active_split == {2}
        scores = {
            row.event_id: row.breakdown
            for row in db.scalars(select(EventScoreRecord))
        }
        assert scores[event_id]["rule_version"] == "score-v2"
        assert scores[event_id]["ai_relevance"] == 100
        assert scores[event_id]["engagement_velocity"] > 0
        assert scores[event_id]["novelty"] == 0
        assert "novelty:pure_repeat" in scores[event_id]["reasons"]
        assert "novelty:no_prior_event" not in scores[event_id]["reasons"]
        assert scores[split_id]["rule_version"] == "score-v2"
        assert scores[split_id]["ai_relevance"] == 60
        assert scores[split_id]["engagement_velocity"] == 0
        assert scores[split_id]["novelty"] == 0
        assert "novelty:pure_repeat" in scores[split_id]["reasons"]
        assert "novelty:no_prior_event" not in scores[split_id]["reasons"]


def test_recluster_missing_real_quality_input_preserves_old_version() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    event_id = _seed_published_event(
        engine,
        ("OpenAI launches Alpha model", "OpenAI launches Beta model"),
        missing_relevance_ids=frozenset({2}),
    )

    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1,
            1,
            1,
            "worker",
            {"event_id": event_id, "actor": "web"},
            "event_recluster",
        ),
        lambda _: None,
    )

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "event_quality_input_unavailable"
    with Session(engine) as db:
        assert db.get(EventRecord, event_id).current_version_number == 1
        assert db.query(EventRecord).count() == 1
        assert db.query(EventVersionRecord).count() == 1


def test_recluster_does_not_publish_when_membership_is_unchanged() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    event_id = _seed_published_event(engine, ("OpenAI launches Alpha model",))

    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1, 2, 1, "worker", {"event_id": event_id, "actor": "web"}, "event_recluster"
        ),
        lambda _: None,
    )

    assert result.result_summary["changed"] is False
    with Session(engine) as db:
        assert db.get(EventRecord, event_id).current_version_number == 1
        assert db.query(EventVersionRecord).count() == 1


def test_enrich_calls_model_without_session_or_lease_and_persists_provenance(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    event_id = _seed_published_event(engine, ("OpenAI launches Alpha model",))
    open_sessions: set[Session] = set()

    class TrackingSession(Session):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            open_sessions.add(self)

        def close(self) -> None:
            try:
                super().close()
            finally:
                open_sessions.discard(self)

    def model_enrichment(candidate):
        assert open_sessions == set()
        with engine.connect() as connection:
            assert connection.scalar(
                text("select lease_operation_id from events where id=:event_id"),
                {"event_id": event_id},
            ) is None
        usage = ModelUsage(
            purpose="event_enrichment",
            model="MiniMax-M2.7-highspeed",
            input_tokens=10,
            output_tokens=5,
            latency_ms=2,
            outcome="success",
        )
        return (
            EventEnrichment(
                zh_title="Alpha 模型发布",
                zh_summary="OpenAI 发布 Alpha 模型",
                why_it_matters="新的模型版本",
                origin="model",
                confidence=0.9,
            ),
            (EventModelRun(stage=usage.purpose, usage=usage),),
        )

    monkeypatch.setattr(EventPipeline, "_enrich", staticmethod(model_enrichment))
    factory = sessionmaker(bind=engine, class_=TrackingSession, expire_on_commit=False)
    result = EventOperationHandler(factory)(
        OperationLease(
            1, 3, 1, "worker", {"event_id": event_id, "actor": "web"}, "event_enrich"
        ),
        lambda _: None,
    )

    assert result.result_summary["changed"] is True
    assert result.result_summary["model_origin"] == "model"
    assert open_sessions == set()
    with Session(engine) as db:
        event = db.get(EventRecord, event_id)
        assert event is not None
        assert event.current_version_number == 2
        version = db.scalar(
            select(EventVersionRecord).where(
                EventVersionRecord.event_id == event_id,
                EventVersionRecord.version_number == 2,
            )
        )
        assert version is not None
        assert version.payload["enrichment"]["zh_title"] == "Alpha 模型发布"
        usage = db.scalar(select(ModelUsageRecord))
        run = db.scalar(select(EventModelRunRecord))
        assert usage is not None and usage.outcome == "success"
        assert run is not None and run.event_id == event_id
        assert event.lease_operation_id is None


def test_enrich_publishes_deterministic_rule_fallback_after_model_degradation(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    event_id = _seed_published_event(
        engine, ("OpenAI launches Alpha model",), origin="model"
    )

    def degraded(candidate):
        return rule_enrichment(candidate), ()

    monkeypatch.setattr(EventPipeline, "_enrich", staticmethod(degraded))
    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1, 4, 1, "worker", {"event_id": event_id, "actor": "web"}, "event_enrich"
        ),
        lambda _: None,
    )

    assert result.result_summary["model_origin"] == "rule_fallback"
    with Session(engine) as db:
        current = EventRepository(db).get_current_event(event_id)
        assert current is not None
        assert current.payload["enrichment"]["origin"] == "rule_fallback"
        assert current.payload["enrichment"]["zh_title"] == "Current title"


def test_enrich_audit_failure_rolls_back_new_version_and_releases_lease(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    event_id = _seed_published_event(engine, ("OpenAI launches Alpha model",))

    def model_enrichment(candidate):
        usage = ModelUsage(
            purpose="event_enrichment",
            model="MiniMax-M2.7-highspeed",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            outcome="success",
        )
        return (
            rule_enrichment(candidate).model_copy(update={"origin": "model"}),
            (EventModelRun(stage=usage.purpose, usage=usage),),
        )

    def fail_audit(self, event_id, usage):
        del self, event_id, usage
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(EventPipeline, "_enrich", staticmethod(model_enrichment))
    monkeypatch.setattr(EventRepository, "record_model_run", fail_audit)
    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1, 5, 1, "worker", {"event_id": event_id, "actor": "web"}, "event_enrich"
        ),
        lambda _: None,
    )

    assert result.status is OperationStatus.FAILED
    assert result.error_code == EventModelAuditError.error_code
    assert result.retryable is True
    with Session(engine) as db:
        event = db.get(EventRecord, event_id)
        assert event is not None
        assert event.current_version_number == 1
        assert event.lease_operation_id is None
        assert db.query(ModelUsageRecord).count() == 0


def test_exclude_action_marks_event_rejected_and_releases_lease() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(EventRecord(id=7, canonical_key="exclude", status="confirmed"))
        db.commit()

    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(1, 9, 1, "worker", {"event_id": 7, "actor": "web"}, "event_exclude"),
        lambda _: None,
    )

    with Session(engine) as db:
        event = db.get(EventRecord, 7)
        assert event is not None
        assert event.status == "rejected"
        assert event.lease_operation_id is None
    assert result.status is OperationStatus.SUCCEEDED


def test_merge_validates_both_event_targets_before_returning_unsupported() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(EventRecord(id=1, canonical_key="one", status="confirmed"))
        db.commit()

    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1,
            1,
            1,
            "worker",
            {"event_id": 1, "target_event_id": 2, "actor": "web"},
            "event_merge",
        ),
        lambda _: None,
    )

    assert result.error_code == "unknown_event"


def test_expired_event_pipeline_returns_timeout_without_publishing() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            SourceDefinitionRecord(
                id="source",
                name="Source",
                status="active",
                nature="first_party",
                language="en",
                roles=["evidence"],
                topics=["ai"],
                authority_score=90,
                poll_interval_minutes=60,
                expected_fields=[],
                definition_hash="source",
            )
        )
        db.add(
            RawItemRecord(
                source_id="source",
                external_id="item",
                canonical_url="https://example.test/item",
                payload={},
                title="OpenAI launches model",
                published_at=datetime.now(UTC),
            )
        )
        db.commit()

    handler = EventOperationHandler(lambda: Session(engine))
    result = handler(
        OperationLease(
            1,
            1,
            1,
            "worker",
            {
                "window_hours": 24,
                "deadline_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            },
            "event_pipeline",
        ),
        lambda _: None,
    )

    with Session(engine) as verify:
        assert verify.query(EventRecord).count() == 0
    assert result.status is OperationStatus.FAILED
    assert result.error_code == "operation_timeout"
    assert result.retryable is False


def test_expired_event_action_mutates_nothing() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(EventRecord(id=8, canonical_key="deadline", status="confirmed"))
        db.commit()
    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1, 1, 1, "worker",
            {
                "event_id": 8,
                "actor": "web",
                "deadline_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            },
            "event_exclude",
        ), lambda _: None,
    )
    with Session(engine) as db:
        assert db.get(EventRecord, 8).status == "confirmed"
    assert result.error_code == "operation_timeout"


def test_merge_claims_both_events_in_sorted_order_and_releases_in_reverse(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                EventRecord(id=1, canonical_key="target", status="confirmed"),
                EventRecord(id=2, canonical_key="survivor", status="confirmed"),
            ]
        )
        db.commit()

    order: list[tuple[str, int]] = []
    original_claim = EventRepository.claim_event
    original_release = EventRepository.release_event

    def observe_claim(self, event_id, operation_id, lease_until):
        order.append(("claim", event_id))
        return original_claim(self, event_id, operation_id, lease_until)

    def observe_release(self, event_id, operation_id):
        order.append(("release", event_id))
        return original_release(self, event_id, operation_id)

    monkeypatch.setattr(EventRepository, "claim_event", observe_claim)
    monkeypatch.setattr(EventRepository, "release_event", observe_release)
    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1,
            51,
            1,
            "worker",
            {"event_id": 2, "target_event_id": 1, "actor": "web"},
            "event_merge",
        ),
        lambda _: None,
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert order == [("claim", 1), ("claim", 2), ("release", 2), ("release", 1)]
    with Session(engine) as db:
        assert db.get(EventRecord, 1).lease_operation_id is None
        assert db.get(EventRecord, 2).lease_operation_id is None


def test_merge_releases_first_lease_when_second_claim_fails(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                EventRecord(id=1, canonical_key="survivor", status="confirmed"),
                EventRecord(id=2, canonical_key="busy", status="confirmed"),
            ]
        )
        db.commit()

    order: list[tuple[str, int]] = []
    original_claim = EventRepository.claim_event
    original_release = EventRepository.release_event

    def fail_second_claim(self, event_id, operation_id, lease_until):
        order.append(("claim", event_id))
        if event_id == 2:
            return False
        return original_claim(self, event_id, operation_id, lease_until)

    def observe_release(self, event_id, operation_id):
        order.append(("release", event_id))
        return original_release(self, event_id, operation_id)

    monkeypatch.setattr(EventRepository, "claim_event", fail_second_claim)
    monkeypatch.setattr(EventRepository, "release_event", observe_release)
    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1,
            52,
            1,
            "worker",
            {"event_id": 1, "target_event_id": 2, "actor": "web"},
            "event_merge",
        ),
        lambda _: None,
    )

    assert result.error_code == "event_lease_unavailable"
    assert order == [("claim", 1), ("claim", 2), ("release", 1)]
    with Session(engine) as db:
        assert db.get(EventRecord, 1).lease_operation_id is None


def test_deadline_after_merge_claim_releases_both_leases_and_returns_timeout(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                EventRecord(id=1, canonical_key="survivor", status="confirmed"),
                EventRecord(id=2, canonical_key="target", status="confirmed"),
            ]
        )
        db.commit()

    class DeadlineAfterClaims:
        def check(self, boundary: str) -> None:
            if boundary == "before_event_mutation":
                raise OperationTimedOut("operation deadline exceeded at before_event_mutation")

    monkeypatch.setattr(
        OperationDeadline,
        "from_scope",
        classmethod(lambda cls, scope: DeadlineAfterClaims()),
    )

    result = EventOperationHandler(lambda: Session(engine))(
        OperationLease(
            1,
            53,
            1,
            "worker",
            {
                "event_id": 1,
                "target_event_id": 2,
                "actor": "web",
                "deadline_at": datetime.now(UTC).isoformat(),
            },
            "event_merge",
        ),
        lambda _: None,
    )

    assert result.error_code == "operation_timeout"
    assert result.retryable is False
    with Session(engine) as db:
        for event_id in (1, 2):
            event = db.get(EventRecord, event_id)
            assert event is not None
            assert event.lease_operation_id is None
            assert event.current_version_number == 0
