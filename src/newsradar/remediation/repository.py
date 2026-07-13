from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    FetchRunRecord,
    OperationRunRecord,
    SourceAccessMethodRecord,
    SourceAcquisitionCandidateRecord,
    SourceAcquisitionProbeRunRecord,
    SourceDefinitionRecord,
    SourceProbeRunRecord,
    SourceProbeSampleRecord,
    SourceRemediationBatchRecord,
    SourceRemediationMemberRecord,
    SourceRiskAssessmentRecord,
)
from newsradar.ingestion.trial import evaluate_trial_eligibility
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import SourceDefinition

from .classifier import classify_probe, explanation
from .schema import RemediationEntry, RemediationEvidence, RemediationManifest

_SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie"}


class RemediationRepository:
    """Build a stable baseline view without changing probe or source history."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def manifest(self, baseline_at: datetime) -> RemediationManifest:
        frozen = self.frozen_manifest(baseline_at)
        if frozen is not None:
            return frozen
        return self._build_manifest(baseline_at)

    def _build_manifest(self, baseline_at: datetime) -> RemediationManifest:
        source_ids = self.session.scalars(select(SourceDefinitionRecord.id)).all()
        entries: list[RemediationEntry] = []
        for source_id in sorted(source_ids):
            run = self.session.scalar(
                select(SourceProbeRunRecord)
                .where(
                    SourceProbeRunRecord.source_id == source_id,
                    SourceProbeRunRecord.finished_at <= baseline_at,
                )
                .order_by(SourceProbeRunRecord.finished_at.desc(), SourceProbeRunRecord.id.desc())
                .limit(1)
            )
            if run is None or run.outcome == "success":
                continue
            source = self.session.get(SourceDefinitionRecord, source_id)
            if source is None or not self._is_trial_failure_candidate(source):
                continue
            category = classify_probe(run)
            reason_zh, next_action_zh = explanation(category)
            entries.append(
                RemediationEntry(
                    source_id=source.id,
                    source_name=source.name,
                    original_probe_id=run.id,
                    original_finished_at=run.finished_at,
                    category=category,
                    reason_zh=reason_zh,
                    next_action_zh=next_action_zh,
                    access_url=run.access_url,
                )
            )
        return RemediationManifest(baseline_at=baseline_at, entries=tuple(entries))

    def freeze_manifest(
        self,
        baseline_at: datetime,
        sources: Sequence[SourceDefinition] = (),
        *,
        before_trial_count: int | None = None,
    ) -> RemediationManifest:
        """Persist the batch membership and classification once, then return snapshots only."""
        frozen = self.frozen_manifest(baseline_at)
        if frozen is not None:
            return frozen
        current = self._build_manifest(baseline_at)
        if before_trial_count is None and sources:
            snapshots = SourceRepository(self.session).latest_probe_snapshots(
                [source.id for source in sources], finished_at_lte=baseline_at
            )
            before_trial_count = sum(
                evaluate_trial_eligibility(source, snapshots.get(source.id)).eligible
                for source in sources
            )
        batch = SourceRemediationBatchRecord(
            baseline_at=baseline_at, before_trial_count=before_trial_count
        )
        self.session.add(batch)
        self.session.flush()
        records = {
            record.id: record
            for record in self.session.scalars(
                select(SourceDefinitionRecord).where(
                    SourceDefinitionRecord.id.in_([entry.source_id for entry in current.entries])
                )
            )
        }
        for entry in current.entries:
            source = records[entry.source_id]
            self.session.add(
                SourceRemediationMemberRecord(
                    batch_id=batch.id,
                    source_id=entry.source_id,
                    source_name=entry.source_name,
                    provider_id=source.provider_id,
                    definition_hash=source.definition_hash,
                    original_probe_id=entry.original_probe_id,
                    original_finished_at=entry.original_finished_at,
                    category=entry.category.value,
                    reason_zh=entry.reason_zh,
                    next_action_zh=entry.next_action_zh,
                    access_url=entry.access_url,
                )
            )
        self.session.commit()
        return self.frozen_manifest(baseline_at) or current

    def frozen_manifest(self, baseline_at: datetime) -> RemediationManifest | None:
        batch = self.session.scalar(
            select(SourceRemediationBatchRecord).where(
                SourceRemediationBatchRecord.baseline_at == baseline_at
            )
        )
        if batch is None:
            return None
        members = self.session.scalars(
            select(SourceRemediationMemberRecord)
            .where(SourceRemediationMemberRecord.batch_id == batch.id)
            .order_by(SourceRemediationMemberRecord.source_id)
        ).all()
        return RemediationManifest(
            baseline_at=batch.baseline_at.astimezone(UTC),
            before_trial_count=batch.before_trial_count,
            entries=tuple(
                RemediationEntry(
                    source_id=member.source_id,
                    source_name=member.source_name,
                    original_probe_id=member.original_probe_id,
                    original_finished_at=member.original_finished_at,
                    category=member.category,
                    reason_zh=member.reason_zh,
                    next_action_zh=member.next_action_zh,
                    access_url=member.access_url,
                )
                for member in members
            ),
        )

    def latest_frozen_manifest(self) -> RemediationManifest | None:
        baseline = self.session.scalar(
            select(SourceRemediationBatchRecord.baseline_at)
            .order_by(SourceRemediationBatchRecord.baseline_at.desc())
            .limit(1)
        )
        return self.frozen_manifest(baseline) if baseline is not None else None

    def enriched_manifest(
        self,
        baseline_at: datetime,
        sources: Sequence[SourceDefinition],
        *,
        before_trial_count: int | None = None,
    ) -> RemediationManifest:
        """Combine the immutable baseline with the latest bounded validation evidence."""
        manifest = self.frozen_manifest(baseline_at)
        if manifest is None:
            raise ValueError("remediation_batch_not_frozen")
        source_by_id = {source.id: source for source in sources}
        source_repository = SourceRepository(self.session)
        snapshots = source_repository.latest_probe_snapshots(tuple(source_by_id))
        after_trial_count = sum(
            evaluate_trial_eligibility(source, snapshots.get(source.id)).eligible
            for source in sources
        )
        linked = self._linked_candidate_probes(manifest.entries)
        entries: list[RemediationEntry] = []
        for entry in manifest.entries:
            source = source_by_id.get(entry.source_id)
            candidate, acquisition = linked.get(entry.source_id, (None, None))
            snapshot = self._content_snapshot_after(
                entry.source_id,
                acquisition,
            )
            decision = evaluate_trial_eligibility(source, snapshot) if source is not None else None
            fetch = self._trial_fetch_after(entry.source_id, snapshot)
            evidence = RemediationEvidence(
                candidate_key=candidate.candidate_key if candidate is not None else None,
                candidate_kind=candidate.kind if candidate is not None else None,
                acquisition_outcome=acquisition.outcome if acquisition is not None else None,
                acquisition_sample_count=(
                    acquisition.sample_count if acquisition is not None else None
                ),
                acquisition_http_status=(
                    acquisition.http_status if acquisition is not None else None
                ),
                retry_after_seconds=(
                    acquisition.retry_after_seconds if acquisition is not None else None
                ),
                earliest_recheck_at=(
                    acquisition.earliest_recheck_at if acquisition is not None else None
                ),
                content_outcome=snapshot.outcome if snapshot is not None else None,
                content_sample_count=snapshot.sample_count if snapshot is not None else None,
                field_completeness=(snapshot.field_completeness if snapshot is not None else None),
                trial_eligible=decision.eligible if decision is not None else None,
                trial_reason_zh=decision.reason if decision is not None else None,
                fetch_outcome=fetch.outcome if fetch is not None else None,
                fetch_items_received=fetch.items_received if fetch is not None else None,
                fetch_items_inserted=fetch.items_inserted if fetch is not None else None,
                html_research_status=(
                    "仅研究，不进入 RawItem"
                    if candidate is not None and candidate.kind == "html"
                    else "不涉及（RSS/API 主路径）"
                ),
                final_conclusion_zh=self._final_conclusion(decision, acquisition, fetch),
            )
            entries.append(entry.model_copy(update={"evidence": evidence}))
        return manifest.model_copy(
            update={
                "entries": tuple(entries),
                "before_trial_count": manifest.before_trial_count,
                "after_trial_count": after_trial_count,
            }
        )

    def _linked_candidate_probes(
        self, entries: tuple[RemediationEntry, ...]
    ) -> dict[str, tuple[SourceAcquisitionCandidateRecord, SourceAcquisitionProbeRunRecord]]:
        if not entries:
            return {}
        by_original = {entry.original_probe_id: entry for entry in entries}
        probes = self.session.scalars(
            select(SourceAcquisitionProbeRunRecord)
            .where(
                SourceAcquisitionProbeRunRecord.original_probe_id.in_(by_original),
                SourceAcquisitionProbeRunRecord.operation_run_id.is_not(None),
            )
            .order_by(
                SourceAcquisitionProbeRunRecord.completed_at.desc(),
                SourceAcquisitionProbeRunRecord.id.desc(),
            )
        ).all()
        candidate_ids = {probe.candidate_id for probe in probes}
        candidates = {
            candidate.id: candidate
            for candidate in self.session.scalars(
                select(SourceAcquisitionCandidateRecord).where(
                    SourceAcquisitionCandidateRecord.id.in_(candidate_ids)
                )
            )
        }
        operation_ids = {probe.operation_run_id for probe in probes if probe.operation_run_id}
        operations = {
            operation.id: operation
            for operation in self.session.scalars(
                select(OperationRunRecord).where(OperationRunRecord.id.in_(operation_ids))
            )
        }
        linked: dict[
            str, tuple[SourceAcquisitionCandidateRecord, SourceAcquisitionProbeRunRecord]
        ] = {}
        for probe in probes:
            entry = by_original.get(probe.original_probe_id)
            candidate = candidates.get(probe.candidate_id)
            operation = operations.get(probe.operation_run_id)
            scope = operation.requested_scope if operation is not None else {}
            if (
                entry is None
                or candidate is None
                or candidate.source_id != entry.source_id
                or scope.get("source_id") != entry.source_id
                or scope.get("candidate_key") != candidate.candidate_key
                or scope.get("original_probe_id") != entry.original_probe_id
            ):
                continue
            linked.setdefault(entry.source_id, (candidate, probe))
        return linked

    def _content_snapshot_after(
        self,
        source_id: str,
        acquisition: SourceAcquisitionProbeRunRecord | None,
    ):
        if acquisition is None or acquisition.completed_at is None:
            return None
        run = self.session.scalar(
            select(SourceProbeRunRecord)
            .where(
                SourceProbeRunRecord.source_id == source_id,
                SourceProbeRunRecord.remediation_acquisition_probe_id == acquisition.id,
                SourceProbeRunRecord.finished_at >= acquisition.completed_at,
            )
            .order_by(SourceProbeRunRecord.finished_at.desc(), SourceProbeRunRecord.id.desc())
            .limit(1)
        )
        if run is None:
            return None
        fields: set[str] = set()
        for row in self.session.scalars(
            select(SourceProbeSampleRecord).where(SourceProbeSampleRecord.probe_run_id == run.id)
        ):
            fields.update(row.fields_present)
        from newsradar.ingestion.trial import ProbeSnapshot

        return ProbeSnapshot(
            probe_run_id=run.id,
            outcome=run.outcome,
            sample_count=int(run.metrics.get("sample_count") or 0),
            field_completeness=float(run.metrics.get("field_completeness") or 0.0),
            sample_fields=frozenset(fields),
            finished_at=run.finished_at,
        )

    def _trial_fetch_after(self, source_id: str, snapshot) -> FetchRunRecord | None:
        if snapshot is None or snapshot.probe_run_id is None:
            return None
        fetches = self.session.scalars(
            select(FetchRunRecord)
            .where(
                FetchRunRecord.source_id == source_id,
                FetchRunRecord.started_at >= snapshot.finished_at,
                FetchRunRecord.operation_run_id.is_not(None),
            )
            .order_by(FetchRunRecord.id.desc())
        ).all()
        for fetch in fetches:
            operation = self.session.get(OperationRunRecord, fetch.operation_run_id)
            scope = operation.requested_scope if operation is not None else {}
            if (
                operation is not None
                and operation.operation_type == "fetch"
                and operation.status == "succeeded"
                and scope.get("source_id") == source_id
                and bool(scope.get("trial"))
                and scope.get("remediation_content_probe_id") == snapshot.probe_run_id
            ):
                return fetch
        return None

    def _primary_candidates(
        self, source_ids: tuple[str, ...]
    ) -> dict[str, SourceAcquisitionCandidateRecord]:
        if not source_ids:
            return {}
        records = self.session.scalars(
            select(SourceAcquisitionCandidateRecord)
            .where(
                SourceAcquisitionCandidateRecord.source_id.in_(source_ids),
                SourceAcquisitionCandidateRecord.is_current.is_(True),
                SourceAcquisitionCandidateRecord.decision == "primary",
            )
            .order_by(SourceAcquisitionCandidateRecord.id)
        ).all()
        return {record.source_id: record for record in records}

    def _latest_candidate_probes(
        self, candidates: tuple[SourceAcquisitionCandidateRecord, ...]
    ) -> dict[int, SourceAcquisitionProbeRunRecord]:
        candidate_ids = tuple(candidate.id for candidate in candidates)
        if not candidate_ids:
            return {}
        records = self.session.scalars(
            select(SourceAcquisitionProbeRunRecord)
            .where(SourceAcquisitionProbeRunRecord.candidate_id.in_(candidate_ids))
            .order_by(
                SourceAcquisitionProbeRunRecord.completed_at.desc(),
                SourceAcquisitionProbeRunRecord.id.desc(),
            )
        ).all()
        latest: dict[int, SourceAcquisitionProbeRunRecord] = {}
        for record in records:
            latest.setdefault(record.candidate_id, record)
        return latest

    def _latest_trial_fetches(self, source_ids: tuple[str, ...]) -> dict[str, FetchRunRecord]:
        if not source_ids:
            return {}
        fetches = self.session.scalars(
            select(FetchRunRecord)
            .where(FetchRunRecord.source_id.in_(source_ids))
            .order_by(FetchRunRecord.id.desc())
        ).all()
        operation_ids = tuple(
            fetch.operation_run_id for fetch in fetches if fetch.operation_run_id is not None
        )
        operations = (
            self.session.scalars(
                select(OperationRunRecord).where(OperationRunRecord.id.in_(operation_ids))
            ).all()
            if operation_ids
            else []
        )
        operation_by_id = {operation.id: operation for operation in operations}
        latest: dict[str, FetchRunRecord] = {}
        for fetch in fetches:
            operation = operation_by_id.get(fetch.operation_run_id)
            if operation is None or not bool((operation.requested_scope or {}).get("trial")):
                continue
            latest.setdefault(fetch.source_id, fetch)
        return latest

    @staticmethod
    def _final_conclusion(decision, acquisition, fetch: FetchRunRecord | None) -> str:
        if decision is not None and decision.eligible:
            if fetch is not None and fetch.outcome in {"succeeded", "no_change"}:
                return "试用抓取已验证"
            return "已符合试用条件，等待抓取验证"
        if acquisition is not None and acquisition.http_status == 429:
            if acquisition.earliest_recheck_at is not None:
                return (
                    "受限：HTTP 429；停止自动重试；最早复查时间 "
                    f"{acquisition.earliest_recheck_at.isoformat()}"
                )
            return "受限：HTTP 429；服务未提供 Retry-After，需人工择期复查"
        if acquisition is not None and acquisition.http_status == 403:
            return "受限：HTTP 403；未自动重试，等待额度或权限复查"
        if decision is not None:
            return f"暂不试用：{decision.reason}"
        return "审核目录或运行证据不完整"

    def _is_trial_failure_candidate(self, source: SourceDefinitionRecord) -> bool:
        """Apply the same pre-probe gates as the source trial baseline."""
        if source.coverage_mode != "direct" or source.availability != "ready":
            return False
        risk = self.session.scalar(
            select(SourceRiskAssessmentRecord)
            .where(SourceRiskAssessmentRecord.source_id == source.id)
            .order_by(
                SourceRiskAssessmentRecord.assessed_at.desc(),
                SourceRiskAssessmentRecord.id.desc(),
            )
            .limit(1)
        )
        if risk is not None and risk.hard_block_reason:
            return False
        methods = self.session.scalars(
            select(SourceAccessMethodRecord)
            .where(SourceAccessMethodRecord.source_id == source.id)
            .order_by(SourceAccessMethodRecord.priority)
        ).all()
        return any(
            method.kind != "html"
            and not method.requires_manual_approval
            and not (method.auth_envs or ([method.auth_env] if method.auth_env else []))
            and not (_SENSITIVE_HEADERS & {name.lower() for name in (method.headers or {})})
            for method in methods
        )
