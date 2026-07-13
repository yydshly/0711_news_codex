from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

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

    def enriched_manifest(
        self,
        baseline_at: datetime,
        sources: Sequence[SourceDefinition],
        *,
        before_trial_count: int = 16,
    ) -> RemediationManifest:
        """Combine the immutable baseline with the latest bounded validation evidence."""
        manifest = self.manifest(baseline_at)
        source_by_id = {source.id: source for source in sources}
        source_repository = SourceRepository(self.session)
        snapshots = source_repository.latest_probe_snapshots(tuple(source_by_id))
        after_trial_count = sum(
            evaluate_trial_eligibility(source, snapshots.get(source.id)).eligible
            for source in sources
        )
        baseline_ids = tuple(entry.source_id for entry in manifest.entries)
        candidates = self._primary_candidates(baseline_ids)
        candidate_probes = self._latest_candidate_probes(tuple(candidates.values()))
        trial_fetches = self._latest_trial_fetches(baseline_ids)
        entries: list[RemediationEntry] = []
        for entry in manifest.entries:
            source = source_by_id.get(entry.source_id)
            snapshot = snapshots.get(entry.source_id)
            decision = (
                evaluate_trial_eligibility(source, snapshot) if source is not None else None
            )
            candidate = candidates.get(entry.source_id)
            acquisition = candidate_probes.get(candidate.id) if candidate is not None else None
            fetch = trial_fetches.get(entry.source_id)
            evidence = RemediationEvidence(
                candidate_key=candidate.candidate_key if candidate is not None else None,
                candidate_kind=candidate.kind if candidate is not None else None,
                acquisition_outcome=acquisition.outcome if acquisition is not None else None,
                acquisition_sample_count=(
                    acquisition.sample_count if acquisition is not None else None
                ),
                content_outcome=snapshot.outcome if snapshot is not None else None,
                content_sample_count=snapshot.sample_count if snapshot is not None else None,
                field_completeness=(
                    snapshot.field_completeness if snapshot is not None else None
                ),
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
                "before_trial_count": before_trial_count,
                "after_trial_count": after_trial_count,
            }
        )

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
            if fetch is not None and fetch.outcome == "succeeded":
                return "试用抓取已验证"
            return "已符合试用条件，等待抓取验证"
        if acquisition is not None and acquisition.http_status == 429:
            return "受限：HTTP 429；停止自动重试，等待复查窗口"
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
