"""Bounded, claim-fenced ingestion for frozen high-value news waves."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import HighValueWaveMemberRecord
from newsradar.ingestion.schema import FetchOutcome
from newsradar.ingestion.service import SourceFetchSummary
from newsradar.operations.deadlines import OperationDeadline, OperationTimedOut
from newsradar.operations.fetch_runtime import FetchExecutor, execute_production_fetch
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import OperationResult
from newsradar.sources.repository import canonical_definition
from newsradar.sources.schema import SourceDefinition
from newsradar.waves.repository import WaveRepository


@dataclass(frozen=True, slots=True)
class WaveMemberOutcome:
    state: str
    result_code: str | None
    conclusion: str
    fetch_run_id: int | None = None


class HighValueWaveHandler:
    """Execute frozen members without retaining a database session during I/O."""

    def __init__(
        self,
        sources: Iterable[SourceDefinition],
        create_session: Callable[[], Session],
        executor: FetchExecutor = execute_production_fetch,
    ) -> None:
        self._sources = {source.id: source for source in sources}
        self._create_session = create_session
        self._executor = executor

    @classmethod
    def production(cls, sources: Iterable[SourceDefinition]) -> HighValueWaveHandler:
        from newsradar.db.session import create_session

        return cls(sources, create_session)

    def __call__(self, lease: OperationLease, checkpoint: Callable[[str], None]) -> OperationResult:
        if lease.operation_type != OperationType.HIGH_VALUE_NEWS_WAVE.value:
            return _failed(
                "unsupported_operation_type", "高价值新闻波次 Worker 只处理已冻结的波次任务"
            )
        try:
            return asyncio.run(self._run(lease, checkpoint))
        except OperationTimedOut as error:
            return _failed("operation_timeout", str(error))

    def run_member(
        self, *, operation_id: int, source_id: str, attempt_id: int
    ) -> WaveMemberOutcome:
        """Small synchronous seam for recovery and deterministic member tests."""
        return asyncio.run(
            self._run_member(operation_id, source_id, lambda _: None, None, attempt_id)
        )

    async def _run(
        self, lease: OperationLease, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        deadline = (
            OperationDeadline.from_scope(lease.requested_scope)
            if "deadline_at" in lease.requested_scope
            else None
        )
        if deadline is not None:
            deadline.check("before_high_value_wave")
        members = self._unfinished_members(lease.operation_id)
        global_semaphore = asyncio.Semaphore(6)
        provider_semaphores: defaultdict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(2)
        )

        async def run_one(source_id: str, provider_id: str) -> WaveMemberOutcome:
            async with global_semaphore:
                async with provider_semaphores[provider_id]:
                    if deadline is not None:
                        deadline.check("before_wave_member")
                    return await self._run_member(
                        lease.operation_id, source_id, checkpoint, deadline, lease.attempt_id
                    )

        await asyncio.gather(
            *(run_one(source_id, provider_id) for source_id, provider_id in members)
        )
        if deadline is not None:
            deadline.check("after_high_value_wave")
        return self._operation_result(lease.operation_id)

    def _unfinished_members(self, operation_id: int) -> list[tuple[str, str]]:
        with self._create_session() as session:
            return [
                (member.source_id, member.provider_id)
                for member in WaveRepository(session).members(operation_id)
                if member.state in {"pending", "running"}
            ]

    async def _run_member(
        self,
        operation_id: int,
        source_id: str,
        checkpoint: Callable[[str], None],
        deadline: OperationDeadline | None,
        attempt_id: int,
    ) -> WaveMemberOutcome:
        source = self._sources.get(source_id)
        with self._create_session() as session:
            repository = WaveRepository(session)
            member, claimed = repository.claim_member(
                operation_id, source_id, claim_attempt_id=attempt_id
            )
            if not claimed:
                return WaveMemberOutcome(
                    member.state, "already_claimed", member.conclusion or "成员已由其他 Worker 处理"
                )
            if source is None or member.definition_hash != canonical_definition(source)[1]:
                outcome = self._finish_in_session(
                    repository,
                    operation_id,
                    source_id,
                    "stale_result",
                    "stale_result",
                    "波次冻结后来源定义已变化，未发起网络抓取",
                    attempt_id,
                )
                session.commit()
                return outcome
            if not member.fetchable:
                outcome = self._finish_in_session(
                    repository,
                    operation_id,
                    source_id,
                    "blocked",
                    "blocked",
                    "冻结快照标记为不可抓取，未发起网络请求",
                    attempt_id,
                )
                session.commit()
                return outcome
            session.commit()

        checkpoint(f"before_wave_fetch:{source_id}")
        if deadline is not None:
            deadline.check("before_wave_fetch")
        try:
            summary = await asyncio.to_thread(
                self._executor, source, operation_id, checkpoint, {"wave": True}
            )
        except OperationTimedOut:
            raise
        except Exception as error:
            return self._finish(
                operation_id, source_id, "failed", "internal", str(error), attempt_id
            )
        checkpoint(f"after_wave_fetch:{source_id}")
        if deadline is not None:
            deadline.check("after_wave_fetch")
        return self._finish_from_summary(operation_id, source_id, summary, attempt_id)

    def _finish_from_summary(
        self, operation_id: int, source_id: str, summary: SourceFetchSummary, attempt_id: int
    ) -> WaveMemberOutcome:
        result = summary.result
        if result.outcome in {FetchOutcome.SUCCEEDED, FetchOutcome.NO_CHANGE}:
            state, code = "succeeded", None
        elif result.outcome is FetchOutcome.BLOCKED:
            state, code = "blocked", result.error_code or "blocked"
        elif result.outcome is FetchOutcome.PARTIAL:
            state, code = "partial", result.error_code or "partial"
        else:
            state, code = "failed", result.error_code or summary.error_code or "fetch_failed"
        return self._finish(
            operation_id,
            source_id,
            state,
            code,
            result.error_message or state,
            attempt_id,
            summary.fetch_run_id,
        )

    def _finish(
        self,
        operation_id: int,
        source_id: str,
        state: str,
        result_code: str | None,
        conclusion: str,
        attempt_id: int,
        fetch_run_id: int | None = None,
    ) -> WaveMemberOutcome:
        with self._create_session() as session:
            try:
                outcome = self._finish_in_session(
                    WaveRepository(session),
                    operation_id,
                    source_id,
                    state,
                    result_code,
                    conclusion,
                    attempt_id,
                    fetch_run_id,
                )
                session.commit()
                return outcome
            except PermissionError:
                session.rollback()
                return WaveMemberOutcome(
                    "running", "claim_lost", "成员认领已失效，未覆盖新 attempt 的结果"
                )

    @staticmethod
    def _finish_in_session(
        repository: WaveRepository,
        operation_id: int,
        source_id: str,
        state: str,
        result_code: str | None,
        conclusion: str,
        attempt_id: int,
        fetch_run_id: int | None = None,
    ) -> WaveMemberOutcome:
        repository.finish_member(
            operation_id,
            source_id,
            state=state,
            result_code=result_code,
            conclusion=conclusion,
            fetch_run_id=fetch_run_id,
            claim_attempt_id=attempt_id,
        )
        return WaveMemberOutcome(state, result_code, conclusion, fetch_run_id)

    def _operation_result(self, operation_id: int) -> OperationResult:
        with self._create_session() as session:
            rows = list(
                session.scalars(
                    select(HighValueWaveMemberRecord).where(
                        HighValueWaveMemberRecord.operation_run_id == operation_id
                    )
                )
            )
        summary = Counter(row.state for row in rows)
        result_summary = {
            **dict(sorted(summary.items())),
            "fetch_succeeded": summary.get("succeeded", 0),
        }
        status = (
            OperationStatus.SUCCEEDED
            if rows and summary.get("succeeded", 0) == len(rows)
            else OperationStatus.PARTIAL
        )
        return OperationResult(status=status, result_summary=result_summary, retryable=False)


def _failed(error_code: str, message: str) -> OperationResult:
    return OperationResult(
        status=OperationStatus.FAILED, error_code=error_code, error_message=message, retryable=False
    )
