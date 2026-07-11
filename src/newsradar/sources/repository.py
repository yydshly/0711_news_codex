from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from newsradar.ai.minimax import ModelUsage
from newsradar.db.models import (
    ModelUsageRecord,
    SourceAccessMethodRecord,
    SourceDefinitionRecord,
    SourceDefinitionVersion,
    SourceProbeRunRecord,
    SourceProbeSampleRecord,
    SourceRiskAssessmentRecord,
)
from newsradar.sources.probes.base import ProbeResult

from .schema import SourceDefinition, SourceStatus


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
                unchanged += 1
                continue

            if current is None:
                current = SourceDefinitionRecord(id=source.id)
                self.session.add(current)
                created += 1
            else:
                updated += 1
                current.access_methods.clear()
                self.session.flush()

            current.name = source.name
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

            for method in source.access_methods:
                current.access_methods.append(
                    SourceAccessMethodRecord(
                        kind=method.kind.value,
                        url=str(method.url),
                        priority=method.priority,
                        requires_manual_approval=method.requires_manual_approval,
                        auth_env=method.auth_env,
                        headers=method.headers,
                        params=method.params,
                    )
                )

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
