import asyncio
from datetime import UTC, datetime

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    OperationRunRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.minimax import EventMiniMaxAdapter
from newsradar.events.pipeline import EventPipeline
from newsradar.events.schema import CandidateCluster, ClusterItem, EventEnrichment
from newsradar.settings import Settings


def test_minimax_offline_does_not_block_rule_publication() -> None:
    """No MiniMax credential can block publication or trigger a network request."""
    fallback = EventEnrichment(
        zh_title="规则标题",
        zh_summary="规则摘要",
        why_it_matters="规则说明",
        limitations=("规则生成",),
        origin="rule_fallback",
        confidence=0.4,
    )
    candidate = CandidateCluster(
        candidate_key="acceptance-model-off",
        title="OpenAI launches model",
        items=(ClusterItem(raw_item_id=1, title="OpenAI launches model"),),
        reasons=("title fingerprint",),
    )

    async def no_network(_: httpx.Request) -> httpx.Response:
        raise AssertionError("MiniMax must not be called when its key is unset")

    async def verify_fallback() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(no_network)) as http:
            result = await EventMiniMaxAdapter(Settings(minimax_api_key=None), http).enrich_event(
                candidate, fallback
            )
        assert result.origin == "rule_fallback"

    asyncio.run(verify_fallback())

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            SourceDefinitionRecord(
                id="model-off-source", name="Model-off official", status="active",
                nature="first_party", language="en", roles=["evidence"], topics=["ai"],
                authority_score=90, poll_interval_minutes=60, expected_fields=[],
                definition_hash="model-off-source",
            )
        )
        session.add(
            RawItemRecord(
                source_id="model-off-source", external_id="1", payload={},
                canonical_url="https://example.test/model-off", title="OpenAI launches model",
                published_at=datetime.now(UTC),
            )
        )
        snapshot = datetime.now(UTC)
        session.add(
            OperationRunRecord(
                id=1,
                operation_type="event_pipeline",
                trigger="manual",
                status="running",
                requested_scope={"window_end": snapshot.isoformat()},
                created_at=snapshot,
            )
        )
        session.commit()
        result = EventPipeline.production(session).run(
            window_hours=24, operation_id=1, checkpoint=lambda _: None
        )
    engine.dispose()

    assert result.current_event_ids
