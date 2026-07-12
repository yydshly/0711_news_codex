from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
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
        now = datetime.now(UTC)
        self.session.execute(
            self._insert(RawItemProcessingRecord)
            .values(
                raw_item_id=raw_item_id,
                stage=stage.value,
                algorithm_version=algorithm_version,
                created_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["raw_item_id", "stage", "algorithm_version"]
            )
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
        values = {
            EventCandidateRecord.title: candidate.title,
            EventCandidateRecord.category: candidate.category.value if candidate.category else None,
            EventCandidateRecord.state: candidate.state,
            EventCandidateRecord.metadata_json: candidate.metadata,
            EventCandidateRecord.updated_at: now,
        }
        self.session.execute(
            self._insert(EventCandidateRecord)
            .values({
                EventCandidateRecord.candidate_key: candidate.candidate_key,
                EventCandidateRecord.algorithm_version: algorithm_version,
                EventCandidateRecord.created_at: now,
                **values,
            })
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

    def publish_version(self, event_id: int, version: PublishedEvent) -> EventVersionRecord:
        self.session.scalar(select(EventRecord).where(EventRecord.id == event_id).with_for_update())
        for _ in range(3):
            next_version = (
                self.session.scalar(
                    select(func.max(EventVersionRecord.version_number)).where(
                        EventVersionRecord.event_id == event_id
                    )
                )
                or 0
            ) + 1
            try:
                with self.session.begin_nested():
                    record = EventVersionRecord(
                        event_id=event_id,
                        version_number=next_version,
                        payload=version.model_dump(mode="json"),
                        zh_title=version.enrichment.zh_title if version.enrichment else None,
                        zh_summary=version.enrichment.zh_summary if version.enrichment else None,
                    )
                    self.session.add(record)
                    active_items = self.session.scalars(
                        select(EventItemRecord).where(
                            EventItemRecord.event_id == event_id,
                            EventItemRecord.removed_version_number.is_(None),
                        )
                    ).all()
                    source_item_ids = set(version.source_item_ids)
                    active_ids = {item.raw_item_id for item in active_items}
                    for item in active_items:
                        if item.raw_item_id not in source_item_ids:
                            item.removed_version_number = next_version
                    for raw_item_id in source_item_ids - active_ids:
                        self.session.add(
                            EventItemRecord(
                                event_id=event_id,
                                raw_item_id=raw_item_id,
                                added_version_number=next_version,
                            )
                        )
                    self.session.flush()
                self.session.execute(
                    update(EventRecord)
                    .where(EventRecord.id == event_id)
                    .values(updated_at=datetime.now(UTC))
                )
                return record
            except IntegrityError:
                continue
        raise RuntimeError("could not allocate an event version after three attempts")

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
                "Unsupported event repository dialect: " f"{self.session.bind.dialect.name}"
            )

        return insert(record_type)
