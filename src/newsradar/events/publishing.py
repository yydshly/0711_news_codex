"""Atomic assembly of durable, reader-visible event versions."""

from __future__ import annotations

from newsradar.events.repository import EventRepository
from newsradar.events.schema import EventScoreInput, PublishedEvent
from newsradar.events.scoring import decide_publication, score_event


class EventPublisher:
    """Publish already-computed candidate facts through one atomic repository operation."""

    def __init__(self, repository: EventRepository):
        self.repository = repository

    def publish(self, candidate_id: int, operation_id: int) -> PublishedEvent:
        candidate, source_item_ids = self.repository.get_candidate_for_publication(candidate_id)
        decision = decide_publication(candidate)
        score = score_event(_score_input(candidate.metadata))
        published = PublishedEvent(
            canonical_key=candidate.candidate_key,
            status=decision.status,
            category=candidate.category,
            score=score,
            source_item_ids=source_item_ids,
        )
        event = self.repository.publish_complete_event(published, operation_id)
        return published.model_copy(update={"event_id": event.id})


def _score_input(metadata: dict) -> EventScoreInput:
    values = metadata.get("score_input", {})
    return EventScoreInput(
        ai_relevance=values.get("ai_relevance", 0),
        source_coverage=values.get("source_coverage", 0),
        source_authority=values.get("source_authority", 0),
        recency=values.get("recency", 0),
        engagement_velocity=values.get("engagement_velocity", 0),
        novelty=values.get("novelty", 0),
    )
