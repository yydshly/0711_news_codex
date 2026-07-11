from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

from newsradar.db.models import (
    ProviderDefinitionRecord,
    ProviderDefinitionVersion,
    ProviderProbeRunRecord,
)
from newsradar.sources.repository import SyncResult

from .schema import ProviderDefinition


def canonical_provider(provider: ProviderDefinition) -> tuple[dict, str]:
    payload = provider.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ProviderRepository:
    def __init__(self, session: Session):
        self.session = session

    def sync(self, providers: list[ProviderDefinition]) -> SyncResult:
        created = updated = unchanged = 0
        for provider in providers:
            payload, definition_hash = canonical_provider(provider)
            record = self.session.get(ProviderDefinitionRecord, provider.id)
            if record is not None and record.definition_hash == definition_hash:
                unchanged += 1
                continue
            if record is None:
                record = ProviderDefinitionRecord(id=provider.id)
                self.session.add(record)
                created += 1
            else:
                updated += 1
            record.name = provider.name
            record.category = provider.category.value
            record.homepage = str(provider.homepage)
            record.docs_url = str(provider.docs_url)
            record.terms_url = str(provider.terms_url)
            record.auth_mode = provider.auth_mode.value
            record.cost_tier = provider.cost_tier.value
            record.availability = provider.availability.value
            record.capabilities = provider.capabilities
            record.required_env = provider.required_env
            record.reviewed_at = provider.reviewed_at
            record.evidence = [str(url) for url in provider.evidence]
            record.unlock_requirements = provider.unlock_requirements
            record.notes = provider.notes
            record.definition_hash = definition_hash
            self.session.add(
                ProviderDefinitionVersion(
                    provider_id=provider.id,
                    definition_hash=definition_hash,
                    definition=payload,
                )
            )
        self.session.flush()
        return SyncResult(created=created, updated=updated, unchanged=unchanged)

    def save_probe(
        self,
        *,
        provider_id: str,
        outcome: str,
        availability: str,
        reason: str,
        checked_at: datetime,
        latency_ms: float | None,
        http_status: int | None,
        evidence_url: str,
    ) -> ProviderProbeRunRecord:
        record = ProviderProbeRunRecord(
            provider_id=provider_id,
            probe_type="capability",
            outcome=outcome,
            availability=availability,
            reason=reason,
            checked_at=checked_at,
            latency_ms=latency_ms,
            http_status=http_status,
            evidence_url=evidence_url,
        )
        self.session.add(record)
        self.session.flush()
        return record
