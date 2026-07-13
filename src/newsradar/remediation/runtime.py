"""Bounded, research-only worker execution for one failed source probe."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import Protocol

from sqlalchemy.orm import Session

from newsradar.db.models import SourceProbeRunRecord
from newsradar.operations.deadlines import OperationDeadline, OperationTimedOut
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import OperationResult
from newsradar.research.probes.factory import OwnedResearchProbe, research_probe_for
from newsradar.research.probes.schema import AcquisitionProbeOutcome, AcquisitionProbeResult
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import (
    AcquisitionAuth,
    AcquisitionCandidate,
    AcquisitionDecision,
    SourceDefinition,
)


class ProbeFactory(Protocol):
    def __call__(
        self, source: SourceDefinition, candidate: AcquisitionCandidate
    ) -> OwnedResearchProbe: ...


class SourceRemediationHandler:
    """Probe exactly one audited candidate and retain only research evidence.

    This handler intentionally has no ingestion dependency: a successful remediation
    is evidence that a candidate can be investigated, never authorization to fetch
    production news or create a RawItem.
    """

    def __init__(
        self,
        sources: Iterable[SourceDefinition],
        create_session: Callable[[], Session],
        probe_factory: ProbeFactory = research_probe_for,
    ) -> None:
        self._sources = {source.id: source for source in sources}
        self._create_session = create_session
        self._probe_factory = probe_factory

    @classmethod
    def production(
        cls, sources: Iterable[SourceDefinition], create_session: Callable[[], Session]
    ) -> SourceRemediationHandler:
        return cls(sources, create_session)

    def __call__(
        self, lease: OperationLease, checkpoint: Callable[[str], None]
    ) -> OperationResult:
        if lease.operation_type != OperationType.SOURCE_REMEDIATION.value:
            return _failed("unsupported_operation_type", "修复 Worker 只处理来源修复操作。")
        source_id = lease.requested_scope.get("source_id")
        candidate_key = lease.requested_scope.get("candidate_key")
        original_probe_id = lease.requested_scope.get("original_probe_id")
        if (
            not isinstance(source_id, str)
            or not source_id
            or not isinstance(candidate_key, str)
            or not candidate_key
            or not isinstance(original_probe_id, int)
            or original_probe_id <= 0
        ):
            return _failed(
                "invalid_source_remediation_scope", "修复操作缺少不可变的来源或基线探测信息。"
            )
        source = self._sources.get(source_id)
        if source is None:
            return _failed("unknown_source", "当前审核目录中不存在该来源。")
        candidate = next(
            (item for item in source.research.candidates if item.key == candidate_key), None
        )
        if candidate is None:
            return _failed("unknown_acquisition_candidate", "当前审核目录中不存在该候选获取方式。")
        if candidate.authentication != AcquisitionAuth.NONE:
            return _failed(
                "candidate_requires_credentials", "候选方式需要凭据或审批，未发起网络请求。"
            )
        if candidate.decision == AcquisitionDecision.REJECTED:
            return _failed("candidate_rejected", "候选方式已被审核拒绝，未发起网络请求。")
        try:
            deadline = OperationDeadline.from_scope(lease.requested_scope)
            deadline.check("before_remediation")
        except (OperationTimedOut, ValueError) as error:
            return _failed("operation_timeout", str(error))
        # Validate immutable evidence in a short database interaction before network I/O.
        with self._create_session() as session:
            original = session.get(SourceProbeRunRecord, original_probe_id)
            if original is None or original.source_id != source_id:
                return _failed(
                    "original_probe_not_found", "基线探测记录不属于该来源，未发起网络请求。"
                )
            records = SourceRepository(session).current_acquisition_candidates(source_id)
            candidate_record = next(
                (record for record in records if record.candidate_key == candidate_key), None
            )
            if candidate_record is None:
                return _failed(
                    "candidate_projection_not_found", "候选方式尚未同步到审核投影，未发起网络请求。"
                )
            candidate_record_id = candidate_record.id
        checkpoint("before_remediation_probe")
        try:
            result = asyncio.run(_run_probe(self._probe_factory, source, candidate))
        except Exception:
            return _failed("remediation_probe_failed", "受控候选探测未完成，未安排自动重试。")
        checkpoint("after_remediation_probe")
        try:
            deadline.check("after_remediation")
        except OperationTimedOut as error:
            return _failed("operation_timeout", str(error))
        # Persist only the bounded research result in a new, short transaction.
        with self._create_session() as session:
            SourceRepository(session).save_acquisition_probe_run(
                candidate_id=candidate_record_id,
                started_at=result.started_at,
                completed_at=result.finished_at,
                outcome=result.outcome.value,
                http_status=result.http_status,
                latency_ms=result.latency_ms,
                fields_present=result.fields_present,
                sample_count=result.sample_count,
                latest_published_at=result.latest_published_at,
                schema_fingerprint=result.schema_fingerprint,
                error_code=result.error_code,
                details=result.model_dump(mode="json"),
            )
            session.commit()
        summary = {
            "source_id": source_id,
            "candidate_key": candidate_key,
            "original_probe_id": original_probe_id,
            "outcome": result.outcome.value,
            "sample_count": result.sample_count,
            "category": _result_category(result),
        }
        if result.outcome == AcquisitionProbeOutcome.SUCCEEDED:
            return OperationResult(result_summary=summary, retryable=False)
        return OperationResult(
            status=OperationStatus.PARTIAL,
            error_code=result.error_code,
            error_message=result.reason_zh,
            result_summary=summary,
            retryable=False,
        )


async def _run_probe(
    probe_factory: ProbeFactory, source: SourceDefinition, candidate: AcquisitionCandidate
) -> AcquisitionProbeResult:
    async with probe_factory(source, candidate) as probe:
        return await probe.probe(source, candidate, limit=5)


def _failed(error_code: str, error_message: str) -> OperationResult:
    return OperationResult(
        status=OperationStatus.FAILED,
        error_code=error_code,
        error_message=error_message,
        retryable=False,
    )


def _result_category(result: AcquisitionProbeResult) -> str:
    """Expose only a deterministic retry category, never raw probe diagnostics."""
    code = (result.error_code or "").lower()
    if result.http_status is not None and result.http_status >= 500:
        return "network_transient"
    if any(marker in code for marker in ("timeout", "dns", "tls", "network", "connection")):
        return "network_transient"
    return "unknown"
