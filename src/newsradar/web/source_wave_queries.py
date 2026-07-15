"""Read-only projections for frozen source catalog refresh waves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsradar.db.models import OperationRunRecord, SourceCatalogRefreshMemberRecord


@dataclass(frozen=True, slots=True)
class SourceWaveSummary:
    operation_id: int
    status: str
    created_at: datetime
    progress_current: int
    progress_total: int | None
    catalog_digest: str | None

    @classmethod
    def from_record(cls, record: OperationRunRecord) -> SourceWaveSummary:
        return cls(
            operation_id=record.id,
            status=record.status,
            created_at=record.created_at,
            progress_current=record.progress_current,
            progress_total=record.progress_total,
            catalog_digest=str(record.requested_scope.get("catalog_digest"))
            if record.requested_scope.get("catalog_digest")
            else None,
        )


@dataclass(frozen=True, slots=True)
class SourceWaveMember:
    source_id: str
    provider_id: str
    lane: str
    availability: str
    coverage_mode: str
    state: str
    result_code: str | None
    conclusion: str | None

    @classmethod
    def from_record(cls, record: SourceCatalogRefreshMemberRecord) -> SourceWaveMember:
        return cls(
            source_id=record.source_id,
            provider_id=record.provider_id,
            lane=record.lane,
            availability=record.availability_snapshot,
            coverage_mode=record.coverage_mode_snapshot,
            state=record.state,
            result_code=record.result_code,
            conclusion=record.conclusion,
        )


@dataclass(frozen=True, slots=True)
class SourceWaveOutcomeSummary:
    content_success: int
    capability_confirmed: int
    catalog_confirmed: int
    degraded: int
    runtime_failed: int

    @property
    def counts(self) -> tuple[int, int, int, int, int]:
        return (
            self.content_success,
            self.capability_confirmed,
            self.catalog_confirmed,
            self.degraded,
            self.runtime_failed,
        )


@dataclass(frozen=True, slots=True)
class SourceWaveDetail:
    operation: SourceWaveSummary
    members: tuple[SourceWaveMember, ...]
    total: int
    page: int
    page_size: int
    summary: SourceWaveOutcomeSummary


class SourceWaveQueryService:
    def __init__(self, session: Session):
        self.session = session

    def list_waves(self, *, limit: int = 20) -> tuple[SourceWaveSummary, ...]:
        records = self.session.scalars(
            select(OperationRunRecord)
            .where(OperationRunRecord.operation_type == "source_catalog_refresh")
            .order_by(OperationRunRecord.created_at.desc(), OperationRunRecord.id.desc())
            .limit(max(1, min(limit, 100)))
        )
        return tuple(SourceWaveSummary.from_record(record) for record in records)

    def detail(
        self,
        operation_id: int,
        *,
        lane: str | None = None,
        provider_id: str | None = None,
        availability: str | None = None,
        coverage_mode: str | None = None,
        state: str | None = None,
        result_code: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> SourceWaveDetail | None:
        operation = self.session.get(OperationRunRecord, operation_id)
        if operation is None or operation.operation_type != "source_catalog_refresh":
            return None
        page, page_size = _pagination(page, page_size)
        filters = _member_filters(
            operation_id,
            lane=lane,
            provider_id=provider_id,
            availability=availability,
            coverage_mode=coverage_mode,
            state=state,
            result_code=result_code,
        )
        total = int(
            self.session.scalar(
                select(func.count()).select_from(SourceCatalogRefreshMemberRecord).where(*filters)
            )
            or 0
        )
        records = self.session.scalars(
            select(SourceCatalogRefreshMemberRecord)
            .where(*filters)
            .order_by(SourceCatalogRefreshMemberRecord.source_id)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        summary = self._summary(operation_id)
        return SourceWaveDetail(
            operation=SourceWaveSummary.from_record(operation),
            members=tuple(SourceWaveMember.from_record(record) for record in records),
            total=total,
            page=page,
            page_size=page_size,
            summary=summary,
        )

    def _summary(self, operation_id: int) -> SourceWaveOutcomeSummary:
        rows = self.session.execute(
            select(
                SourceCatalogRefreshMemberRecord.lane,
                SourceCatalogRefreshMemberRecord.state,
                func.count().label("count"),
            )
            .where(SourceCatalogRefreshMemberRecord.operation_run_id == operation_id)
            .group_by(SourceCatalogRefreshMemberRecord.lane, SourceCatalogRefreshMemberRecord.state)
        )
        counts = {tuple(row[:2]): int(row.count) for row in rows}
        return SourceWaveOutcomeSummary(
            content_success=counts.get(("content", "succeeded"), 0),
            capability_confirmed=counts.get(("capability", "succeeded"), 0),
            catalog_confirmed=counts.get(("catalog", "succeeded"), 0),
            degraded=sum(count for (_, status), count in counts.items() if status == "degraded"),
            runtime_failed=sum(
                count
                for (_, status), count in counts.items()
                if status in {"failed", "blocked", "cancelled"}
            ),
        )


def _member_filters(operation_id: int, **values: str | None) -> tuple[object, ...]:
    filters: list[object] = [SourceCatalogRefreshMemberRecord.operation_run_id == operation_id]
    fields = {
        "lane": SourceCatalogRefreshMemberRecord.lane,
        "provider_id": SourceCatalogRefreshMemberRecord.provider_id,
        "availability": SourceCatalogRefreshMemberRecord.availability_snapshot,
        "coverage_mode": SourceCatalogRefreshMemberRecord.coverage_mode_snapshot,
        "state": SourceCatalogRefreshMemberRecord.state,
        "result_code": SourceCatalogRefreshMemberRecord.result_code,
    }
    for name, value in values.items():
        if value:
            filters.append(fields[name] == value)
    return tuple(filters)


def _pagination(page: int, page_size: int) -> tuple[int, int]:
    return max(1, page), max(1, min(page_size, 100))
