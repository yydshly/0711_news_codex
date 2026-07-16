from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from math import isfinite

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    EventCandidateItemRecord,
    EventCandidateRecord,
    EventItemRecord,
    EventModelRunRecord,
    EventPairDecisionRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    ModelUsageRecord,
    RawItemProcessingRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.schema import (
    CandidateCluster,
    ClusterItem,
    EntityType,
    EventCategory,
    EventStatus,
    EventVisibility,
    EvidenceRole,
    NewsworthinessDecision,
    ProcessingStage,
    PublishedEvent,
    RelevanceDecision,
)
from newsradar.events.trends import HeatSnapshot


class EventPublicationConflict(RuntimeError):
    """A concurrent event write changed the canonical snapshot; retry safely."""

    error_code = "event_publication_conflict"
    retryable = True


class EventModelAuditError(RuntimeError):
    """Model attempt metadata could not be durably linked to its event."""

    error_code = "event_model_audit_failed"
    retryable = True


class EventRepository:
    """Small transactional operations for durable event processing state."""

    def __init__(self, session: Session):
        self.session = session
        self.last_publish_created_version: bool | None = None

    def record_stage(
        self,
        raw_item_id: int,
        stage: ProcessingStage,
        algorithm_version: str,
        *,
        outcome: str | None = None,
        score: int | None = None,
        reason_codes: tuple[str, ...] = (),
        details: dict[str, object] | None = None,
    ) -> RawItemProcessingRecord:
        now = datetime.now(UTC)
        decision_values = {
            "outcome": outcome,
            "score": score,
            "reason_codes": list(reason_codes),
            "details": _normalize_processing_details(details),
        }
        self.session.execute(
            self._insert(RawItemProcessingRecord)
            .values(
                raw_item_id=raw_item_id,
                stage=stage.value,
                algorithm_version=algorithm_version,
                created_at=now,
                **decision_values,
            )
            .on_conflict_do_update(
                index_elements=["raw_item_id", "stage", "algorithm_version"],
                set_=decision_values,
            )
        )
        record = self.session.scalar(
            select(RawItemProcessingRecord)
            .where(
                RawItemProcessingRecord.raw_item_id == raw_item_id,
                RawItemProcessingRecord.stage == stage.value,
                RawItemProcessingRecord.algorithm_version == algorithm_version,
            )
            .execution_options(populate_existing=True)
        )
        assert record is not None
        return record

    def record_relevance_decisions(
        self,
        decisions: tuple[tuple[int, RelevanceDecision], ...],
        algorithm_version: str,
    ) -> None:
        """Bulk-upsert a complete relevance selection in one short transaction."""
        if not decisions:
            return
        now = datetime.now(UTC)
        rows = [
            {
                "raw_item_id": raw_item_id,
                "stage": ProcessingStage.RELEVANCE.value,
                "algorithm_version": algorithm_version,
                "outcome": decision.outcome,
                "score": decision.score,
                "reason_codes": list(decision.reasons),
                "details": {"threshold": 60},
                "created_at": now,
            }
            for raw_item_id, decision in decisions
        ]
        statement = self._insert(RawItemProcessingRecord).values(rows)
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["raw_item_id", "stage", "algorithm_version"],
                set_={
                    "outcome": statement.excluded.outcome,
                    "score": statement.excluded.score,
                    "reason_codes": statement.excluded.reason_codes,
                    "details": statement.excluded.details,
                },
            )
        )

    def upsert_candidate(
        self, candidate: CandidateCluster, algorithm_version: str
    ) -> EventCandidateRecord:
        now = datetime.now(UTC)
        metadata = dict(candidate.metadata)
        metadata["_candidate_reasons"] = list(candidate.reasons)
        values = {
            EventCandidateRecord.title: candidate.title,
            EventCandidateRecord.category: candidate.category.value if candidate.category else None,
            EventCandidateRecord.state: candidate.state,
            EventCandidateRecord.metadata_json: metadata,
            EventCandidateRecord.updated_at: now,
        }
        self.session.execute(
            self._insert(EventCandidateRecord)
            .values(
                {
                    EventCandidateRecord.candidate_key: candidate.candidate_key,
                    EventCandidateRecord.algorithm_version: algorithm_version,
                    EventCandidateRecord.created_at: now,
                    **values,
                }
            )
            .on_conflict_do_update(
                index_elements=["candidate_key", "algorithm_version"], set_=values
            )
        )
        record = self.session.scalar(
            select(EventCandidateRecord).where(
                EventCandidateRecord.candidate_key == candidate.candidate_key,
                EventCandidateRecord.algorithm_version == algorithm_version,
            )
        )
        assert record is not None
        return record

    def replace_candidate_items(self, candidate_id: int, raw_item_ids: tuple[int, ...]) -> None:
        self.session.query(EventCandidateItemRecord).filter_by(candidate_id=candidate_id).delete()
        self.session.add_all(
            EventCandidateItemRecord(candidate_id=candidate_id, raw_item_id=raw_item_id)
            for raw_item_id in sorted(set(raw_item_ids))
        )
        self.session.execute(
            update(EventCandidateRecord)
            .where(EventCandidateRecord.id == candidate_id)
            .values(updated_at=datetime.now(UTC))
        )
        self.session.flush()

    def create_or_update_event(self, event: PublishedEvent) -> EventRecord:
        now = datetime.now(UTC)
        values = {
            "status": event.status.value,
            "category": event.category.value if event.category else None,
            "occurred_at": event.occurred_at,
            "updated_at": now,
        }
        if event.event_id is not None:
            self.session.execute(
                update(EventRecord).where(EventRecord.id == event.event_id).values(**values)
            )
            record = self.session.get(EventRecord, event.event_id)
        else:
            self.session.execute(
                self._insert(EventRecord)
                .values(canonical_key=event.canonical_key, created_at=now, **values)
                .on_conflict_do_update(index_elements=["canonical_key"], set_=values)
            )
            record = self.session.scalar(
                select(EventRecord).where(EventRecord.canonical_key == event.canonical_key)
            )
        assert record is not None
        return record

    def get_candidate_for_publication(
        self, candidate_id: int
    ) -> tuple[CandidateCluster, tuple[int, ...]]:
        record = self.session.get(EventCandidateRecord, candidate_id)
        if record is None:
            raise LookupError(f"event candidate {candidate_id} does not exist")
        rows = self.session.execute(
            select(RawItemRecord, SourceDefinitionRecord)
            .join(SourceDefinitionRecord, SourceDefinitionRecord.id == RawItemRecord.source_id)
            .join(
                EventCandidateItemRecord,
                EventCandidateItemRecord.raw_item_id == RawItemRecord.id,
            )
            .where(EventCandidateItemRecord.candidate_id == candidate_id)
            .order_by(RawItemRecord.id)
        ).all()
        items = tuple(
            ClusterItem(
                raw_item_id=item.id,
                title=item.title or "",
                canonical_url=item.canonical_url,
                original_url=item.original_url,
                title_fingerprint=item.title_fingerprint,
                published_at=item.published_at,
                source_nature=source.nature,
                source_roles=tuple(source.roles),
                publisher_name=item.publisher_name or source.name,
            )
            for item, source in rows
        )
        raw_item_ids = tuple(item.raw_item_id for item in items)
        return (
            CandidateCluster(
                candidate_key=record.candidate_key,
                title=record.title,
                category=EventCategory(record.category) if record.category else None,
                items=items,
                raw_item_ids=raw_item_ids,
                reasons=tuple(record.metadata_json.get("_candidate_reasons", ())),
                state=record.state,
                metadata=record.metadata_json,
                occurred_at=min(
                    (item.published_at for item in items if item.published_at is not None),
                    default=datetime(1970, 1, 1, tzinfo=UTC),
                ),
            ),
            raw_item_ids,
        )

    def get_current_event(self, event_id: int) -> EventVersionRecord | None:
        return self.session.scalar(
            select(EventVersionRecord)
            .join(EventRecord, EventRecord.id == EventVersionRecord.event_id)
            .where(
                EventRecord.id == event_id,
                EventVersionRecord.version_number == EventRecord.current_version_number,
            )
        )

    def heat_history(
        self, canonical_key: str, *, before: datetime
    ) -> tuple[HeatSnapshot, ...]:
        """Read one event's immutable logical score snapshots before a window end.

        ``created_at`` is a database-write audit timestamp and can lag a retried
        operation.  Legacy scores have no logical observation time, so only those
        records fall back to ``created_at``.
        """
        event = self.session.scalar(
            select(EventRecord).where(EventRecord.canonical_key == canonical_key)
        )
        if event is None:
            return ()
        observed_at = func.coalesce(EventScoreRecord.observed_at, EventScoreRecord.created_at)
        rows = self.session.scalars(
            select(EventScoreRecord)
            .where(
                EventScoreRecord.event_id == event.id,
                observed_at <= before,
            )
            .order_by(observed_at, EventScoreRecord.id)
        )
        return tuple(
            HeatSnapshot(
                observed_at=row.observed_at or row.created_at,
                heat=round(row.heat),
            )
            for row in rows
        )

    def publish_complete_event(
        self,
        event: PublishedEvent,
        operation_id: int,
        *,
        model_usages: tuple[ModelUsage, ...] = (),
        visibility: EventVisibility = EventVisibility.CURRENT,
    ) -> EventRecord:
        """Write a complete version before exposing it through the current-version pointer."""
        # Reservation is handled by the worker; this is the short write transaction.
        del operation_id
        self.last_publish_created_version = None
        now = datetime.now(UTC)
        with self.session.begin_nested():
            record = self.session.scalar(
                select(EventRecord)
                .where(EventRecord.canonical_key == event.canonical_key)
                .with_for_update()
            )
            if record is None:
                try:
                    with self.session.begin_nested():
                        record = EventRecord(
                            canonical_key=event.canonical_key,
                            visibility=EventVisibility.CURRENT.value,
                            status=event.status.value,
                            category=event.category.value if event.category else None,
                            occurred_at=event.occurred_at,
                            current_version_number=0,
                            created_at=now,
                            updated_at=now,
                        )
                        self.session.add(record)
                        self.session.flush()
                except IntegrityError as error:
                    if not _is_event_canonical_collision(error):
                        raise
                    record = self.session.scalar(
                        select(EventRecord)
                        .where(EventRecord.canonical_key == event.canonical_key)
                        .with_for_update()
                    )
                    if record is None:
                        raise EventPublicationConflict(
                            "Concurrent canonical event creation could not be resolved"
                        ) from error
                    if (
                        record.current_version_number > 0
                        and self._has_same_active_membership(
                            record.id, event.source_item_ids
                        )
                    ):
                        try:
                            for usage in model_usages:
                                self.record_model_run(record.id, usage)
                        except Exception as audit_error:
                            raise EventModelAuditError(
                                "Model attempt audit could not be linked to the published event"
                            ) from audit_error
                        self.last_publish_created_version = False
                        return record
                    raise EventPublicationConflict(
                        "Concurrent canonical event publication changed the candidate snapshot"
                    ) from error

            next_version = record.current_version_number + 1
            version_payload = event.model_dump(mode="json")
            version_payload["publication"] = {
                "tier": event.display_tier.value,
                "rank_score": event.rank_score,
                "reasons": list(event.score.reasons) if event.score else [],
            }
            version_payload["model_runs"] = [
                _safe_model_run_summary(usage) for usage in model_usages
            ]
            version = EventVersionRecord(
                event_id=record.id,
                version_number=next_version,
                payload=version_payload,
                zh_title=event.enrichment.zh_title if event.enrichment else None,
                zh_summary=event.enrichment.zh_summary if event.enrichment else None,
            )
            self.session.add(version)
            self._replace_active_memberships(record.id, event.source_item_ids, next_version)
            assert event.score is not None
            self.session.add(
                EventScoreRecord(
                    event_id=record.id,
                    version_number=next_version,
                    heat=event.score.heat,
                    breakdown=event.score.model_dump(mode="json"),
                    observed_at=event.snapshot_at or now,
                )
            )
            try:
                for usage in model_usages:
                    self.record_model_run(record.id, usage)
            except Exception as error:
                raise EventModelAuditError(
                    "Model attempt audit could not be linked to the published event"
                ) from error
            self.session.flush()
            self.before_current_version_switch(record, version)
            record.status = event.status.value
            record.visibility = visibility.value
            record.category = event.category.value if event.category else None
            record.occurred_at = event.occurred_at
            record.display_tier = event.display_tier.value
            record.rank_score = event.rank_score
            record.current_version_number = next_version
            record.updated_at = now
            self.session.flush()
            self.last_publish_created_version = True
        return record

    def _has_same_active_membership(
        self, event_id: int, source_item_ids: tuple[int, ...]
    ) -> bool:
        active_ids = set(
            self.session.scalars(
                select(EventItemRecord.raw_item_id).where(
                    EventItemRecord.event_id == event_id,
                    EventItemRecord.removed_version_number.is_(None),
                )
            )
        )
        return active_ids == set(source_item_ids)

    def record_model_run(self, event_id: int, usage: ModelUsage) -> None:
        """Best-effort caller boundary: this short write never affects publication."""
        model_usage = self._add_model_usage(usage)
        self.session.add(
            EventModelRunRecord(
                event_id=event_id,
                model_usage_id=model_usage.id,
                stage=usage.purpose,
                algorithm_version=usage.model,
            )
        )

    def get_pair_decision(
        self,
        left_raw_item_id: int,
        right_raw_item_id: int,
        algorithm_version: str,
        input_fingerprint: str,
    ) -> EventPairDecisionRecord | None:
        left, right = sorted((left_raw_item_id, right_raw_item_id))
        return self.session.scalar(
            select(EventPairDecisionRecord).where(
                EventPairDecisionRecord.left_raw_item_id == left,
                EventPairDecisionRecord.right_raw_item_id == right,
                EventPairDecisionRecord.algorithm_version == algorithm_version,
                EventPairDecisionRecord.input_fingerprint == input_fingerprint,
            )
        )

    def record_pair_decision(
        self,
        left_raw_item_id: int,
        right_raw_item_id: int,
        algorithm_version: str,
        input_fingerprint: str,
        *,
        rule_score: float,
        rule_reasons: tuple[str, ...],
        model_same_event: bool | None,
        model_confidence: float | None,
        final_decision: str,
    ) -> EventPairDecisionRecord:
        left, right = sorted((left_raw_item_id, right_raw_item_id))
        if left == right:
            raise ValueError("pair decisions require two distinct RawItems")
        values = {
            "left_raw_item_id": left,
            "right_raw_item_id": right,
            "algorithm_version": algorithm_version,
            "input_fingerprint": input_fingerprint,
            "rule_score": rule_score,
            "rule_reasons": list(rule_reasons),
            "model_same_event": model_same_event,
            "model_confidence": model_confidence,
            "final_decision": final_decision,
            "created_at": datetime.now(UTC),
        }
        self.session.execute(
            self._insert(EventPairDecisionRecord)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=[
                    "left_raw_item_id",
                    "right_raw_item_id",
                    "algorithm_version",
                    "input_fingerprint",
                ]
            )
        )
        record = self.get_pair_decision(left, right, algorithm_version, input_fingerprint)
        assert record is not None
        return record

    def record_newsworthiness_decisions(
        self,
        decisions: tuple[tuple[int, NewsworthinessDecision], ...],
        algorithm_version: str,
    ) -> None:
        """Bulk-upsert newsworthiness outcomes for relevant raw items."""
        if not decisions:
            return
        now = datetime.now(UTC)
        rows = [
            {
                "raw_item_id": raw_item_id,
                "stage": ProcessingStage.NEWSWORTHINESS.value,
                "algorithm_version": algorithm_version,
                "outcome": decision.outcome,
                "score": decision.score,
                "reason_codes": list(decision.reason_codes),
                "details": {"action": decision.action},
                "created_at": now,
            }
            for raw_item_id, decision in decisions
        ]
        statement = self._insert(RawItemProcessingRecord).values(rows)
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["raw_item_id", "stage", "algorithm_version"],
                set_={
                    "outcome": statement.excluded.outcome,
                    "score": statement.excluded.score,
                    "reason_codes": statement.excluded.reason_codes,
                    "details": statement.excluded.details,
                },
            )
        )

    def record_pair_model_run(self, pair_decision_id: int, usage: ModelUsage) -> None:
        model_usage = self._add_model_usage(usage)
        self.session.add(
            EventModelRunRecord(
                pair_decision_id=pair_decision_id,
                model_usage_id=model_usage.id,
                stage=usage.purpose,
                algorithm_version=usage.model,
            )
        )

    def _add_model_usage(self, usage: ModelUsage) -> ModelUsageRecord:
        model_usage = ModelUsageRecord(
            purpose=usage.purpose,
            model=usage.model,
            input_tokens=max(0, usage.input_tokens),
            output_tokens=max(0, usage.output_tokens),
            latency_ms=usage.latency_ms,
            outcome=usage.outcome,
            error=usage.error[:1000] if usage.error else None,
        )
        self.session.add(model_usage)
        self.session.flush()
        return model_usage

    def before_current_version_switch(
        self, event: EventRecord, version: EventVersionRecord
    ) -> None:
        """Injection point for failure testing immediately before the visibility switch."""

    def _replace_active_memberships(
        self, event_id: int, source_item_ids: tuple[int, ...], version_number: int
    ) -> None:
        active_items = self.session.scalars(
            select(EventItemRecord).where(
                EventItemRecord.event_id == event_id,
                EventItemRecord.removed_version_number.is_(None),
            )
        ).all()
        source_ids = set(source_item_ids)
        active_ids = {item.raw_item_id for item in active_items}
        for item in active_items:
            if item.raw_item_id not in source_ids:
                item.removed_version_number = version_number
        self.session.add_all(
            EventItemRecord(
                event_id=event_id,
                raw_item_id=raw_item_id,
                added_version_number=version_number,
            )
            for raw_item_id in sorted(source_ids - active_ids)
        )

    def _claim_statement(self, event_id: int, operation_id: int, lease_until: datetime):
        return (
            update(EventRecord)
            .where(
                EventRecord.id == event_id,
                or_(
                    EventRecord.lease_expires_at.is_(None),
                    EventRecord.lease_expires_at <= datetime.now(UTC),
                ),
            )
            .values(
                lease_operation_id=operation_id,
                lease_expires_at=lease_until,
                updated_at=datetime.now(UTC),
            )
            .execution_options(synchronize_session=False)
        )

    def claim_event(self, event_id: int, operation_id: int, lease_until: datetime) -> bool:
        result = self.session.execute(self._claim_statement(event_id, operation_id, lease_until))
        return result.rowcount == 1

    def release_event(self, event_id: int, operation_id: int) -> bool:
        result = self.session.execute(
            update(EventRecord)
            .where(and_(EventRecord.id == event_id, EventRecord.lease_operation_id == operation_id))
            .values(
                lease_operation_id=None,
                lease_expires_at=None,
                updated_at=datetime.now(UTC),
            )
        )
        return result.rowcount == 1

    def _insert(self, record_type):
        assert self.session.bind is not None
        if self.session.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        elif self.session.bind.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            raise ValueError(
                f"Unsupported event repository dialect: {self.session.bind.dialect.name}"
            )

        return insert(record_type)


_STABLE_ENUM_VALUE = re.compile(r"[A-Za-z0-9_.:-]+")
_SENSITIVE_DETAIL_KEY_PATTERNS = (
    ("api", "key"),
    ("access", "token"),
    ("authorization",),
    ("session", "cookie"),
    ("client", "secret"),
    ("service", "credential"),
    ("db", "password"),
    ("request", "header"),
    ("request", "headers"),
    ("token",),
    ("cookie",),
    ("secret",),
    ("credential",),
    ("password",),
    ("header",),
    ("headers",),
)
_ALLOWED_DETAIL_ENUM_TYPES = (
    EventVisibility,
    EventStatus,
    ProcessingStage,
    EventCategory,
    EvidenceRole,
    EntityType,
)
_DETAILS_VALUE_ERROR = "details values must be booleans, numbers, or enum members"


def _safe_model_run_summary(usage: ModelUsage) -> dict[str, object]:
    latency = usage.latency_ms
    safe_latency = (
        float(latency)
        if isinstance(latency, (int, float)) and isfinite(latency) and latency >= 0
        else None
    )
    return {
        "model": str(usage.model)[:120],
        "purpose": str(usage.purpose)[:64],
        "outcome": str(usage.outcome)[:32],
        "latency_ms": safe_latency,
    }


def _normalize_processing_details(details: dict[str, object] | None) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in (details or {}).items():
        key_tokens = _detail_key_tokens(key)
        if any(
            len(key_tokens) >= len(pattern) and key_tokens[-len(pattern) :] == pattern
            for pattern in _SENSITIVE_DETAIL_KEY_PATTERNS
        ):
            raise ValueError(
                f"{_DETAILS_VALUE_ERROR}; sensitive field names are forbidden"
            )
        if isinstance(value, Enum):
            enum_value = value.value
            if isinstance(enum_value, float) and not isfinite(enum_value):
                raise ValueError("details values must use finite numbers")
            if not isinstance(value, _ALLOWED_DETAIL_ENUM_TYPES):
                raise ValueError("details enum members must use a project-defined stable enum")
            if isinstance(enum_value, str) and (
                len(enum_value) > 120 or _STABLE_ENUM_VALUE.fullmatch(enum_value) is None
            ):
                raise ValueError(_DETAILS_VALUE_ERROR)
            if not isinstance(enum_value, (str, bool, int, float)):
                raise ValueError(_DETAILS_VALUE_ERROR)
            normalized[key] = enum_value
        elif isinstance(value, (bool, int)):
            normalized[key] = value
        elif isinstance(value, float) and isfinite(value):
            normalized[key] = value
        else:
            raise ValueError(_DETAILS_VALUE_ERROR)
    return normalized


def _detail_key_tokens(key: str) -> tuple[str, ...]:
    separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", key)
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", separated)
    return tuple(re.findall(r"[a-z0-9]+", separated.casefold()))


def _is_event_canonical_collision(error: IntegrityError) -> bool:
    diagnostic = getattr(error.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == "events_canonical_key_key":
        return True
    return str(error.orig) == "UNIQUE constraint failed: events.canonical_key"
