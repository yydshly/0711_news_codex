"""Bounded, deterministic event processing stages for durable operations."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from re import fullmatch

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    EventCandidateRecord,
    EventItemRecord,
    EventRecord,
    EventVersionRecord,
    OperationRunRecord,
    RawItemProcessingRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.clustering import CLUSTER_RULE_VERSION, cluster_candidates
from newsradar.events.entities import ENTITY_RULE_VERSION, extract_entities
from newsradar.events.evidence import assess_evidence, count_suppressed_independent_roots
from newsradar.events.minimax import (
    EventEnrichmentBatch,
    EventEnrichmentResult,
    EventMiniMaxAdapter,
    EventModelRun,
)
from newsradar.events.newsworthiness import (
    NEWSWORTHINESS_RULE_VERSION,
    evaluate_newsworthiness,
)
from newsradar.events.publishing import EventPublisher, rule_enrichment
from newsradar.events.quality import build_score_input, filter_engagement_fields
from newsradar.events.relevance import (
    CONTENT_MAX_CHARS,
    ITEM_KIND_MAX_CHARS,
    PUBLISHER_MAX_CHARS,
    RELEVANCE_RULE_VERSION,
    SOURCE_TOPIC_MAX_CHARS,
    SUMMARY_MAX_CHARS,
    TITLE_MAX_CHARS,
    evaluate_relevance,
)
from newsradar.events.repository import (
    EventModelAuditError,
    EventPublicationConflict,
    EventRepository,
)
from newsradar.events.schema import (
    CandidateCluster,
    ClusterItem,
    EventCategory,
    EventScoreInput,
    NewsworthinessDecision,
    ProcessingStage,
    RawItemText,
    RelevanceDecision,
)
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS
from newsradar.settings import get_settings

ALGORITHM_VERSIONS = EVENT_ALGORITHM_VERSIONS


@dataclass(frozen=True)
class PipelineResult:
    current_event_ids: tuple[int, ...]
    event_version_snapshots: tuple[tuple[int, int], ...]
    created_event_versions: int
    candidate_count: int
    processed_item_count: int
    selected_item_count: int
    included_item_count: int
    excluded_item_count: int
    exclusion_reasons: dict[str, int]
    newsworthy_item_count: int
    non_newsworthy_item_count: int
    newsworthiness_reasons: dict[str, int]
    duplicate_root_suppressed_count: int
    model_success_count: int
    model_fallback_count: int
    model_error_counts: dict[str, int]


@dataclass(frozen=True)
class SelectionResult:
    selected_count: int
    included: tuple[ClusterItem, ...]
    excluded_count: int
    exclusion_reasons: dict[str, int]
    decisions: tuple[tuple[int, RelevanceDecision], ...]
    newsworthiness_decisions: tuple[tuple[int, NewsworthinessDecision], ...]
    newsworthiness_reasons: dict[str, int]
    included_texts: tuple[RawItemText, ...]
    authority_by_item: dict[int, object]
    engagement_by_item: dict[int, dict[str, object]]


def _capture_event_version(
    snapshots: dict[int, int], event: EventRecord
) -> None:
    """Capture the exact reader-visible version produced or reused by this run."""
    if event.current_version_number <= 0:
        raise EventPublicationConflict(
            "Event output does not have a reader-visible version"
        )
    snapshots[event.id] = event.current_version_number


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
        snapshot_now = self._operation_window_end(operation_id, checkpoint=checkpoint)
        checkpoint("before_event_selection")
        selection = self._select_and_classify_items(window_hours, now=snapshot_now)
        checkpoint("after_event_selection")
        self._record_relevance_decisions(selection)
        checkpoint("after_event_relevance")
        self._record_newsworthiness_decisions(selection)
        checkpoint("after_event_newsworthiness")
        items = self._extract_and_record_entities(selection)
        checkpoint("after_event_rules")
        candidates = self._cluster(items)
        checkpoint("after_event_cluster")
        duplicate_root_suppressed_count = sum(
            count_suppressed_independent_roots(assess_evidence(candidate.items))
            for candidate in candidates
        )
        (
            event_ids,
            event_version_snapshots,
            created_versions,
            model_success_count,
            model_fallback_count,
            model_error_counts,
        ) = self._publish(
            candidates,
            operation_id,
            checkpoint,
            relevance_by_item={
                raw_item_id: decision.score
                for raw_item_id, decision in selection.decisions
            },
            authority_by_item=selection.authority_by_item,
            engagement_by_item=selection.engagement_by_item,
            now=snapshot_now,
        )
        checkpoint("after_event_publish")
        return PipelineResult(
            current_event_ids=tuple(sorted(set(event_ids))),
            event_version_snapshots=event_version_snapshots,
            created_event_versions=created_versions,
            candidate_count=len(candidates),
            processed_item_count=len(selection.included),
            selected_item_count=selection.selected_count,
            included_item_count=len(selection.included),
            excluded_item_count=selection.excluded_count,
            exclusion_reasons=dict(selection.exclusion_reasons),
            newsworthy_item_count=len(selection.included),
            non_newsworthy_item_count=(
                len(selection.newsworthiness_decisions) - len(selection.included)
            ),
            newsworthiness_reasons=dict(selection.newsworthiness_reasons),
            duplicate_root_suppressed_count=duplicate_root_suppressed_count,
            model_success_count=model_success_count,
            model_fallback_count=model_fallback_count,
            model_error_counts=model_error_counts,
        )

    def _select_and_classify_items(
        self, window_hours: int, *, now: datetime | None = None
    ) -> SelectionResult:
        snapshot_now = now or datetime.now(UTC)
        cutoff = snapshot_now - timedelta(hours=window_hours)
        with self._session_factory() as session:
            event_time = func.coalesce(RawItemRecord.published_at, RawItemRecord.fetched_at)
            rows = tuple(
                session.execute(
                    select(
                        RawItemRecord.id.label("raw_item_id"),
                        func.substr(
                            func.coalesce(RawItemRecord.title, ""), 1, TITLE_MAX_CHARS
                        ).label("title"),
                        func.substr(
                            func.coalesce(RawItemRecord.summary, ""),
                            1,
                            SUMMARY_MAX_CHARS,
                        ).label("summary"),
                        func.substr(
                            func.coalesce(RawItemRecord.content, ""),
                            1,
                            CONTENT_MAX_CHARS,
                        ).label("content"),
                        func.substr(
                            func.coalesce(RawItemRecord.item_kind, ""),
                            1,
                            ITEM_KIND_MAX_CHARS,
                        ).label("item_kind"),
                        func.substr(
                            func.coalesce(
                                RawItemRecord.publisher_name,
                                SourceDefinitionRecord.name,
                            ),
                            1,
                            PUBLISHER_MAX_CHARS,
                        ).label("publisher_name"),
                        func.substr(RawItemRecord.canonical_url, 1, 4_096).label(
                            "canonical_url"
                        ),
                        func.substr(RawItemRecord.original_url, 1, 4_096).label(
                            "original_url"
                        ),
                        RawItemRecord.canonical_url_hash.label("canonical_url_hash"),
                        RawItemRecord.title_fingerprint.label("title_fingerprint"),
                        RawItemRecord.published_at.label("published_at"),
                        RawItemRecord.fetched_at.label("fetched_at"),
                        RawItemRecord.engagement.label("engagement"),
                        SourceDefinitionRecord.nature.label("source_nature"),
                        SourceDefinitionRecord.authority_score.label("authority_score"),
                        SourceDefinitionRecord.roles.label("source_roles"),
                        SourceDefinitionRecord.topics.label("source_topics"),
                    )
                    .join(
                        SourceDefinitionRecord,
                        SourceDefinitionRecord.id == RawItemRecord.source_id,
                    )
                    .where(event_time >= cutoff, event_time <= snapshot_now)
                    .order_by(RawItemRecord.id)
                )
                .mappings()
                .all()
            )

        included: list[ClusterItem] = []
        included_texts: list[RawItemText] = []
        decisions: list[tuple[int, RelevanceDecision]] = []
        newsworthiness_decisions: list[tuple[int, NewsworthinessDecision]] = []
        exclusion_reasons: Counter[str] = Counter()
        newsworthiness_reasons: Counter[str] = Counter()
        authority_by_item: dict[int, object] = {}
        engagement_by_item: dict[int, dict[str, object]] = {}
        for row in rows:
            text = RawItemText(
                raw_item_id=row["raw_item_id"],
                title=row["title"],
                summary=row["summary"],
                content=row["content"],
                item_kind=row["item_kind"] or None,
                publisher_name=row["publisher_name"] or None,
                source_topics=_bounded_values(row["source_topics"]),
            )
            decision = evaluate_relevance(text)
            decisions.append((row["raw_item_id"], decision))
            if decision.outcome == "excluded":
                exclusion_reasons.update(decision.reasons)
                continue
            try:
                newsworthiness = evaluate_newsworthiness(text)
            except Exception:
                newsworthiness = NewsworthinessDecision(
                    outcome="excluded",
                    score=0,
                    reason_codes=("newsworthiness_rule_failed",),
                )
            newsworthiness_decisions.append((row["raw_item_id"], newsworthiness))
            if newsworthiness.outcome == "excluded":
                exclusion_reasons.update(newsworthiness.reason_codes)
                newsworthiness_reasons.update(newsworthiness.reason_codes)
                continue
            included_texts.append(text)
            authority_by_item[row["raw_item_id"]] = row["authority_score"]
            engagement_by_item[row["raw_item_id"]] = _bounded_engagement(
                row["engagement"]
            )
            included.append(
                ClusterItem(
                    raw_item_id=row["raw_item_id"],
                    title=row["title"],
                    canonical_url=row["canonical_url"],
                    canonical_url_hash=row["canonical_url_hash"],
                    original_url=row["original_url"],
                    title_fingerprint=row["title_fingerprint"],
                    entities=(),
                    published_at=row["published_at"] or row["fetched_at"],
                    source_nature=row["source_nature"],
                    source_roles=_bounded_values(row["source_roles"], max_chars=64),
                    publisher_name=row["publisher_name"] or None,
                )
            )
        return SelectionResult(
            selected_count=len(rows),
            included=tuple(included),
            excluded_count=len(rows) - len(included),
            exclusion_reasons=dict(sorted(exclusion_reasons.items())),
            decisions=tuple(decisions),
            newsworthiness_decisions=tuple(newsworthiness_decisions),
            newsworthiness_reasons=dict(sorted(newsworthiness_reasons.items())),
            included_texts=tuple(included_texts),
            authority_by_item=authority_by_item,
            engagement_by_item=engagement_by_item,
        )

    def _operation_window_end(
        self,
        operation_id: int,
        *,
        checkpoint: Callable[[str], None] | None = None,
    ) -> datetime:
        with self._session_factory() as session:
            return load_operation_window_end(
                session, operation_id, checkpoint=checkpoint
            )

    def _record_relevance_decisions(self, selection: SelectionResult) -> None:
        with self._session_factory() as session:
            repository = EventRepository(session)
            repository.record_relevance_decisions(
                selection.decisions, RELEVANCE_RULE_VERSION
            )
            session.commit()

    def _record_newsworthiness_decisions(self, selection: SelectionResult) -> None:
        with self._session_factory() as session:
            repository = EventRepository(session)
            repository.record_newsworthiness_decisions(
                selection.newsworthiness_decisions,
                NEWSWORTHINESS_RULE_VERSION,
            )
            session.commit()

    def _extract_and_record_entities(
        self, selection: SelectionResult
    ) -> tuple[ClusterItem, ...]:
        items: list[ClusterItem] = []
        audits: list[tuple[int, str, tuple[str, ...], int]] = []
        for item, text in zip(selection.included, selection.included_texts, strict=True):
            try:
                entities = tuple(
                    entity.canonical_key for entity in extract_entities(text)
                )
            except Exception:
                entities = ()
                audits.append(
                    (item.raw_item_id, "failed", ("entity_extraction_failed",), 0)
                )
            else:
                audits.append((item.raw_item_id, "included", (), len(entities)))
            items.append(item.model_copy(update={"entities": entities}))

        with self._session_factory() as session:
            repository = EventRepository(session)
            for raw_item_id, outcome, reason_codes, entity_count in audits:
                repository.record_stage(
                    raw_item_id,
                    ProcessingStage.ENTITIES,
                    ENTITY_RULE_VERSION,
                    outcome=outcome,
                    reason_codes=reason_codes,
                    details={"entity_count": entity_count, "failed": outcome == "failed"},
                )
            session.commit()
        return tuple(items)

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

    def _publish(
        self,
        candidates,
        operation_id: int,
        checkpoint: Callable[[str], None],
        *,
        relevance_by_item: dict[int, object],
        authority_by_item: dict[int, object],
        engagement_by_item: dict[int, dict[str, object]],
        now: datetime,
    ):
        event_ids: list[int] = []
        event_version_snapshots: dict[int, int] = {}
        created = 0
        publish_plans: list[tuple[CandidateCluster, EventScoreInput]] = []
        for candidate in candidates:
            # Persist/read the bounded candidate context first, then close the DB
            # transaction before optional HTTP work.  No event lease exists here.
            with self._session_factory() as session:
                EventRepository(session).upsert_candidate(
                    candidate, CLUSTER_RULE_VERSION
                )
                session.flush()
                existing = session.scalar(
                    select(EventRecord).where(EventRecord.canonical_key == candidate.candidate_key)
                )
                prior_event_exists, prior_evidence_roots = _prior_quality_state(
                    session, candidate, now
                )
                same_membership = existing is not None and self._has_same_membership(
                    session, existing.id, candidate.raw_item_ids
                )
                if same_membership:
                    assert existing is not None
                    event_ids.append(existing.id)
                    _capture_event_version(event_version_snapshots, existing)
                session.commit()
                if same_membership:
                    continue

            evidence = assess_evidence(candidate.items)
            score_input = build_score_input(
                candidate=candidate,
                evidence=evidence,
                relevance_by_item=relevance_by_item,
                authority_by_item=authority_by_item,
                engagement_by_item=engagement_by_item,
                now=now,
                prior_event_exists=prior_event_exists,
                prior_evidence_roots=prior_evidence_roots,
            )
            publish_plans.append((candidate, score_input))

        # Optional network work is complete before any publication transaction.
        checkpoint("before_event_enrichment")
        enrichment_results = self._enrich_candidates(
            tuple(candidate for candidate, _ in publish_plans),
            candidate_checkpoint=lambda _: checkpoint(
                "before_event_enrichment_candidate"
            ),
        )
        checkpoint("after_event_enrichment")
        model_success_count = sum(
            result.enrichment.origin == "model"
            for result in enrichment_results.values()
        )
        model_fallback_count = len(enrichment_results) - model_success_count
        model_error_counts: Counter[str] = Counter()
        for result in enrichment_results.values():
            for model_run in result.model_runs:
                error = model_run.usage.error
                if isinstance(error, str) and fullmatch(r"[a-z][a-z0-9_]{0,63}", error):
                    model_error_counts[error] += 1

        for candidate, score_input in publish_plans:
            checkpoint("before_event_publish_candidate")
            enrichment_result = enrichment_results[candidate.candidate_key]
            with self._session_factory() as session:
                repository = EventRepository(session)
                existing = session.scalar(
                    select(EventRecord).where(EventRecord.canonical_key == candidate.candidate_key)
                )
                if existing is not None and self._has_same_membership(
                    session, existing.id, candidate.raw_item_ids
                ):
                    self._record_model_runs(
                        repository, existing.id, enrichment_result.model_runs
                    )
                    event_ids.append(existing.id)
                    _capture_event_version(event_version_snapshots, existing)
                    session.commit()
                    continue
                claimed_event_id: int | None = None
                if existing is not None:
                    claimed_event_id = existing.id
                    if not repository.claim_event(
                        existing.id, operation_id, datetime.now(UTC) + timedelta(minutes=5)
                    ):
                        raise EventPublicationConflict(
                            "Event publication lease is held by another Operation"
                        )
                    # The pre-enrichment membership read may now be stale.  Re-read
                    # only after this operation owns the lease, and close a
                    # same-snapshot race without creating another event version.
                    if self._has_same_membership(
                        session, existing.id, candidate.raw_item_ids
                    ):
                        self._record_model_runs(
                            repository, existing.id, enrichment_result.model_runs
                        )
                        repository.release_event(existing.id, operation_id)
                        event_ids.append(existing.id)
                        _capture_event_version(event_version_snapshots, existing)
                        session.commit()
                        continue
                published = EventPublisher(repository).publish_snapshot(
                    candidate,
                    operation_id,
                    score_input=score_input,
                    enrichment=enrichment_result.enrichment,
                    model_usages=tuple(
                        model_run.usage
                        for model_run in enrichment_result.model_runs
                    ),
                )
                if claimed_event_id is not None:
                    repository.release_event(claimed_event_id, operation_id)
                assert published.event_id is not None
                event_ids.append(published.event_id)
                published_record = session.get(EventRecord, published.event_id)
                assert published_record is not None
                _capture_event_version(event_version_snapshots, published_record)
                created += int(repository.last_publish_created_version is True)
                session.commit()
        return (
            event_ids,
            tuple(sorted(event_version_snapshots.items())),
            created,
            model_success_count,
            model_fallback_count,
            dict(sorted(model_error_counts.items())),
        )

    @staticmethod
    def _record_model_runs(
        repository: EventRepository,
        event_id: int,
        model_runs: tuple[EventModelRun, ...],
    ) -> None:
        try:
            with repository.session.begin_nested():
                for model_run in model_runs:
                    repository.record_model_run(event_id, model_run.usage)
        except Exception as error:
            raise EventModelAuditError(
                "Model attempt audit could not be linked to the published event"
            ) from error

    @staticmethod
    def _enrich_candidates(
        candidates: tuple[CandidateCluster, ...],
        *,
        candidate_checkpoint: Callable[[CandidateCluster], None] | None = None,
    ) -> dict[str, EventEnrichmentResult]:
        settings = get_settings()

        async def run():
            import httpx

            async with httpx.AsyncClient() as http:
                async def adapter(candidate, fallback):
                    return await EventPipeline._enrich_candidate_async(
                        candidate, fallback, settings, http
                    )

                return await EventEnrichmentBatch(
                    adapter=adapter,
                    max_concurrency=settings.event_model_max_concurrency,
                    fallback_model=settings.minimax_fast_model,
                    candidate_checkpoint=candidate_checkpoint,
                ).enrich(candidates)

        return asyncio.run(run())

    @staticmethod
    async def _enrich_candidate_async(
        candidate: CandidateCluster,
        fallback,
        settings,
        http,
    ) -> EventEnrichmentResult:
        """Run one cancellable model request without crossing a thread boundary."""
        runs: list[EventModelRun] = []
        if not settings.minimax_api_key:
            usage = ModelUsage(
                purpose="event_enrichment",
                model=settings.minimax_fast_model,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                outcome="fallback",
                error="no_api_key",
            )
            return EventEnrichmentResult(
                enrichment=fallback,
                model_runs=(EventModelRun(stage=usage.purpose, usage=usage),),
            )
        try:
            enrichment = await EventMiniMaxAdapter(
                settings, http, runs.append
            ).enrich_event(candidate, fallback)
        except Exception:
            if not runs:
                usage = ModelUsage(
                    purpose="event_enrichment",
                    model=settings.minimax_fast_model,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0,
                    outcome="fallback",
                    error="unexpected_error",
                )
                runs.append(EventModelRun(stage=usage.purpose, usage=usage))
            enrichment = fallback
        return EventEnrichmentResult(enrichment=enrichment, model_runs=tuple(runs))

    @staticmethod
    def _enrich(candidate):
        """Call MiniMax only in the Worker pipeline; hard fallback remains publishable."""
        fallback = rule_enrichment(candidate)
        settings = get_settings()
        async def run():
            import httpx

            async with httpx.AsyncClient() as http:
                return await EventPipeline._enrich_candidate_async(
                    candidate, fallback, settings, http
                )

        result = asyncio.run(run())
        return result.enrichment, result.model_runs

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


def load_operation_window_end(
    session: Session,
    operation_id: int,
    *,
    checkpoint: Callable[[str], None] | None = None,
) -> datetime:
    """Resolve the immutable clock snapshot owned by a durable operation."""
    row = session.execute(
        select(
            OperationRunRecord.requested_scope,
            OperationRunRecord.created_at,
        ).where(OperationRunRecord.id == operation_id)
    ).one_or_none()
    if row is None:
        raise LookupError(f"operation {operation_id} does not exist")
    scope, created_at = row
    if isinstance(scope, dict) and isinstance(scope.get("window_end"), str):
        try:
            window_end = datetime.fromisoformat(scope["window_end"])
        except ValueError:
            pass
        else:
            return _as_utc(window_end)
    if checkpoint is not None:
        checkpoint("operation_window_end_fallback")
    return _as_utc(created_at)


def build_candidate_score_input(
    session: Session,
    candidate: CandidateCluster,
    *,
    now: datetime,
    prior_event: EventRecord | None = None,
) -> EventScoreInput:
    """Rebuild score-v2 inputs from persisted facts for one candidate snapshot."""
    member_ids = candidate.raw_item_ids
    relevance_by_item = dict(
        session.execute(
            select(
                RawItemProcessingRecord.raw_item_id,
                RawItemProcessingRecord.score,
            ).where(
                RawItemProcessingRecord.raw_item_id.in_(member_ids),
                RawItemProcessingRecord.stage == ProcessingStage.RELEVANCE.value,
                RawItemProcessingRecord.algorithm_version == RELEVANCE_RULE_VERSION,
                RawItemProcessingRecord.outcome == "included",
            )
        ).all()
    )
    quality_rows = session.execute(
        select(
            RawItemRecord.id,
            RawItemRecord.engagement,
            SourceDefinitionRecord.authority_score,
        )
        .join(
            SourceDefinitionRecord,
            SourceDefinitionRecord.id == RawItemRecord.source_id,
        )
        .where(RawItemRecord.id.in_(member_ids))
    ).all()
    authority_by_item = {
        raw_item_id: authority for raw_item_id, _, authority in quality_rows
    }
    engagement_by_item = {
        raw_item_id: _bounded_engagement(engagement)
        for raw_item_id, engagement, _ in quality_rows
    }
    if prior_event is None:
        prior_event_exists, prior_evidence_roots = _prior_quality_state(
            session, candidate, now
        )
    else:
        prior_event_exists = True
        prior_evidence_roots = _prior_evidence_roots(session, prior_event)
    evidence = assess_evidence(candidate.items)
    return build_score_input(
        candidate=candidate,
        evidence=evidence,
        relevance_by_item=relevance_by_item,
        authority_by_item=authority_by_item,
        engagement_by_item=engagement_by_item,
        now=now,
        prior_event_exists=prior_event_exists,
        prior_evidence_roots=prior_evidence_roots,
    )


def _bounded_values(
    values: object, *, max_count: int = 20, max_chars: int = SOURCE_TOPIC_MAX_CHARS
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(
        value[:max_chars]
        for value in values[:max_count]
        if isinstance(value, str) and value
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bounded_engagement(values: object, *, max_count: int = 20) -> dict[str, object]:
    return filter_engagement_fields(values, max_count=max_count)


def _prior_evidence_roots(
    session: Session, event: EventRecord | None
) -> frozenset[str]:
    if event is None or event.current_version_number <= 0:
        return frozenset()
    version = session.scalar(
        select(EventVersionRecord).where(
            EventVersionRecord.event_id == event.id,
            EventVersionRecord.version_number == event.current_version_number,
        )
    )
    if version is None or not isinstance(version.payload, dict):
        return frozenset()
    evidence = version.payload.get("evidence")
    if not isinstance(evidence, list):
        return frozenset()
    return frozenset(
        root
        for row in evidence
        if isinstance(row, dict)
        and row.get("independent") is True
        and isinstance((root := row.get("root_evidence_key")), str)
        and root
    )


def _prior_quality_state(
    session: Session,
    candidate,
    now: datetime,
) -> tuple[bool, frozenset[str] | None]:
    core_identity = candidate.metadata.get("_core_identity")
    if not isinstance(core_identity, str) or not core_identity:
        return False, None
    cutoff = now - timedelta(days=30)
    event_time = func.coalesce(EventRecord.occurred_at, EventRecord.updated_at)
    events = tuple(
        session.scalars(
            select(EventRecord)
            .join(
                EventCandidateRecord,
                EventCandidateRecord.candidate_key == EventRecord.canonical_key,
            )
            .where(
                EventCandidateRecord.algorithm_version == CLUSTER_RULE_VERSION,
                EventCandidateRecord.metadata_json["_core_identity"].as_string()
                == core_identity,
                EventRecord.visibility == "current",
                event_time >= cutoff,
                event_time <= now,
            )
            .order_by(EventRecord.id)
        )
    )
    if not events:
        return False, frozenset()
    roots: set[str] = set()
    for event in events:
        roots.update(_prior_evidence_roots(session, event))
    return True, frozenset(roots)


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
