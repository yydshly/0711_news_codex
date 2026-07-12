from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from newsradar.db.models import (
    EventCandidateItemRecord,
    EventCandidateRecord,
    EventItemRecord,
    EventRecord,
    EventVersionRecord,
    RawItemProcessingRecord,
)
from newsradar.events.schema import CandidateCluster, ProcessingStage, PublishedEvent


class EventRepository:
    """Small transactional operations for durable event processing state."""

    def __init__(self, session: Session):
        self.session = session

    def record_stage(
        self, raw_item_id: int, stage: ProcessingStage, algorithm_version: str
    ) -> RawItemProcessingRecord:
        record = self.session.scalar(
            select(RawItemProcessingRecord).where(
                RawItemProcessingRecord.raw_item_id == raw_item_id,
                RawItemProcessingRecord.stage == stage.value,
                RawItemProcessingRecord.algorithm_version == algorithm_version,
            )
        )
        if record is None:
            record = RawItemProcessingRecord(
                raw_item_id=raw_item_id, stage=stage.value, algorithm_version=algorithm_version
            )
            self.session.add(record)
            self.session.flush()
        return record

    def upsert_candidate(
        self, candidate: CandidateCluster, algorithm_version: str
    ) -> EventCandidateRecord:
        record = self.session.scalar(
            select(EventCandidateRecord).where(
                EventCandidateRecord.candidate_key == candidate.candidate_key,
                EventCandidateRecord.algorithm_version == algorithm_version,
            )
        )
        if record is None:
            record = EventCandidateRecord(
                candidate_key=candidate.candidate_key,
                algorithm_version=algorithm_version,
                title=candidate.title,
                category=candidate.category.value if candidate.category else None,
                state=candidate.state,
                metadata_json=candidate.metadata,
            )
            self.session.add(record)
            self.session.flush()
        else:
            record.title = candidate.title
            record.category = candidate.category.value if candidate.category else None
            record.state = candidate.state
            record.metadata_json = candidate.metadata
        return record

    def replace_candidate_items(self, candidate_id: int, raw_item_ids: tuple[int, ...]) -> None:
        self.session.query(EventCandidateItemRecord).filter_by(candidate_id=candidate_id).delete()
        self.session.add_all(
            EventCandidateItemRecord(candidate_id=candidate_id, raw_item_id=raw_item_id)
            for raw_item_id in sorted(set(raw_item_ids))
        )
        self.session.flush()

    def create_or_update_event(self, event: PublishedEvent) -> EventRecord:
        record = self.session.get(EventRecord, event.event_id) if event.event_id else None
        if record is None:
            record = self.session.scalar(
                select(EventRecord).where(EventRecord.canonical_key == event.canonical_key)
            )
        if record is None:
            record = EventRecord(canonical_key=event.canonical_key, status=event.status.value)
            self.session.add(record)
            self.session.flush()
        record.status = event.status.value
        record.category = event.category.value if event.category else None
        record.occurred_at = event.occurred_at
        return record

    def publish_version(self, event_id: int, version: PublishedEvent) -> EventVersionRecord:
        next_version = (
            self.session.scalar(
                select(EventVersionRecord.version_number)
                .where(EventVersionRecord.event_id == event_id)
                .order_by(EventVersionRecord.version_number.desc())
                .limit(1)
            )
            or 0
        ) + 1
        record = EventVersionRecord(
            event_id=event_id,
            version_number=next_version,
            payload=version.model_dump(mode="json"),
            zh_title=version.enrichment.zh_title if version.enrichment else None,
            zh_summary=version.enrichment.zh_summary if version.enrichment else None,
        )
        self.session.add(record)
        for raw_item_id in version.source_item_ids:
            self.session.add(
                EventItemRecord(
                    event_id=event_id, raw_item_id=raw_item_id, added_version_number=next_version
                )
            )
        self.session.flush()
        return record

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
            .values(lease_operation_id=operation_id, lease_expires_at=lease_until)
        )

    def claim_event(self, event_id: int, operation_id: int, lease_until: datetime) -> bool:
        result = self.session.execute(self._claim_statement(event_id, operation_id, lease_until))
        return result.rowcount == 1

    def release_event(self, event_id: int, operation_id: int) -> bool:
        result = self.session.execute(
            update(EventRecord)
            .where(and_(EventRecord.id == event_id, EventRecord.lease_operation_id == operation_id))
            .values(lease_operation_id=None, lease_expires_at=None)
        )
        return result.rowcount == 1
