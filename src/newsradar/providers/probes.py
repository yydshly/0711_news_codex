from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ConfigDict

from .schema import Availability, ProviderDefinition


class ProviderProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str
    probe_type: str = "capability"
    outcome: str
    availability: str
    reason: str
    checked_at: datetime
    latency_ms: float | None = None
    http_status: int | None = None
    evidence_url: str


class ProviderProbe:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def probe(self, provider: ProviderDefinition) -> ProviderProbeResult:
        checked_at = datetime.now(UTC)
        blocked = {
            Availability.REQUIRES_APPROVAL,
            Availability.REQUIRES_PAYMENT,
            Availability.MANUAL_ONLY,
            Availability.UNAVAILABLE,
        }
        if provider.availability in blocked:
            requirements = "; ".join(provider.unlock_requirements) or provider.availability.value
            return self._result(provider, "blocked", requirements, checked_at)
        missing = [name for name in provider.required_env if not os.environ.get(name)]
        if missing:
            return self._result(
                provider,
                "blocked",
                f"Missing required environment variables: {', '.join(missing)}",
                checked_at,
            )
        started = time.perf_counter()
        try:
            response = await self.client.get(
                str(provider.docs_url),
                headers={"User-Agent": "NewsCodexProviderProbe/0.2"},
                follow_redirects=True,
            )
            latency = (time.perf_counter() - started) * 1000
            if response.status_code in {401, 403, 429}:
                outcome = "blocked"
            elif response.is_success:
                outcome = "success"
            else:
                outcome = "failed"
            return self._result(
                provider,
                outcome,
                f"Capability documentation returned HTTP {response.status_code}",
                checked_at,
                latency_ms=latency,
                http_status=response.status_code,
            )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            return self._result(
                provider,
                "failed",
                f"Capability check failed: {type(exc).__name__}",
                checked_at,
                latency_ms=(time.perf_counter() - started) * 1000,
            )

    @staticmethod
    def _result(
        provider: ProviderDefinition,
        outcome: str,
        reason: str,
        checked_at: datetime,
        *,
        latency_ms: float | None = None,
        http_status: int | None = None,
    ) -> ProviderProbeResult:
        return ProviderProbeResult(
            provider_id=provider.id,
            outcome=outcome,
            availability=provider.availability.value,
            reason=reason,
            checked_at=checked_at,
            latency_ms=latency_ms,
            http_status=http_status,
            evidence_url=str(provider.docs_url),
        )


async def probe_providers(
    providers: list[ProviderDefinition], client: httpx.AsyncClient
) -> dict[str, ProviderProbeResult]:
    probe = ProviderProbe(client)
    values = await asyncio.gather(*(probe.probe(provider) for provider in providers))
    return {result.provider_id: result for result in values}
