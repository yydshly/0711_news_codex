"""Atomic assembly of durable, reader-visible event versions."""

from __future__ import annotations

from newsradar.ai.minimax import ModelUsage
from newsradar.events.evidence import assess_evidence
from newsradar.events.repository import EventRepository
from newsradar.events.schema import (
    CandidateCluster,
    EventEnrichment,
    EventScoreInput,
    PublishedEvent,
)
from newsradar.events.scoring import decide_publication, score_event


class EventPublisher:
    """Publish already-computed candidate facts through one atomic repository operation."""

    def __init__(self, repository: EventRepository):
        self.repository = repository

    def publish(
        self,
        candidate_id: int,
        operation_id: int,
        *,
        score_input: EventScoreInput,
        enrichment: EventEnrichment | None = None,
    ) -> PublishedEvent:
        published = self.assemble(
            candidate_id, score_input=score_input, enrichment=enrichment
        )
        event = self.repository.publish_complete_event(published, operation_id)
        return published.model_copy(update={"event_id": event.id})

    def publish_snapshot(
        self,
        candidate: CandidateCluster,
        operation_id: int,
        *,
        score_input: EventScoreInput,
        enrichment: EventEnrichment | None = None,
        model_usages: tuple[ModelUsage, ...] = (),
    ) -> PublishedEvent:
        """Publish the exact immutable candidate snapshot that was scored."""
        published = self.assemble_snapshot(
            candidate, score_input=score_input, enrichment=enrichment
        )
        event = self.repository.publish_complete_event(
            published,
            operation_id,
            model_usages=model_usages,
        )
        return published.model_copy(update={"event_id": event.id})

    def assemble(
        self,
        candidate_id: int,
        *,
        score_input: EventScoreInput,
        enrichment: EventEnrichment | None = None,
    ) -> PublishedEvent:
        """Build the complete deterministic snapshot without making it reader-visible."""
        candidate, source_item_ids = self.repository.get_candidate_for_publication(candidate_id)
        candidate = candidate.model_copy(update={"raw_item_ids": source_item_ids})
        return self.assemble_snapshot(
            candidate, score_input=score_input, enrichment=enrichment
        )

    def assemble_snapshot(
        self,
        candidate: CandidateCluster,
        *,
        score_input: EventScoreInput,
        enrichment: EventEnrichment | None = None,
    ) -> PublishedEvent:
        """Assemble evidence, score, and members from one immutable candidate value."""
        evidence = assess_evidence(candidate.items)
        decision = decide_publication(candidate, evidence)
        score = score_event(score_input.model_copy(update={"evidence": evidence}))
        # A model is editorial assistance only.  This deterministic original-title
        # fallback is always complete, so an absent key or a model outage cannot
        # block a confirmed event or leave NULL reader-facing fields.
        enrichment = enrichment or _rule_enrichment(candidate)
        return PublishedEvent(
            canonical_key=candidate.candidate_key,
            status=decision.status,
            category=candidate.category,
            occurred_at=candidate.occurred_at,
            enrichment=enrichment,
            score=score,
            evidence=evidence,
            source_item_ids=candidate.raw_item_ids,
        )
def rule_enrichment(candidate) -> EventEnrichment:
    title = candidate.title.strip() or "未命名 AI 事件"
    return EventEnrichment(
        zh_title=title,
        zh_summary=title,
        why_it_matters="已按可追溯规则汇总；中文增强暂不可用。",
        limitations=("model_unavailable_or_not_configured",),
        origin="rule_fallback",
        confidence=0,
    )


# Backwards-compatible private spelling for callers within this module.
_rule_enrichment = rule_enrichment
