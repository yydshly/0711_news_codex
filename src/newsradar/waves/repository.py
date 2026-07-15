"""Short-transaction persistence for frozen high-value news waves."""

from __future__ import annotations

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from newsradar.db.models import HighValueWaveMemberRecord, OperationRunRecord, utcnow

from .planning import WavePlan

_UNFINISHED_STATES = ("pending", "running")


class WaveRepository:
    """Persist WavePlan snapshots; never re-resolve live catalog or credentials."""

    def __init__(self, session: Session):
        self.session = session

    def create_members(
        self, operation_run_id: int, plan: WavePlan
    ) -> list[HighValueWaveMemberRecord]:
        records = [
            HighValueWaveMemberRecord(
                operation_run_id=operation_run_id,
                source_id=member.source_id,
                provider_id=member.provider_id,
                definition_hash=member.definition_hash,
                roles_snapshot=list(member.roles),
                availability_snapshot=member.availability,
                access_kind_snapshot=member.access_kind,
                fetchable=member.fetchable,
                state="pending",
                conclusion=member.blocked_reason,
            )
            for member in plan.members
        ]
        self.session.add_all(records)
        self.session.flush()
        return records

    def members(self, operation_run_id: int) -> list[HighValueWaveMemberRecord]:
        return list(
            self.session.scalars(
                select(HighValueWaveMemberRecord)
                .where(HighValueWaveMemberRecord.operation_run_id == operation_run_id)
                .order_by(HighValueWaveMemberRecord.source_id)
            )
        )

    def claim_member(
        self, operation_run_id: int, source_id: str, *, claim_attempt_id: int | None = None
    ) -> tuple[HighValueWaveMemberRecord, bool]:
        self._require_claim_attempt_id(claim_attempt_id)
        record = self._locked_member(operation_run_id, source_id)
        if record.state != "pending":
            return record, False
        record.state = "running"
        record.claim_attempt_id = claim_attempt_id
        record.started_at = record.started_at or utcnow()
        self.session.flush()
        return record, True

    def finish_member(
        self,
        operation_run_id: int,
        source_id: str,
        *,
        state: str,
        result_code: str | None,
        conclusion: str | None,
        fetch_run_id: int | None = None,
        claim_attempt_id: int | None = None,
    ) -> HighValueWaveMemberRecord:
        self._require_claim_attempt_id(claim_attempt_id)
        record = self._locked_member(operation_run_id, source_id)
        if record.claim_attempt_id != claim_attempt_id:
            raise PermissionError(
                f"high value wave member claim lost: {operation_run_id}/{source_id}"
            )
        was_unfinished = record.state in _UNFINISHED_STATES
        record.state, record.result_code, record.conclusion = state, result_code, conclusion
        if fetch_run_id is not None:
            record.fetch_run_id = fetch_run_id
        record.finished_at = utcnow()
        if was_unfinished:
            self.session.execute(
                update(OperationRunRecord)
                .where(OperationRunRecord.id == operation_run_id)
                .values(
                    progress_current=case(
                        (
                            (OperationRunRecord.progress_total.is_not(None))
                            & (
                                OperationRunRecord.progress_current
                                >= OperationRunRecord.progress_total
                            ),
                            OperationRunRecord.progress_current,
                        ),
                        else_=OperationRunRecord.progress_current + 1,
                    )
                )
            )
        self.session.flush()
        return record

    def _locked_member(self, operation_run_id: int, source_id: str) -> HighValueWaveMemberRecord:
        record = self.session.scalar(
            select(HighValueWaveMemberRecord)
            .where(
                HighValueWaveMemberRecord.operation_run_id == operation_run_id,
                HighValueWaveMemberRecord.source_id == source_id,
            )
            .with_for_update()
        )
        if record is None:
            raise LookupError(f"high value wave member not found: {operation_run_id}/{source_id}")
        return record

    @staticmethod
    def _require_claim_attempt_id(claim_attempt_id: int | None) -> None:
        if claim_attempt_id is None or claim_attempt_id <= 0:
            raise ValueError("claim_attempt_id_required")
