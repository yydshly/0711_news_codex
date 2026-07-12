from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    EventCandidateItemRecord,
    EventCandidateRecord,
    EventItemRecord,
    EventModelRunRecord,
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
    EventCategory,
    ProcessingStage,
    PublishedEvent,
)


class EventRepository:
    """Small transactional operations for durable event processing state."""

    def __init__(self, session: Session):
        self.session = session

    def record_stage(
        self, raw_item_id: int, stage: ProcessingStage, algorithm_version: str
    ) -> RawItemProcessingRecord:
        now = datetime.now(UTC)
        self.session.execute(
            self._insert(RawItemProcessingRecord)
            .values(
                raw_item_id=raw_item_id,
                stage=stage.value,
                algorithm_version=algorithm_version,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["raw_item_id", "stage", "algorithm_version"])
        )
        record = self.session.scalar(
            select(RawItemProcessingRecord).where(
                RawItemProcessingRecord.raw_item_id == raw_item_id,
                RawItemProcessingRecord.stage == stage.value,
                RawItemProcessingRecord.algorithm_version == algorithm_version,
            )
        )
        assert record is not None
        return record

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

    def publish_complete_event(self, event: PublishedEvent, operation_id: int) -> EventRecord:
        """Write a complete version before exposing it through the current-version pointer."""
        # Reservation is handled by the worker; this is the short write transaction.
        del operation_id
        now = datetime.now(UTC)
        with self.session.begin_nested():
            record = self.session.scalar(
                select(EventRecord)
                .where(EventRecord.canonical_key == event.canonical_key)
                .with_for_update()
            )
            if record is None:
                record = EventRecord(
                    canonical_key=event.canonical_key,
                    status=event.status.value,
                    category=event.category.value if event.category else None,
                    occurred_at=event.occurred_at,
                    current_version_number=0,
                    created_at=now,
                    updated_at=now,
                )
                self.session.add(record)
                self.session.flush()

            next_version = record.current_version_number + 1
            version = EventVersionRecord(
                event_id=record.id,
                version_number=next_version,
                payload=event.model_dump(mode="json"),
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
                )
            )
            self.session.flush()
            self.before_current_version_switch(record, version)
            record.status = event.status.value
            record.category = event.category.value if event.category else None
            record.occurred_at = event.occurred_at
            record.current_version_number = next_version
            record.updated_at = now
            self.session.flush()
        return record

    def record_model_run(self, event_id: int, usage: ModelUsage) -> None:
        """Best-effort caller boundary: this short write never affects publication."""
        model_usage = ModelUsageRecord(
            purpose=usage.purpose,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            outcome=usage.outcome,
            error=usage.error[:1000] if usage.error else None,
        )
        self.session.add(model_usage)
        self.session.flush()
        self.session.add(
            EventModelRunRecord(
                event_id=event_id,
                model_usage_id=model_usage.id,
                stage=usage.purpose,
                algorithm_version=usage.model,
            )
        )

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
