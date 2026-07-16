from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import EventMergeCandidateRecord
from newsradar.event_merges.schema import (
    MergeCandidateDraft,
    MergeCandidateStatus,
    MergeCandidateType,
)

_ALLOWED_TRANSITIONS = {
    "pending": {"confirmed", "dismissed", "applied", "expired", "failed"},
    "confirmed": {"applied", "expired", "failed"},
    "dismissed": set(),
    "applied": set(),
    "expired": set(),
    "failed": set(),
}


class EventMergeCandidateRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_candidate(
        self, draft: MergeCandidateDraft, generated_operation_id: int
    ) -> EventMergeCandidateRecord:
        now = datetime.now(UTC)
        values = {
            "left_event_id": draft.left.event_id,
            "left_version_number": draft.left.version_number,
            "right_event_id": draft.right.event_id,
            "right_version_number": draft.right.version_number,
            "candidate_type": draft.candidate_type.value,
            "status": MergeCandidateStatus.PENDING.value,
            "algorithm_version": draft.algorithm_version,
            "input_fingerprint": draft.input_fingerprint,
            "facts_snapshot": {
                "left": draft.left.model_dump(mode="json"),
                "right": draft.right.model_dump(mode="json"),
            },
            "reason_codes": list(draft.reason_codes),
            "zh_reason": draft.zh_reason,
            "zh_next_action": draft.zh_next_action,
            "generated_operation_id": generated_operation_id,
            "result_summary": {},
            "created_at": now,
            "updated_at": now,
        }
        self.session.execute(
            self._insert(EventMergeCandidateRecord)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=[
                    "left_event_id",
                    "left_version_number",
                    "right_event_id",
                    "right_version_number",
                    "algorithm_version",
                    "input_fingerprint",
                ]
            )
        )
        record = self.session.scalar(self._unique_statement(draft))
        assert record is not None
        return record

    def get(
        self, candidate_id: int, *, for_update: bool = False
    ) -> EventMergeCandidateRecord | None:
        statement = select(EventMergeCandidateRecord).where(
            EventMergeCandidateRecord.id == candidate_id
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def mark_reviewed(
        self,
        candidate_id: int,
        status: MergeCandidateStatus,
        operation_id: int,
    ) -> EventMergeCandidateRecord:
        if status not in {MergeCandidateStatus.CONFIRMED, MergeCandidateStatus.DISMISSED}:
            raise ValueError("event_merge_invalid_transition")
        record = self._require_locked(candidate_id)
        self._set_status(record, status)
        record.reviewed_operation_id = operation_id
        record.reviewed_at = datetime.now(UTC)
        return record

    def mark_expired(
        self, candidate_id: int, reason_code: str
    ) -> EventMergeCandidateRecord:
        record = self._require_locked(candidate_id)
        self._set_status(record, MergeCandidateStatus.EXPIRED)
        if reason_code not in record.reason_codes:
            record.reason_codes = [*record.reason_codes, reason_code]
        return record

    def mark_applied(
        self,
        candidate_id: int,
        operation_id: int,
        result: dict[str, object],
    ) -> EventMergeCandidateRecord:
        record = self._require_locked(candidate_id)
        if (
            record.candidate_type == MergeCandidateType.MANUAL_REVIEW.value
            and record.status == MergeCandidateStatus.PENDING.value
        ):
            raise ValueError("event_merge_invalid_transition")
        self._set_status(record, MergeCandidateStatus.APPLIED)
        record.applied_operation_id = operation_id
        record.result_summary = dict(result)
        return record

    def _unique_statement(self, draft: MergeCandidateDraft):
        return select(EventMergeCandidateRecord).where(
            EventMergeCandidateRecord.left_event_id == draft.left.event_id,
            EventMergeCandidateRecord.left_version_number == draft.left.version_number,
            EventMergeCandidateRecord.right_event_id == draft.right.event_id,
            EventMergeCandidateRecord.right_version_number == draft.right.version_number,
            EventMergeCandidateRecord.algorithm_version == draft.algorithm_version,
            EventMergeCandidateRecord.input_fingerprint == draft.input_fingerprint,
        )

    def _require_locked(self, candidate_id: int) -> EventMergeCandidateRecord:
        record = self.get(candidate_id, for_update=True)
        if record is None:
            raise LookupError(f"event_merge_candidate_not_found:{candidate_id}")
        return record

    @staticmethod
    def _set_status(
        record: EventMergeCandidateRecord, status: MergeCandidateStatus
    ) -> None:
        if status.value not in _ALLOWED_TRANSITIONS[record.status]:
            raise ValueError("event_merge_invalid_transition")
        record.status = status.value
        record.updated_at = datetime.now(UTC)

    def _insert(self, record_type):
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        elif dialect_name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            raise ValueError(f"Unsupported event merge repository dialect: {dialect_name}")
        return insert(record_type)
