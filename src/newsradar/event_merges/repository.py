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
        existing = self.session.scalar(self._chain_statement(draft))
        if existing is not None:
            return existing
        values = self._candidate_values(
            draft,
            generated_operation_id,
            revision=1,
            supersedes_candidate_id=None,
        )
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
                ],
                index_where=EventMergeCandidateRecord.supersedes_candidate_id.is_(
                    None
                ),
            )
        )
        record = self.session.scalar(self._chain_statement(draft))
        assert record is not None
        return record

    def resolve_recheck(
        self,
        parent_id: int,
        draft: MergeCandidateDraft | None,
        *,
        generated_operation_id: int,
        reason_code: str,
    ) -> EventMergeCandidateRecord:
        parent = self._require_locked(parent_id)
        if parent.status != MergeCandidateStatus.PENDING.value:
            return self._recheck_retry(parent, generated_operation_id)
        if draft is None:
            self.mark_expired(parent_id, reason_code)
            self._record_recheck(
                parent,
                generated_operation_id,
                outcome="no_candidate",
                replacement_id=None,
            )
            return parent
        if self._same_chain_identity(parent, draft):
            replacement = self.create_revision(
                parent_id,
                draft,
                generated_operation_id=generated_operation_id,
                reason_code=reason_code,
            )
            outcome = "revision"
        else:
            self.mark_expired(parent_id, reason_code)
            replacement = self.upsert_candidate(draft, generated_operation_id)
            outcome = "new_root"
        self._record_recheck(
            parent,
            generated_operation_id,
            outcome=outcome,
            replacement_id=replacement.id,
        )
        return replacement

    def create_revision(
        self,
        parent_id: int,
        draft: MergeCandidateDraft,
        *,
        generated_operation_id: int,
        reason_code: str,
    ) -> EventMergeCandidateRecord:
        parent = self._require_locked(parent_id)
        existing = self.child_of(parent_id, for_update=True)
        if existing is not None:
            return existing
        if parent.status != MergeCandidateStatus.PENDING.value:
            raise ValueError("event_merge_candidate_not_reviewable")
        if not self._same_chain_identity(parent, draft):
            raise ValueError("event_merge_revision_chain_changed")
        self.mark_expired(parent_id, reason_code)
        values = self._candidate_values(
            draft,
            generated_operation_id,
            revision=parent.revision + 1,
            supersedes_candidate_id=parent.id,
        )
        self.session.execute(
            self._insert(EventMergeCandidateRecord)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=["supersedes_candidate_id"]
            )
        )
        child = self.child_of(parent_id, for_update=True)
        assert child is not None
        return child

    @staticmethod
    def _same_chain_identity(
        parent: EventMergeCandidateRecord,
        draft: MergeCandidateDraft,
    ) -> bool:
        return (
            parent.left_event_id,
            parent.left_version_number,
            parent.right_event_id,
            parent.right_version_number,
            parent.algorithm_version,
        ) == (
            draft.left.event_id,
            draft.left.version_number,
            draft.right.event_id,
            draft.right.version_number,
            draft.algorithm_version,
        )

    def _recheck_retry(
        self,
        parent: EventMergeCandidateRecord,
        operation_id: int,
    ) -> EventMergeCandidateRecord:
        outcome = parent.result_summary.get("recheck_outcome")
        if (
            parent.status != MergeCandidateStatus.EXPIRED.value
            or parent.reviewed_operation_id != operation_id
            or outcome not in {"no_candidate", "revision", "new_root"}
        ):
            raise ValueError("event_merge_candidate_not_reviewable")
        replacement_id = parent.result_summary.get("recheck_candidate_id")
        if outcome == "no_candidate" and replacement_id is None:
            return parent
        if not isinstance(replacement_id, int) or isinstance(replacement_id, bool):
            raise ValueError("event_merge_candidate_not_reviewable")
        replacement = self.get(replacement_id, for_update=True)
        if replacement is None:
            raise ValueError("event_merge_candidate_not_reviewable")
        return replacement

    @staticmethod
    def _record_recheck(
        parent: EventMergeCandidateRecord,
        operation_id: int,
        *,
        outcome: str,
        replacement_id: int | None,
    ) -> None:
        parent.reviewed_operation_id = operation_id
        parent.reviewed_at = datetime.now(UTC)
        parent.result_summary = {
            "recheck_outcome": outcome,
            "recheck_candidate_id": replacement_id,
        }

    def child_of(
        self, candidate_id: int, *, for_update: bool = False
    ) -> EventMergeCandidateRecord | None:
        statement = select(EventMergeCandidateRecord).where(
            EventMergeCandidateRecord.supersedes_candidate_id == candidate_id
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement)

    @staticmethod
    def _candidate_values(
        draft: MergeCandidateDraft,
        generated_operation_id: int,
        *,
        revision: int,
        supersedes_candidate_id: int | None,
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        return {
            "revision": revision,
            "supersedes_candidate_id": supersedes_candidate_id,
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

    def get(
        self, candidate_id: int, *, for_update: bool = False
    ) -> EventMergeCandidateRecord | None:
        statement = select(EventMergeCandidateRecord).where(
            EventMergeCandidateRecord.id == candidate_id
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
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

    def _chain_statement(self, draft: MergeCandidateDraft):
        return (
            select(EventMergeCandidateRecord)
            .where(
                EventMergeCandidateRecord.left_event_id == draft.left.event_id,
                EventMergeCandidateRecord.left_version_number
                == draft.left.version_number,
                EventMergeCandidateRecord.right_event_id == draft.right.event_id,
                EventMergeCandidateRecord.right_version_number
                == draft.right.version_number,
                EventMergeCandidateRecord.algorithm_version == draft.algorithm_version,
            )
            .order_by(EventMergeCandidateRecord.revision.desc())
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
