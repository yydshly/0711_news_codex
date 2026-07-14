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
    RawItemProcessingRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.reporting import (
    build_event_quality_report_view,
    render_event_quality_report,
)

NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)


def test_event_quality_report_projects_complete_v2_closure_from_database() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            SourceDefinitionRecord(
                id="official-ai",
                name="Official AI",
                provider_id="github",
                target_type="publisher_feed",
                availability="ready",
                coverage_mode="direct",
                official_identity_url="https://example.test/official",
                status="candidate",
                nature="first_party",
                language="en",
                roles=["evidence"],
                topics=["ai"],
                authority_score=5,
                poll_interval_minutes=60,
                expected_fields=["title", "canonical_url"],
                definition_hash="official-ai-hash",
            )
        )
        session.flush()
        raw_items = [
            RawItemRecord(
                source_id="official-ai",
                external_id=f"item-{index}",
                canonical_url=f"https://example.test/items/{index}",
                payload={},
                title="OpenAI 发布多模态模型" if index == 1 else "Generic technology roundup",
                fetched_at=NOW - timedelta(hours=index),
            )
            for index in (1, 2)
        ]
        session.add_all(raw_items)
        session.flush()
        session.add_all(
            [
                RawItemProcessingRecord(
                    raw_item_id=raw_items[0].id,
                    stage="relevance",
                    algorithm_version="relevance-v2",
                    outcome="included",
                    score=95,
                    reason_codes=["explicit_ai_signal"],
                    details={},
                ),
                RawItemProcessingRecord(
                    raw_item_id=raw_items[1].id,
                    stage="relevance",
                    algorithm_version="relevance-v2",
                    outcome="excluded",
                    score=10,
                    reason_codes=["generic_technology"],
                    details={},
                ),
            ]
        )
        session.add(
            EventCandidateRecord(
                candidate_key="openai:model-release",
                algorithm_version="cluster-v2",
                title="OpenAI 发布多模态模型",
                state="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        event = EventRecord(
            canonical_key="openai:model-release",
            visibility="current",
            status="confirmed",
            current_version_number=1,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(event)
        session.flush()
        session.add(
            EventVersionRecord(
                event_id=event.id,
                version_number=1,
                zh_title="OpenAI 发布多模态模型",
                zh_summary="官方发布了新的多模态模型。",
                payload={},
                created_at=NOW,
            )
        )
        session.add(
            EventScoreRecord(
                event_id=event.id,
                version_number=1,
                heat=82,
                breakdown={
                    "ai_relevance": 95,
                    "source_coverage": 35,
                    "source_authority": 100,
                    "recency": 100,
                    "engagement_velocity": 20,
                    "novelty": 100,
                },
                created_at=NOW,
            )
        )
        usage = ModelUsageRecord(
            purpose="event_enrichment",
            model="MiniMax-M2.7-highspeed",
            outcome="success",
            created_at=NOW,
        )
        session.add(usage)
        session.flush()
        session.add(
            EventModelRunRecord(
                event_id=event.id,
                model_usage_id=usage.id,
                stage="event_enrichment",
                algorithm_version="MiniMax-M2.7-highspeed",
                created_at=NOW,
            )
        )
        retry_usage = ModelUsageRecord(
            purpose="event_enrichment",
            model="MiniMax-M2.7-highspeed",
            outcome="retry",
            error="invalid_response",
            created_at=NOW,
        )
        session.add(retry_usage)
        session.flush()
        session.add(
            EventModelRunRecord(
                event_id=event.id,
                model_usage_id=retry_usage.id,
                stage="event_enrichment",
                algorithm_version="MiniMax-M2.7-highspeed",
                created_at=NOW,
            )
        )
        session.commit()

        view = build_event_quality_report_view(session, window_hours=72, now=NOW)
        report = render_event_quality_report(view)

    assert view.selected_count == 2
    assert view.processed_count == 2
    assert view.included_count + view.excluded_count == view.selected_count
    assert view.candidate_count == 1
    assert dict(view.visibility_counts)["current"] == 1
    assert view.score_snapshot_count == 1
    assert view.score_averages.ai_relevance == 95
    assert view.minimax_success_count == 1
    assert view.minimax_fallback_count == 0
    assert "规则处理覆盖率：100.0%" in report
    assert "OpenAI 发布多模态模型" not in report
