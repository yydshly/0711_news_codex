"""Bounded execution of the direct-content lane of a catalog refresh."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import OperationRunRecord, SourceCatalogRefreshMemberRecord
from newsradar.operations.deadlines import OperationDeadline, OperationTimedOut
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import OperationResult
from newsradar.providers.probes import ProviderProbe, ProviderProbeResult
from newsradar.providers.repository import ProviderRepository
from newsradar.providers.schema import ProviderDefinition
from newsradar.sources.catalog_refresh import (
    CatalogMemberState,
    CatalogRefreshLane,
    CatalogResultCode,
    catalog_definition_hash,
    validate_catalog_entry,
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


class ProviderProbeCallable(Protocol):
    def __call__(self, provider: ProviderDefinition) -> Awaitable[ProviderProbeResult]: ...


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
        provider_probe_factory: ProviderProbeCallable | None = None,
    ) -> None:
        self._sources = {source.id: source for source in sources}
        self._providers = tuple(providers)
        self._create_session = create_session
        self._probe_factory = probe_factory
        self._provider_probe_factory = provider_probe_factory

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
        members = self._unfinished_member_ids(lease.operation_id)
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
                    return await self._run_content_member(
                        lease.operation_id, source_id, checkpoint, deadline
                    )

        content_outcomes = await asyncio.gather(
            *(run_one(source_id, provider_id) for source_id, provider_id in members)
        )
        capability_outcomes: list[ContentMemberOutcome] = []
        for provider_id, source_ids in self._capability_member_ids(lease.operation_id).items():
            checkpoint(f"before_catalog_capability_probe:{provider_id}")
            deadline.check("before_capability_probe")
            capability_outcomes.extend(
                await self._run_capability_group(lease.operation_id, provider_id, source_ids)
            )
            checkpoint(f"after_catalog_capability_probe:{provider_id}")
        catalog_outcomes = [
            self._run_catalog_member(lease.operation_id, source_id)
            for source_id in self._catalog_member_ids(lease.operation_id)
        ]
        outcomes = [*content_outcomes, *capability_outcomes, *catalog_outcomes]
        deadline.check("after_catalog_refresh")
        with self._create_session() as session:
            operation = session.get(OperationRunRecord, lease.operation_id)
            completed_count = operation.progress_current if operation is not None else 0
            catalog_count = operation.progress_total if operation is not None else len(outcomes)
            summary = Counter(
                record.state
                for record in session.scalars(
                    select(SourceCatalogRefreshMemberRecord).where(
                        SourceCatalogRefreshMemberRecord.operation_run_id == lease.operation_id
                    )
                )
            )
        terminal_status = (
            OperationStatus.SUCCEEDED
            if catalog_count == summary.get(CatalogMemberState.SUCCEEDED.value, 0)
            else OperationStatus.PARTIAL
        )
        return OperationResult(
            status=terminal_status,
            result_summary={
                "catalog_count": catalog_count,
                "completed_count": completed_count,
                **dict(sorted(summary.items())),
            },
            retryable=False,
        )

    def _unfinished_member_ids(self, operation_run_id: int) -> list[tuple[str, str]]:
        with self._create_session() as session:
            records = CatalogRefreshRepository(session).unfinished_members(operation_run_id)
            return [
                (record.source_id, record.provider_id)
                for record in records
                if record.lane == CatalogRefreshLane.CONTENT.value
            ]

    def _capability_member_ids(self, operation_run_id: int) -> dict[str, list[str]]:
        with self._create_session() as session:
            records = CatalogRefreshRepository(session).unfinished_members(operation_run_id)
            groups: defaultdict[str, list[str]] = defaultdict(list)
            for record in records:
                if record.lane == CatalogRefreshLane.CAPABILITY.value:
                    groups[record.provider_id].append(record.source_id)
            return dict(groups)

    def _catalog_member_ids(self, operation_run_id: int) -> list[str]:
        with self._create_session() as session:
            return [
                record.source_id
                for record in CatalogRefreshRepository(session).unfinished_members(operation_run_id)
                if record.lane == CatalogRefreshLane.CATALOG.value
            ]

    async def _run_capability_group(
        self, operation_run_id: int, provider_id: str, source_ids: list[str]
    ) -> list[ContentMemberOutcome]:
        provider = next((item for item in self._providers if item.id == provider_id), None)
        if provider is None:
            return [
                self._finish(
                    operation_run_id,
                    source_id,
                    CatalogMemberState.DEGRADED,
                    CatalogResultCode.CATALOG_INCOMPLETE,
                    "来源所属平台未登记，无法完成能力核验",
                    (),
                )
                for source_id in source_ids
            ]
        try:
            result = await self._probe_provider(provider)
        except OperationTimedOut:
            raise
        except Exception:
            result = ProviderProbeResult(
                provider_id=provider.id,
                outcome="failed",
                availability=provider.availability.value,
                reason="Capability check transport failure",
                checked_at=datetime.now(UTC),
                evidence_url=str(provider.docs_url),
            )
        provider_run_id = self._save_provider_probe(operation_run_id, result)
        outcomes: list[ContentMemberOutcome] = []
        for source_id in source_ids:
            state, code, conclusion = self._capability_conclusion(
                operation_run_id, source_id, result
            )
            outcomes.append(
                self._finish_with_provider_probe(
                    operation_run_id, source_id, state, code, conclusion, provider_run_id
                )
            )
        return outcomes

    async def _probe_provider(self, provider: ProviderDefinition) -> ProviderProbeResult:
        if self._provider_probe_factory is not None:
            return await self._provider_probe_factory(provider)
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await ProviderProbe(client).probe(provider)

    def _save_provider_probe(self, operation_run_id: int, result: ProviderProbeResult) -> int:
        with self._create_session() as session:
            record = ProviderRepository(session).save_probe(
                operation_run_id=operation_run_id, **result.model_dump()
            )
            session.commit()
            return record.id

    def _capability_conclusion(
        self, operation_run_id: int, source_id: str, result: ProviderProbeResult
    ) -> tuple[CatalogMemberState, CatalogResultCode | None, str]:
        with self._create_session() as session:
            record = next(
                record
                for record in CatalogRefreshRepository(session).unfinished_members(operation_run_id)
                if record.source_id == source_id
            )
            availability = record.availability_snapshot
            initial = record.result_code
        if (
            initial == CatalogResultCode.MISSING_CREDENTIALS.value
            or availability == "requires_credentials"
        ):
            return (
                CatalogMemberState.BLOCKED,
                CatalogResultCode.MISSING_CREDENTIALS,
                "缺少所需凭据；仅完成平台能力核验，未抓取内容",
            )
        if availability == "requires_approval":
            return (
                CatalogMemberState.BLOCKED,
                CatalogResultCode.REQUIRES_APPROVAL,
                "需要平台审批；仅完成平台能力核验，未抓取内容",
            )
        if availability == "requires_payment":
            return (
                CatalogMemberState.BLOCKED,
                CatalogResultCode.REQUIRES_PAYMENT,
                "需要付费权限；仅完成平台能力核验，未抓取内容",
            )
        if result.outcome == "blocked":
            return (
                CatalogMemberState.BLOCKED,
                CatalogResultCode.REQUIRES_APPROVAL,
                "平台能力访问受限；未抓取内容",
            )
        if result.outcome != "success":
            return (
                CatalogMemberState.FAILED,
                CatalogResultCode.CONNECTION_ERROR,
                "平台能力核验失败；未抓取内容",
            )
        return CatalogMemberState.SUCCEEDED, None, "平台能力核验成功，不代表已获取内容"

    def _finish_with_provider_probe(
        self,
        operation_run_id: int,
        source_id: str,
        state: CatalogMemberState,
        result_code: CatalogResultCode | None,
        conclusion: str,
        provider_probe_run_id: int,
    ) -> ContentMemberOutcome:
        with self._create_session() as session:
            repository = CatalogRefreshRepository(session)
            repository.finish_member(
                operation_run_id,
                source_id,
                state,
                result_code,
                conclusion,
                provider_probe_run_id=provider_probe_run_id,
            )
            session.commit()
        return ContentMemberOutcome(state, result_code, conclusion, ())

    def _run_catalog_member(self, operation_run_id: int, source_id: str) -> ContentMemberOutcome:
        source = self._sources.get(source_id)
        provider = next(
            (item for item in self._providers if source and item.id == source.provider_id), None
        )
        if source is None:
            return self._finish(
                operation_run_id,
                source_id,
                CatalogMemberState.DEGRADED,
                CatalogResultCode.CATALOG_INCOMPLETE,
                "来源定义不存在，无法完成目录核验",
                (),
            )
        validation = validate_catalog_entry(source, provider)
        state = (
            CatalogMemberState.SUCCEEDED
            if validation.code is CatalogResultCode.CATALOG_VERIFIED
            else CatalogMemberState.DEGRADED
        )
        return self._finish(
            operation_run_id, source_id, state, validation.code, validation.conclusion, ()
        )

    async def _run_content_member(
        self,
        operation_run_id: int,
        source_id: str,
        checkpoint: Callable[[str], None],
        deadline: OperationDeadline | None = None,
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
        successful_rounds = 0
        transient_retry_used = False
        while successful_rounds < 3:
            round_number = successful_rounds + 1
            checkpoint(f"before_catalog_content_probe:{source_id}:{round_number}")
            if deadline is not None:
                deadline.check("before_content_probe")
            try:
                result = await self._probe(source, method)
            except Exception:
                return self._finish_internal_error(operation_run_id, source_id)
            checkpoint(f"after_catalog_content_probe:{source_id}:{round_number}")
            code = result_code_for_probe(result)
            probe_run_ids.append(self._save_probe(operation_run_id, result))
            if code in _TRANSIENT_CODES and not transient_retry_used:
                retry_after = _retry_after_seconds(result)
                if deadline is None and retry_after > 0:
                    return self._finish(
                        operation_run_id,
                        source_id,
                        CatalogMemberState.FAILED,
                        code,
                        _conclusion_for_code(code),
                        tuple(probe_run_ids),
                    )
                if deadline is not None and retry_after > deadline.remaining_seconds():
                    return self._finish(
                        operation_run_id,
                        source_id,
                        CatalogMemberState.FAILED,
                        code,
                        _conclusion_for_code(code),
                        tuple(probe_run_ids),
                    )
                transient_retry_used = True
                if retry_after > 0:
                    await asyncio.sleep(retry_after)
                continue
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
            successful_rounds += 1
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


_TRANSIENT_CODES = {
    CatalogResultCode.TIMEOUT,
    CatalogResultCode.CONNECTION_ERROR,
    CatalogResultCode.RATE_LIMITED,
}


def _retry_after_seconds(result: ProbeResult) -> float:
    """Return the server-requested delay; invalid values are deliberately non-blocking."""
    raw = next(
        (
            value
            for key, value in result.response_headers.items()
            if key.lower() == "retry-after"
        ),
        None,
    )
    if raw is None:
        return 0.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            return 0.0
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


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
