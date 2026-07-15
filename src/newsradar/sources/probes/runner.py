from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from newsradar.sources.schema import SourceDefinition

from .base import ProbeOutcome, ProbeResult
from .factory import ProbeFactory


class ProbeRunner:
    def __init__(self, factory: ProbeFactory, max_concurrency: int = 8):
        if not 1 <= max_concurrency <= 16:
            raise ValueError("max_concurrency must be between 1 and 16")
        self.factory = factory
        self.max_concurrency = max_concurrency

    async def probe_one(self, source: SourceDefinition) -> ProbeResult:
        results: list[ProbeResult] = []
        for method in source.access_methods:
            result = await self.factory.create(method).probe(source, method)
            results.append(result)
            if result.outcome == ProbeOutcome.SUCCESS:
                return result
        rank = {
            ProbeOutcome.DEGRADED: 3,
            ProbeOutcome.BLOCKED: 2,
            ProbeOutcome.FAILED: 1,
            ProbeOutcome.SUCCESS: 4,
        }
        return max(results, key=lambda result: rank[result.outcome])

    async def probe_all(self, sources: list[SourceDefinition]) -> dict[str, ProbeResult]:
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def probe_safely(source: SourceDefinition) -> ProbeResult:
            async with semaphore:
                try:
                    return await self.probe_one(source)
                except Exception:
                    now = datetime.now(UTC)
                    method = source.access_methods[0]
                    return ProbeResult(
                        source_id=source.id,
                        access_kind=method.kind.value,
                        access_url=str(method.url),
                        outcome=ProbeOutcome.FAILED,
                        started_at=now,
                        finished_at=now,
                        suggested_status=source.status,
                        reason="internal probe error",
                        error_code="internal_probe_error",
                    )

        results = await asyncio.gather(*(probe_safely(source) for source in sources))
        return {result.source_id: result for result in results}
