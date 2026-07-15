from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import OperationRunRecord, SourceDefinitionRecord, utcnow


class CatalogReconcileBlocked(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CatalogReconcilePlan:
    yaml_count: int
    current_db_count: int
    archive_ids: tuple[str, ...]
    restore_ids: tuple[str, ...]
    blocked_ids: tuple[str, ...]


def build_reconcile_plan(session: Session, yaml_ids: set[str]) -> CatalogReconcilePlan:
    records = list(
        session.scalars(select(SourceDefinitionRecord).order_by(SourceDefinitionRecord.id))
    )
    archive_ids = tuple(
        record.id
        for record in records
        if record.catalog_state == "current" and record.id not in yaml_ids
    )
    restore_ids = tuple(
        record.id
        for record in records
        if record.catalog_state == "archived" and record.id in yaml_ids
    )
    active_operations = session.scalars(
        select(OperationRunRecord).where(OperationRunRecord.status.in_(("queued", "running")))
    )
    active_source_ids = {
        str(scope["source_id"])
        for operation in active_operations
        if isinstance((scope := operation.requested_scope), dict) and scope.get("source_id")
    }
    blocked_ids = tuple(source_id for source_id in archive_ids if source_id in active_source_ids)
    return CatalogReconcilePlan(
        yaml_count=len(yaml_ids),
        current_db_count=sum(record.catalog_state == "current" for record in records),
        archive_ids=archive_ids,
        restore_ids=restore_ids,
        blocked_ids=blocked_ids,
    )


def apply_reconcile_plan(session: Session, plan: CatalogReconcilePlan) -> None:
    if plan.blocked_ids:
        raise CatalogReconcileBlocked(
            "cannot archive sources with queued or running operations: "
            + ", ".join(plan.blocked_ids)
        )
    for source_id in plan.archive_ids:
        record = session.get(SourceDefinitionRecord, source_id)
        if record is not None:
            record.catalog_state = "archived"
            record.catalog_archived_at = utcnow()
            record.catalog_archive_reason = "absent_from_current_yaml"
    for source_id in plan.restore_ids:
        record = session.get(SourceDefinitionRecord, source_id)
        if record is not None:
            record.catalog_state = "current"
            record.catalog_archived_at = None
            record.catalog_archive_reason = None
    session.flush()
