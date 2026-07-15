"""Bounded execution of the direct-content lane of a catalog refresh."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from newsradar.operations.deadlines import OperationDeadline, OperationTimedOut
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import OperationResult
from newsradar.providers.schema import ProviderDefinition
from newsradar.sources.catalog_refresh import (
    CatalogMemberState,
    CatalogRefreshLane,
    CatalogResultCode,
    catalog_definition_hash,
)
from newsradar.sources.catalog_refresh_repository import CatalogRefreshRepository
from newsradar.sources.probes.base import ProbeOutcome, ProbeResult
from newsradar.sources.probes.factory import ProbeFactory
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import AccessMethod, SourceDefinition


class ProbeCallable(Protocol):
    def __call__(
        self, source: SourceDefinition, method: AccessMethod
    ) -> Awaitable[ProbeResult]: ...


@dataclass(frozen=True, slots=True)
class ContentMemberOutcome:
    state: CatalogMemberState
    result_code: CatalogResultCode | None
    conclusion: str
    content_probe_run_ids: tuple[int, ...]


class CatalogRefreshHandler:
    """Run only the auditable direct-content portion of a frozen refresh batch.

    Database interactions are deliberately short-lived.  A session is never retained
    while a probe awaits remote I/O.
    """

    def __init__(
        self,
        sources: Iterable[SourceDefinition],
        providers: Iterable[ProviderDefinition],
        create_session: Callable[[], Session],
        probe_factory: ProbeCallable | None = None,
    ) -> None:
        self._sources = {source.id: source for source in sources}
        self._providers = tuple(providers)
        self._create_session = create_session
        self._probe_factory = probe_factory

    @classmethod
    def production(
        cls,
        sources: Iterable[SourceDefinition],
        providers: Iterable[ProviderDefinition],
        create_session: Callable[[], Session],
    ) -> CatalogRefreshHandler:
        return cls(sources, providers, create_session)

    @staticmethod
    def definition_hash(source: SourceDefinition, providers: Iterable[ProviderDefinition]) -> str:
        """Use the planner fingerprint without applying its archived-source filter."""
        return catalog_definition_hash(source, providers)

    def __call__(self, lease: OperationLease, checkpoint: Callable[[str], None]) -> OperationResult:
        if lease.operation_type != OperationType.SOURCE_CATALOG_REFRESH.value:
            return _failed("unsupported_operation_type", "全量盘点 Worker 只处理来源目录刷新任务")
        try:
            return asyncio.run(self._run(lease, checkpoint))
        except OperationTimedOut as error:
            return _failed("operation_timeout", str(error))

    def run_content_member(
        self, operation_run_id: int, source_id: str, checkpoint: Callable[[str], None]
    ) -> ContentMemberOutcome:
        """Small synchronous seam for deterministic member-level tests and recovery."""
        return asyncio.run(self._run_content_member(operation_run_id, source_id, checkpoint))

    async def _run(
        self, lease: OperationLease, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        deadline = OperationDeadline.from_scope(lease.requested_scope)
        deadline.check("before_catalog_refresh")
        members = self._content_member_ids(lease.operation_id)
        global_limit = _bounded_scope_int(lease.requested_scope, "global_concurrency", 8)
        provider_limit = _bounded_scope_int(lease.requested_scope, "provider_concurrency", 2)
        global_semaphore = asyncio.Semaphore(global_limit)
        provider_semaphores: defaultdict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(provider_limit)
        )

        async def run_one(source_id: str, provider_id: str) -> ContentMemberOutcome:
            async with global_semaphore:
                async with provider_semaphores[provider_id]:
                    deadline.check("before_content_member")
                    return await self._run_content_member(lease.operation_id, source_id, checkpoint)

        outcomes = await asyncio.gather(
            *(run_one(source_id, provider_id) for source_id, provider_id in members)
        )
        deadline.check("after_catalog_refresh")
        summary = Counter(outcome.state.value for outcome in outcomes)
        return OperationResult(
            status=(
                OperationStatus.SUCCEEDED
                if not outcomes
                or all(outcome.state is CatalogMemberState.SUCCEEDED for outcome in outcomes)
                else OperationStatus.PARTIAL
            ),
            result_summary={"content_members": len(outcomes), **dict(sorted(summary.items()))},
            retryable=False,
        )

    def _content_member_ids(self, operation_run_id: int) -> list[tuple[str, str]]:
        with self._create_session() as session:
            records = CatalogRefreshRepository(session).unfinished_members(operation_run_id)
            return [
                (record.source_id, record.provider_id)
                for record in records
                if record.lane == CatalogRefreshLane.CONTENT.value
            ]

    async def _run_content_member(
        self, operation_run_id: int, source_id: str, checkpoint: Callable[[str], None]
    ) -> ContentMemberOutcome:
        source = self._sources.get(source_id)
        if source is None:
            return self._finish(
                operation_run_id,
                source_id,
                CatalogMemberState.DEGRADED,
                CatalogResultCode.STALE_RESULT,
                "批次创建后来源定义已变化",
                (),
            )
        expected_hash = self.definition_hash(source, self._providers)
        with self._create_session() as session:
            repository = CatalogRefreshRepository(session)
            member = repository.start_member(operation_run_id, source_id)
            access_kind = member.access_kind_snapshot
            if (
                _source_is_unavailable_or_archived(source)
                or member.definition_hash != expected_hash
            ):
                outcome = self._finish_in_session(
                    repository,
                    operation_run_id,
                    source_id,
                    CatalogMemberState.DEGRADED,
                    CatalogResultCode.STALE_RESULT,
                    "批次创建后来源定义已变化",
                    (),
                )
                session.commit()
                return outcome
            session.commit()

        method = next(
            (item for item in source.access_methods if item.kind.value == access_kind),
            None,
        )
        if method is None:
            return self._finish(
                operation_run_id,
                source_id,
                CatalogMemberState.FAILED,
                CatalogResultCode.UNSUPPORTED_ACCESS_KIND,
                "冻结访问方式已不在当前来源定义中",
                (),
            )

        probe_run_ids: list[int] = []
        for round_number in range(3):
            checkpoint(f"before_catalog_content_probe:{source_id}:{round_number + 1}")
            try:
                result = await self._probe(source, method)
            except Exception:
                return self._finish_internal_error(operation_run_id, source_id)
            checkpoint(f"after_catalog_content_probe:{source_id}:{round_number + 1}")
            code = result_code_for_probe(result)
            probe_run_ids.append(self._save_probe(operation_run_id, result))
            if code is not None or result.outcome is not ProbeOutcome.SUCCESS:
                state = _state_for_code(code)
                return self._finish(
                    operation_run_id,
                    source_id,
                    state,
                    code or CatalogResultCode.INTERNAL_ERROR,
                    _conclusion_for_code(code),
                    tuple(probe_run_ids),
                )
        return self._finish(
            operation_run_id,
            source_id,
            CatalogMemberState.SUCCEEDED,
            None,
            "连续三轮内容探测成功，字段完整率均不低于 90%",
            tuple(probe_run_ids),
        )

    async def _probe(self, source: SourceDefinition, method: AccessMethod) -> ProbeResult:
        if self._probe_factory is not None:
            return await self._probe_factory(source, method)
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await ProbeFactory(client).create(method).probe(source, method)

    def _save_probe(self, operation_run_id: int, result: ProbeResult) -> int:
        with self._create_session() as session:
            record = SourceRepository(session).save_probe_result(
                result, operation_run_id=operation_run_id
            )
            session.commit()
            return record.id

    def _finish(
        self,
        operation_run_id: int,
        source_id: str,
        state: CatalogMemberState,
        result_code: CatalogResultCode | None,
        conclusion: str,
        probe_run_ids: tuple[int, ...],
    ) -> ContentMemberOutcome:
        with self._create_session() as session:
            outcome = self._finish_in_session(
                CatalogRefreshRepository(session),
                operation_run_id,
                source_id,
                state,
                result_code,
                conclusion,
                probe_run_ids,
            )
            session.commit()
            return outcome

    @staticmethod
    def _finish_in_session(
        repository: CatalogRefreshRepository,
        operation_run_id: int,
        source_id: str,
        state: CatalogMemberState,
        result_code: CatalogResultCode | None,
        conclusion: str,
        probe_run_ids: tuple[int, ...],
    ) -> ContentMemberOutcome:
        repository.finish_member(
            operation_run_id,
            source_id,
            state,
            result_code,
            conclusion,
            content_probe_run_ids=list(probe_run_ids),
        )
        return ContentMemberOutcome(state, result_code, conclusion, probe_run_ids)

    def _finish_internal_error(self, operation_run_id: int, source_id: str) -> ContentMemberOutcome:
        return self._finish(
            operation_run_id,
            source_id,
            CatalogMemberState.FAILED,
            CatalogResultCode.INTERNAL_ERROR,
            "内容探测执行异常，未影响同批其他来源",
            (),
        )


def result_code_for_probe(result: ProbeResult) -> CatalogResultCode | None:
    """Convert protocol-specific probe output to the frozen catalog vocabulary."""
    error = (result.error_code or "").lower()
    if error == "no_content":
        return CatalogResultCode.NO_CONTENT
    if error == "incomplete_fields":
        return CatalogResultCode.INCOMPLETE_FIELDS
    if result.http_status == 429 or error in {"http_429", "rate_limited"}:
        return CatalogResultCode.RATE_LIMITED
    if error in {"timeout", "operation_timeout"}:
        return CatalogResultCode.TIMEOUT
    if error in {"connection_error", "connect_error", "dns_error"}:
        return CatalogResultCode.CONNECTION_ERROR
    if error == "missing_credential":
        return CatalogResultCode.MISSING_CREDENTIALS
    if error == "unsupported_access_kind":
        return CatalogResultCode.UNSUPPORTED_ACCESS_KIND
    if result.http_status == 401 or error == "http_401":
        return CatalogResultCode.MISSING_CREDENTIALS
    if result.http_status == 403 or error == "http_403":
        return CatalogResultCode.REQUIRES_APPROVAL
    if error:
        return None
    if result.sample_count == 0:
        return CatalogResultCode.NO_CONTENT
    if result.field_completeness < 0.9:
        return CatalogResultCode.INCOMPLETE_FIELDS
    return None


def _state_for_code(code: CatalogResultCode | None) -> CatalogMemberState:
    if code in {
        CatalogResultCode.NO_CONTENT,
        CatalogResultCode.INCOMPLETE_FIELDS,
        CatalogResultCode.STALE_RESULT,
    }:
        return CatalogMemberState.DEGRADED
    if code in {
        CatalogResultCode.MISSING_CREDENTIALS,
        CatalogResultCode.REQUIRES_APPROVAL,
        CatalogResultCode.REQUIRES_PAYMENT,
    }:
        return CatalogMemberState.BLOCKED
    return CatalogMemberState.FAILED


def _conclusion_for_code(code: CatalogResultCode | None) -> str:
    return {
        CatalogResultCode.NO_CONTENT: "首轮内容探测未获得可用样本",
        CatalogResultCode.INCOMPLETE_FIELDS: "首轮内容探测字段完整率低于 90%",
        CatalogResultCode.RATE_LIMITED: "首轮内容探测被上游限流",
        CatalogResultCode.TIMEOUT: "首轮内容探测超时",
        CatalogResultCode.CONNECTION_ERROR: "首轮内容探测连接失败",
        CatalogResultCode.MISSING_CREDENTIALS: "首轮内容探测缺少有效凭据",
        CatalogResultCode.REQUIRES_APPROVAL: "首轮内容探测需要平台审批",
        CatalogResultCode.UNSUPPORTED_ACCESS_KIND: "首轮内容探测缺少已审核的协议实现",
    }.get(code, "首轮内容探测未成功完成")


def _bounded_scope_int(scope: dict[str, object], key: str, default: int) -> int:
    value = scope.get(key, default)
    return value if isinstance(value, int) and 1 <= value <= 16 else default


def _source_is_unavailable_or_archived(source: SourceDefinition) -> bool:
    return (
        getattr(source, "catalog_state", None) == "archived"
        or getattr(source.availability, "value", source.availability) != "ready"
    )


def _failed(error_code: str, message: str) -> OperationResult:
    return OperationResult(
        status=OperationStatus.FAILED,
        error_code=error_code,
        error_message=message,
        retryable=False,
    )
