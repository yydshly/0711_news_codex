"""Bounded, deterministic event processing stages for durable operations."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from newsradar.db.models import (
    EventItemRecord,
    EventRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.clustering import CLUSTER_RULE_VERSION, cluster_candidates
from newsradar.events.entities import ENTITY_RULE_VERSION, extract_entities
from newsradar.events.evidence import assess_evidence, count_suppressed_independent_roots
from newsradar.events.minimax import EventMiniMaxAdapter, EventModelRun
from newsradar.events.publishing import EventPublisher, rule_enrichment
from newsradar.events.relevance import RELEVANCE_RULE_VERSION, evaluate_relevance
from newsradar.events.repository import EventRepository
from newsradar.events.schema import (
    ClusterItem,
    EventCategory,
    ProcessingStage,
    RawItemText,
    RelevanceDecision,
)
from newsradar.settings import get_settings

ALGORITHM_VERSIONS = {
    "relevance": RELEVANCE_RULE_VERSION,
    "entities": ENTITY_RULE_VERSION,
    "cluster": CLUSTER_RULE_VERSION,
}


@dataclass(frozen=True)
class PipelineResult:
    current_event_ids: tuple[int, ...]
    created_event_versions: int
    candidate_count: int
    processed_item_count: int
    selected_item_count: int
    included_item_count: int
    excluded_item_count: int
    exclusion_reasons: dict[str, int]
    duplicate_root_suppressed_count: int
    model_fallback_count: int


@dataclass(frozen=True)
class SelectionResult:
    selected_count: int
    included: tuple[ClusterItem, ...]
    excluded_count: int
    exclusion_reasons: dict[str, int]
    decisions: tuple[tuple[int, RelevanceDecision], ...]


class EventPipeline:
    """Run each event stage in a fresh short-lived database session."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    @classmethod
    def production(cls, session: Session) -> EventPipeline:
        bind = session.get_bind()
        return cls(sessionmaker(bind=bind, expire_on_commit=False))

    def run(
        self, *, window_hours: int, operation_id: int, checkpoint: Callable[[str], None]
    ) -> PipelineResult:
        if window_hours <= 0:
            raise ValueError("window_hours must be positive")
        checkpoint("before_event_selection")
        selection = self._select_and_classify_items(window_hours)
        checkpoint("after_event_selection")
        self._record_item_stages(selection)
        checkpoint("after_event_rules")
        candidates = self._cluster(selection.included)
        checkpoint("after_event_cluster")
        duplicate_root_suppressed_count = sum(
            count_suppressed_independent_roots(assess_evidence(candidate.items))
            for candidate in candidates
        )
        event_ids, created_versions, model_fallback_count = self._publish(
            candidates, operation_id, checkpoint
        )
        checkpoint("after_event_publish")
        return PipelineResult(
            current_event_ids=tuple(sorted(event_ids)),
            created_event_versions=created_versions,
            candidate_count=len(candidates),
            processed_item_count=len(selection.included),
            selected_item_count=selection.selected_count,
            included_item_count=len(selection.included),
            excluded_item_count=selection.excluded_count,
            exclusion_reasons=dict(selection.exclusion_reasons),
            duplicate_root_suppressed_count=duplicate_root_suppressed_count,
            model_fallback_count=model_fallback_count,
        )

    def _select_and_classify_items(self, window_hours: int) -> SelectionResult:
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        with self._session_factory() as session:
            event_time = func.coalesce(RawItemRecord.published_at, RawItemRecord.fetched_at)
            rows = session.execute(
                select(RawItemRecord, SourceDefinitionRecord)
                .join(
                    SourceDefinitionRecord,
                    SourceDefinitionRecord.id == RawItemRecord.source_id,
                )
                .where(event_time >= cutoff)
                .order_by(RawItemRecord.id)
            ).all()
            included: list[ClusterItem] = []
            decisions: list[tuple[int, RelevanceDecision]] = []
            exclusion_reasons: Counter[str] = Counter()
            for item, source in rows:
                text = RawItemText(
                    raw_item_id=item.id,
                    title=item.title or "",
                    summary=item.summary or "",
                    content=item.content or "",
                    item_kind=item.item_kind,
                    publisher_name=item.publisher_name or source.name,
                    source_topics=tuple(source.topics),
                )
                decision = evaluate_relevance(text)
                decisions.append((item.id, decision))
                if decision.outcome == "excluded":
                    exclusion_reasons.update(decision.reasons)
                    continue
                entities = tuple(entity.canonical_key for entity in extract_entities(text))
                included.append(
                    ClusterItem(
                        raw_item_id=item.id,
                        title=item.title or "",
                        canonical_url=item.canonical_url,
                        canonical_url_hash=item.canonical_url_hash,
                        original_url=item.original_url,
                        title_fingerprint=item.title_fingerprint,
                        entities=entities,
                        published_at=item.published_at or item.fetched_at,
                        source_nature=source.nature,
                        source_roles=tuple(source.roles),
                        publisher_name=item.publisher_name or source.name,
                    )
                )
            return SelectionResult(
                selected_count=len(rows),
                included=tuple(included),
                excluded_count=len(rows) - len(included),
                exclusion_reasons=dict(sorted(exclusion_reasons.items())),
                decisions=tuple(decisions),
            )

    def _record_item_stages(self, selection: SelectionResult) -> None:
        with self._session_factory() as session:
            repository = EventRepository(session)
            repository.record_relevance_decisions(
                selection.decisions, RELEVANCE_RULE_VERSION
            )
            for item in selection.included:
                repository.record_stage(
                    item.raw_item_id, ProcessingStage.ENTITIES, ENTITY_RULE_VERSION
                )
            session.commit()

    def _cluster(self, items: tuple[ClusterItem, ...]):
        candidates = tuple(
            candidate.model_copy(update={"category": _category(candidate.items)})
            for candidate in cluster_candidates(items)
        )
        with self._session_factory() as session:
            repository = EventRepository(session)
            for candidate in candidates:
                record = repository.upsert_candidate(candidate, CLUSTER_RULE_VERSION)
                repository.replace_candidate_items(record.id, candidate.raw_item_ids)
                for raw_item_id in candidate.raw_item_ids:
                    repository.record_stage(
                        raw_item_id, ProcessingStage.CLUSTER, CLUSTER_RULE_VERSION
                    )
            session.commit()
        return candidates

    def _publish(self, candidates, operation_id: int, checkpoint: Callable[[str], None]):
        event_ids: list[int] = []
        created = 0
        model_fallback_count = 0
        for candidate in candidates:
            checkpoint("before_event_publish_candidate")
            # Persist/read the bounded candidate context first, then close the DB
            # transaction before optional HTTP work.  No event lease exists here.
            with self._session_factory() as session:
                candidate_record = EventRepository(session).upsert_candidate(
                    candidate, CLUSTER_RULE_VERSION
                )
                session.flush()
                existing = session.scalar(
                    select(EventRecord).where(EventRecord.canonical_key == candidate.candidate_key)
                )
                if existing is not None and self._has_same_membership(
                    session, existing.id, candidate.raw_item_ids
                ):
                    event_ids.append(existing.id)
                session.commit()
                if existing is not None and self._has_same_membership(
                    session, existing.id, candidate.raw_item_ids
                ):
                    continue
                candidate_id = candidate_record.id

            # Network/model work is deliberately between short DB sessions.
            enrichment, model_runs = self._enrich(candidate)
            if enrichment.origin == "rule_fallback":
                model_fallback_count += 1
            with self._session_factory() as session:
                repository = EventRepository(session)
                existing = session.scalar(
                    select(EventRecord).where(EventRecord.canonical_key == candidate.candidate_key)
                )
                claimed_event_id: int | None = None
                if existing is not None:
                    claimed_event_id = existing.id
                    if not repository.claim_event(
                        existing.id, operation_id, datetime.now(UTC) + timedelta(minutes=5)
                    ):
                        event_ids.append(existing.id)
                        session.commit()
                        continue
                published = EventPublisher(repository).publish(
                    candidate_id, operation_id, enrichment
                )
                if claimed_event_id is not None:
                    repository.release_event(claimed_event_id, operation_id)
                assert published.event_id is not None
                for model_run in model_runs:
                    try:
                        with session.begin_nested():
                            repository.record_model_run(published.event_id, model_run.usage)
                    except Exception:
                        # Provenance is best effort; never roll back a published event.
                        continue
                event_ids.append(published.event_id)
                created += 1
                session.commit()
        return event_ids, created, model_fallback_count

    @staticmethod
    def _enrich(candidate):
        """Call MiniMax only in the Worker pipeline; hard fallback remains publishable."""
        fallback = rule_enrichment(candidate)
        settings = get_settings()
        if not settings.minimax_api_key:
            return fallback, ()

        runs: list[EventModelRun] = []

        async def run():
            import httpx

            async with httpx.AsyncClient() as http:
                return await EventMiniMaxAdapter(settings, http, runs.append).enrich_event(
                    candidate, fallback
                )

        try:
            return asyncio.run(run()), tuple(runs)
        except Exception:
            return fallback, tuple(runs)

    @staticmethod
    def _has_same_membership(
        session: Session, event_id: int, raw_item_ids: tuple[int, ...]
    ) -> bool:
        active = session.scalars(
            select(EventItemRecord.raw_item_id).where(
                EventItemRecord.event_id == event_id,
                EventItemRecord.removed_version_number.is_(None),
            )
        ).all()
        return set(active) == set(raw_item_ids)


def _category(items: tuple[ClusterItem, ...]) -> EventCategory:
    text = " ".join(
        f"{item.title} {' '.join(item.entities)}".casefold() for item in items
    )
    if any(word in text for word in ("paper", "research", "benchmark", "arxiv")):
        return EventCategory.RESEARCH
    if any(word in text for word in ("sdk", "api", "developer", "tool", "github")):
        return EventCategory.DEVELOPER_TOOL
    if any(word in text for word in ("acquire", "funding", "raises", "partnership", "company")):
        return EventCategory.COMPANY
    return EventCategory.PRODUCT_MODEL
