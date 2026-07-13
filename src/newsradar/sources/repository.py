from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    ModelUsageRecord,
    SourceAccessMethodRecord,
    SourceAcquisitionCandidateRecord,
    SourceAcquisitionProbeRunRecord,
    SourceDefinitionRecord,
    SourceDefinitionVersion,
    SourceFetchStateRecord,
    SourceProbeRunRecord,
    SourceProbeSampleRecord,
    SourceResearchProfileRecord,
    SourceRiskAssessmentRecord,
    utcnow,
)
from newsradar.operations.logging import redact
from newsradar.sources.probes.base import ProbeResult

from .schema import SourceDefinition, SourceStatus

_SENSITIVE_DETAIL_KEY = re.compile(
    r"(?i)(authorization|cookie|api[_-]?key|access_token|refresh_token|token|client_secret|secret|password)"
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)\b(access_token|refresh_token|client_secret)\s*[=:]\s*[^\s,&;]+"
)


def _sanitize_research_details(value: object) -> object:
    """Drop credentials before persisting exploratory probe diagnostics."""
    if isinstance(value, dict):
        return {
            str(key): _sanitize_research_details(item)
            for key, item in value.items()
            if not _SENSITIVE_DETAIL_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [_sanitize_research_details(item) for item in value]
    if isinstance(value, str):
        parsed = urlsplit(value)
        if (
            parsed.username
            or parsed.password
            or any(_SENSITIVE_DETAIL_KEY.search(key) for key, _ in parse_qsl(parsed.query))
        ):
            return "[redacted credential URL]"
        return _SENSITIVE_VALUE.sub("[REDACTED]", redact(value))
    return value


@dataclass(frozen=True)
class SyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0


def canonical_definition(source: SourceDefinition) -> tuple[dict, str]:
    payload = source.model_dump(mode="json", exclude={"total_risk"})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SourceRepository:
    def __init__(self, session: Session):
        self.session = session

    def sync(self, sources: list[SourceDefinition]) -> SyncResult:
        created = updated = unchanged = 0
        for source in sources:
            payload, definition_hash = canonical_definition(source)
            current = self.session.get(SourceDefinitionRecord, source.id)
            if current is not None and current.definition_hash == definition_hash:
                self._sync_research_projection(current, source)
                unchanged += 1
                continue

            if current is None:
                current = SourceDefinitionRecord(id=source.id)
                self.session.add(current)
                created += 1
            else:
                updated += 1

            existing_methods = {method.priority: method for method in current.access_methods}

            current.name = source.name
            current.provider_id = source.provider_id
            current.target_type = source.target_type.value
            current.availability = source.availability.value
            current.coverage_mode = source.coverage_mode.value
            current.official_identity_url = (
                str(source.official_identity_url) if source.official_identity_url else None
            )
            current.reviewed_at = source.reviewed_at
            current.unlock_requirements = source.unlock_requirements
            if current.status is None or current.status == SourceStatus.CANDIDATE.value:
                current.status = (
                    SourceStatus.CANDIDATE.value
                    if source.status == SourceStatus.ACTIVE
                    else source.status.value
                )
            current.nature = source.nature.value
            current.language = source.language
            current.roles = [role.value for role in source.roles]
            current.topics = source.topics
            current.authority_score = source.authority_score
            current.poll_interval_minutes = source.poll_interval_minutes
            current.expected_fields = [field.value for field in source.expected_fields]
            current.notes = source.notes
            current.definition_hash = definition_hash

            self._sync_research_projection(current, source)

            for method in source.access_methods:
                record = existing_methods.pop(method.priority, None)
                if record is None:
                    record = SourceAccessMethodRecord(priority=method.priority)
                    current.access_methods.append(record)
                record.kind = method.kind.value
                record.url = str(method.url)
                record.requires_manual_approval = method.requires_manual_approval
                record.auth_env = method.auth_env
                record.auth_envs = list(method.auth_envs)
                record.headers = method.headers
                record.params = method.params

            for obsolete in existing_methods.values():
                self.session.execute(
                    delete(SourceFetchStateRecord).where(
                        SourceFetchStateRecord.access_method_id == obsolete.id
                    )
                )
                current.access_methods.remove(obsolete)

            version_exists = self.session.scalar(
                select(SourceDefinitionVersion.id).where(
                    SourceDefinitionVersion.source_id == source.id,
                    SourceDefinitionVersion.definition_hash == definition_hash,
                )
            )
            if version_exists is None:
                self.session.add(
                    SourceDefinitionVersion(
                        source=current,
                        definition_hash=definition_hash,
                        definition=payload,
                    )
                )
            self.session.add(
                SourceRiskAssessmentRecord(
                    source=current,
                    terms=source.risk.terms,
                    authentication=source.risk.authentication,
                    stability=source.risk.stability,
                    data_quality=source.risk.data_quality,
                    operating_cost=source.risk.operating_cost,
                    total=source.total_risk,
                    evidence=[str(url) for url in source.risk.evidence],
                    hard_block_reason=source.risk.hard_block_reason,
                )
            )

        self.session.flush()
        return SyncResult(created=created, updated=updated, unchanged=unchanged)

    def sync_source(self, source: SourceDefinition) -> SyncResult:
        """Synchronize one YAML source without committing the caller's transaction."""
        return self.sync([source])

    def _sync_research_projection(
        self, current: SourceDefinitionRecord, source: SourceDefinition
    ) -> None:
        research = source.research
        profile = current.research_profile
        if profile is None:
            profile = SourceResearchProfileRecord(source=current)
            self.session.add(profile)
        profile.status = research.status.value
        profile.wanted_information = list(research.wanted_information)
        profile.conclusion = research.conclusion
        profile.no_fallback_reason = research.no_fallback_reason
        profile.reviewed_at = research.reviewed_at

        existing = {
            candidate.candidate_key: candidate for candidate in current.acquisition_candidates
        }
        for candidate in research.candidates:
            record = existing.pop(candidate.key, None)
            if record is None:
                record = SourceAcquisitionCandidateRecord(candidate_key=candidate.key)
                current.acquisition_candidates.append(record)
            record.kind = candidate.kind.value
            record.implementation = candidate.implementation.value
            record.officiality = candidate.officiality.value
            record.authentication = candidate.authentication.value
            record.roles = [role.value for role in candidate.roles]
            record.fields = list(candidate.fields)
            record.limitations = list(candidate.limitations)
            record.evidence = [str(url) for url in candidate.evidence]
            record.sample_status = candidate.sample_status.value
            record.decision = candidate.decision.value
            record.reviewed_at = candidate.reviewed_at
            record.is_current = True
            record.removed_at = None

        for obsolete in existing.values():
            obsolete.is_current = False
            obsolete.removed_at = utcnow()

    def current_acquisition_candidates(
        self, source_id: str
    ) -> list[SourceAcquisitionCandidateRecord]:
        return list(
            self.session.scalars(
                select(SourceAcquisitionCandidateRecord)
                .where(
                    SourceAcquisitionCandidateRecord.source_id == source_id,
                    SourceAcquisitionCandidateRecord.is_current.is_(True),
                )
                .order_by(SourceAcquisitionCandidateRecord.id)
            )
        )

    def save_acquisition_probe_run(
        self,
        *,
        candidate_id: int,
        started_at,
        completed_at,
        outcome: str,
        http_status: int | None = None,
        latency_ms: float | None = None,
        fields_present: list[str] | None = None,
        sample_count: int | None = None,
        latest_published_at=None,
        schema_fingerprint: str | None = None,
        error_code: str | None = None,
        details: dict | None = None,
    ) -> SourceAcquisitionProbeRunRecord:
        record = SourceAcquisitionProbeRunRecord(
            candidate_id=candidate_id,
            started_at=started_at,
            completed_at=completed_at,
            outcome=outcome,
            http_status=http_status,
            latency_ms=latency_ms,
            fields_present=fields_present or [],
            sample_count=sample_count,
            latest_published_at=latest_published_at,
            schema_fingerprint=schema_fingerprint,
            error_code=error_code,
            details=_sanitize_research_details(details or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def save_probe_result(self, result: ProbeResult) -> SourceProbeRunRecord:
        metrics = {
            "content_type": result.content_type,
            "content_length": result.content_length,
            "etag": result.etag,
            "last_modified": result.last_modified,
            "cache_control": result.cache_control,
            "rate_limit_remaining": result.rate_limit_remaining,
            "rate_limit_reset": result.rate_limit_reset,
            "pagination_detected": result.pagination_detected,
            "sample_count": result.sample_count,
            "duplicate_ratio": result.duplicate_ratio,
            "field_completeness": result.field_completeness,
            "latest_published_at": result.latest_published_at.isoformat()
            if result.latest_published_at
            else None,
            "cross_domain_redirect": result.cross_domain_redirect,
        }
        record = SourceProbeRunRecord(
            source_id=result.source_id,
            access_kind=result.access_kind,
            access_url=result.access_url,
            outcome=result.outcome.value,
            started_at=result.started_at,
            finished_at=result.finished_at,
            latency_ms=result.latency_ms,
            http_status=result.http_status,
            final_url=result.final_url,
            response_headers={
                key: value
                for key, value in result.model_dump(mode="json").get("response_headers", {}).items()
                if key.lower() not in {"authorization", "cookie", "set-cookie"}
            },
            metrics=metrics,
            schema_fingerprint=result.schema_fingerprint,
            suggested_status=result.suggested_status.value,
            reason=result.reason,
            error_code=result.error_code,
        )
        self.session.add(record)
        self.session.flush()
        for index, sample in enumerate(result.samples):
            payload = sample.model_dump(mode="json")
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            self.session.add(
                SourceProbeSampleRecord(
                    probe_run_id=record.id,
                    sample_index=index,
                    canonical_url=sample.canonical_url,
                    published_at=sample.published_at,
                    fields_present=sorted(sample.fields_present()),
                    sample_hash=hashlib.sha256(encoded.encode()).hexdigest(),
                )
            )
        self.session.flush()
        return record

    def save_model_usage(self, usage: ModelUsage) -> ModelUsageRecord:
        record = ModelUsageRecord(
            purpose=usage.purpose,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            outcome=usage.outcome,
            error=usage.error,
        )
        self.session.add(record)
        self.session.flush()
        return record
