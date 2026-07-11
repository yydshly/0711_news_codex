from __future__ import annotations

import asyncio

from newsradar.sources.schema import SourceDefinition

from .base import ProbeOutcome, ProbeResult
from .factory import ProbeFactory


class ProbeRunner:
    def __init__(self, factory: ProbeFactory):
        self.factory = factory

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
        results = await asyncio.gather(*(self.probe_one(source) for source in sources))
        return {result.source_id: result for result in results}
