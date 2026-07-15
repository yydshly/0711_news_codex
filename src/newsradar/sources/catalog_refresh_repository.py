"""Short-transaction persistence for immutable catalog refresh plans."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from newsradar.db.models import (
    OperationRunRecord,
    SourceCatalogRefreshMemberRecord,
    utcnow,
)

from .catalog_refresh import (
    CatalogMemberState,
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
    CatalogResultCode,
)

_UNFINISHED_STATES = (CatalogMemberState.PENDING.value, CatalogMemberState.RUNNING.value)
_RETRYABLE_CODES = {
    CatalogResultCode.TIMEOUT,
    CatalogResultCode.CONNECTION_ERROR,
    CatalogResultCode.RATE_LIMITED,
    CatalogResultCode.DEADLINE_EXCEEDED,
}


class CatalogRefreshRepository:
    """Persist member snapshots only; it never resolves current source definitions."""

    def __init__(self, session: Session):
        self.session = session

    def create_members(
        self, operation_run_id: int, plan: CatalogRefreshPlan
    ) -> list[SourceCatalogRefreshMemberRecord]:
        records = [
            SourceCatalogRefreshMemberRecord(
                operation_run_id=operation_run_id,
                source_id=member.source_id,
                provider_id=member.provider_id,
                definition_hash=member.definition_hash,
                availability_snapshot=member.availability,
                coverage_mode_snapshot=member.coverage_mode,
                access_kind_snapshot=member.access_kind,
                lane=member.lane.value,
                state=CatalogMemberState.PENDING.value,
                result_code=(
                    member.initial_result_code.value if member.initial_result_code else None
                ),
                content_probe_run_ids=[],
                attempt_count=0,
            )
            for member in plan.members
        ]
        self.session.add_all(records)
        self.session.flush()
        return records

    def unfinished_members(self, operation_run_id: int) -> list[SourceCatalogRefreshMemberRecord]:
        return list(
            self.session.scalars(
                select(SourceCatalogRefreshMemberRecord)
                .where(
                    SourceCatalogRefreshMemberRecord.operation_run_id == operation_run_id,
                    SourceCatalogRefreshMemberRecord.state.in_(_UNFINISHED_STATES),
                )
                .order_by(SourceCatalogRefreshMemberRecord.source_id)
            )
        )

    def start_member(
        self, operation_run_id: int, source_id: str
    ) -> SourceCatalogRefreshMemberRecord:
        # A fresh Session is used for every member by the concurrent Worker.  Lock
        # this exact row so two workers/recovered leases cannot both observe an
        # unfinished state and advance operation progress twice.
        record = self.session.scalar(
            select(SourceCatalogRefreshMemberRecord)
            .where(
                SourceCatalogRefreshMemberRecord.operation_run_id == operation_run_id,
                SourceCatalogRefreshMemberRecord.source_id == source_id,
            )
            .with_for_update()
        )
        if record is None:
            raise LookupError(f"catalog refresh member not found: {operation_run_id}/{source_id}")
        record.state = CatalogMemberState.RUNNING.value
        record.attempt_count += 1
        record.started_at = record.started_at or utcnow()
        self.session.flush()
        return record

    def finish_member(
        self,
        operation_run_id: int,
        source_id: str,
        state: CatalogMemberState,
        result_code: CatalogResultCode | None,
        conclusion: str | None,
        content_probe_run_ids: list[int] | None = None,
        provider_probe_run_id: int | None = None,
    ) -> SourceCatalogRefreshMemberRecord:
        record = self.session.scalar(
            select(SourceCatalogRefreshMemberRecord)
            .where(
                SourceCatalogRefreshMemberRecord.operation_run_id == operation_run_id,
                SourceCatalogRefreshMemberRecord.source_id == source_id,
            )
            .with_for_update()
        )
        if record is None:
            raise LookupError(f"catalog refresh member not found: {operation_run_id}/{source_id}")
        was_unfinished = record.state in _UNFINISHED_STATES
        record.state = state.value
        record.result_code = result_code.value if result_code else None
        record.conclusion = conclusion
        if content_probe_run_ids is not None:
            record.content_probe_run_ids = list(content_probe_run_ids)
        if provider_probe_run_id is not None:
            record.provider_probe_run_id = provider_probe_run_id
        record.finished_at = utcnow()
        # The operation view is the live, durable progress surface.  Count a member
        # exactly once when it first leaves a resumable state; recovery must never
        # inflate the total by revisiting an already terminal member.
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

    def summary(self, operation_run_id: int) -> dict[str, int]:
        counts = Counter(
            f"{record.lane}_{record.state}"
            for record in self.session.scalars(
                select(SourceCatalogRefreshMemberRecord).where(
                    SourceCatalogRefreshMemberRecord.operation_run_id == operation_run_id
                )
            )
        )
        return dict(sorted(counts.items()))

    def retryable_plan(self, operation_run_id: int) -> CatalogRefreshPlan:
        records = self.session.scalars(
            select(SourceCatalogRefreshMemberRecord)
            .where(
                SourceCatalogRefreshMemberRecord.operation_run_id == operation_run_id,
                SourceCatalogRefreshMemberRecord.state == CatalogMemberState.FAILED.value,
                SourceCatalogRefreshMemberRecord.result_code.in_(
                    [code.value for code in _RETRYABLE_CODES]
                ),
            )
            .order_by(SourceCatalogRefreshMemberRecord.source_id)
        )
        return CatalogRefreshPlan.from_members(
            self.snapshot_from_record(record) for record in records
        )

    @staticmethod
    def snapshot_from_record(
        record: SourceCatalogRefreshMemberRecord,
    ) -> CatalogRefreshMemberSnapshot:
        return CatalogRefreshMemberSnapshot(
            source_id=record.source_id,
            provider_id=record.provider_id,
            definition_hash=record.definition_hash,
            availability=record.availability_snapshot,
            coverage_mode=record.coverage_mode_snapshot,
            access_kind=record.access_kind_snapshot,
            lane=CatalogRefreshLane(record.lane),
        )

    def _get_member(
        self, operation_run_id: int, source_id: str
    ) -> SourceCatalogRefreshMemberRecord:
        record = self.session.scalar(
            select(SourceCatalogRefreshMemberRecord).where(
                SourceCatalogRefreshMemberRecord.operation_run_id == operation_run_id,
                SourceCatalogRefreshMemberRecord.source_id == source_id,
            )
        )
        if record is None:
            raise LookupError(f"catalog refresh member not found: {operation_run_id}/{source_id}")
        return record
