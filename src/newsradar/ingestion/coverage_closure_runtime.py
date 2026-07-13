from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsradar.db.models import FetchRunRecord, OperationRunRecord, RawItemRecord
from newsradar.ingestion.coverage_closure import CoverageClosurePlan, build_coverage_closure_plan
from newsradar.operations.commands import OperationCommandService
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import SourceDefinition

_COVERED_OUTCOMES = frozenset({"succeeded", "no_change"})
_ACTIVE_OPERATION_STATUSES = frozenset(
    {OperationStatus.QUEUED.value, OperationStatus.RUNNING.value}
)


class _OperationCommands(Protocol):
    def enqueue_fetch(
        self,
        *,
        source_id: str,
        max_items: int,
        trial: bool,
        trigger: str,
    ) -> int: ...

    def wait_for_terminal(self, operation_id: int) -> OperationRunRecord: ...


@dataclass(frozen=True, slots=True)
class ClosureOperation:
    source_id: str
    operation_id: int
    status: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageEvidence:
    source_id: str
    latest_fetch_outcome: str | None
    latest_fetch_error_code: str | None
    raw_item_count: int


class CoverageClosureService:
    def __init__(
        self,
        session: Session,
        *,
        commands_factory: Callable[[Session], _OperationCommands] = OperationCommandService,
    ) -> None:
        self.session = session
        self._commands_factory = commands_factory

    def plan(self, sources: Sequence[SourceDefinition]) -> CoverageClosurePlan:
        source_ids = [source.id for source in sources]
        covered_source_ids = set(
            self.session.scalars(
                select(FetchRunRecord.source_id)
                .where(FetchRunRecord.source_id.in_(source_ids))
                .where(FetchRunRecord.outcome.in_(_COVERED_OUTCOMES))
                .distinct()
            )
        )
        active_source_ids = {
            source_id
            for scope in self.session.scalars(
                select(OperationRunRecord.requested_scope)
                .where(OperationRunRecord.operation_type == OperationType.FETCH.value)
                .where(OperationRunRecord.status.in_(_ACTIVE_OPERATION_STATUSES))
            )
            if isinstance(scope, dict)
            for source_id in [scope.get("source_id")]
            if isinstance(source_id, str) and source_id
        }
        snapshots = SourceRepository(self.session).latest_probe_snapshots(source_ids)
        return build_coverage_closure_plan(
            sources,
            snapshots,
            covered_source_ids,
            active_source_ids,
        )

    def enqueue(
        self,
        plan: CoverageClosurePlan,
        *,
        max_items: int,
        trigger: str,
    ) -> tuple[ClosureOperation, ...]:
        if not 1 <= max_items <= 5:
            raise ValueError("max_items_must_be_between_1_and_5")
        commands = self._commands_factory(self.session)
        operations: list[ClosureOperation] = []
        for entry in plan.queueable:
            try:
                operation_id = commands.enqueue_fetch(
                    source_id=entry.source_id,
                    max_items=max_items,
                    trial=True,
                    trigger=trigger,
                )
            except ValueError:
                operations.append(ClosureOperation(entry.source_id, 0, "enqueue_failed"))
                continue
            operations.append(ClosureOperation(entry.source_id, operation_id))
        return tuple(operations)

    def wait(self, operations: Sequence[ClosureOperation]) -> tuple[ClosureOperation, ...]:
        commands = self._commands_factory(self.session)
        terminals: list[ClosureOperation] = []
        for operation in operations:
            if operation.operation_id <= 0:
                terminals.append(operation)
                continue
            try:
                terminal = commands.wait_for_terminal(operation.operation_id)
            except LookupError:
                terminals.append(replace(operation, status="missing"))
            except TimeoutError:
                terminals.append(replace(operation, status="timed_out"))
            else:
                terminals.append(replace(operation, status=terminal.status))
        return tuple(terminals)

    def evidence(self, source_ids: Sequence[str]) -> tuple[CoverageEvidence, ...]:
        requested_ids = tuple(dict.fromkeys(source_ids))
        if not requested_ids:
            return ()
        latest_fetches: dict[str, FetchRunRecord] = {}
        for fetch in self.session.scalars(
            select(FetchRunRecord)
            .where(FetchRunRecord.source_id.in_(requested_ids))
            .order_by(
                FetchRunRecord.source_id,
                FetchRunRecord.started_at.desc(),
                FetchRunRecord.id.desc(),
            )
        ):
            latest_fetches.setdefault(fetch.source_id, fetch)
        raw_item_counts = dict(
            self.session.execute(
                select(RawItemRecord.source_id, func.count(RawItemRecord.id))
                .where(RawItemRecord.source_id.in_(requested_ids))
                .group_by(RawItemRecord.source_id)
            ).all()
        )
        return tuple(
            CoverageEvidence(
                source_id=source_id,
                latest_fetch_outcome=latest_fetches.get(source_id).outcome
                if source_id in latest_fetches
                else None,
                latest_fetch_error_code=latest_fetches.get(source_id).error_code
                if source_id in latest_fetches
                else None,
                raw_item_count=int(raw_item_counts.get(source_id, 0)),
            )
            for source_id in sorted(requested_ids)
        )
