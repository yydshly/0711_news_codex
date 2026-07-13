from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    SourceAccessMethodRecord,
    SourceDefinitionRecord,
    SourceProbeRunRecord,
    SourceRiskAssessmentRecord,
)

from .classifier import classify_probe, explanation
from .schema import RemediationEntry, RemediationManifest

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
