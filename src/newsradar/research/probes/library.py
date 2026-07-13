from __future__ import annotations

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from .schema import AcquisitionProbeOutcome, probe_result


class LibraryResearchProbe:
    def __init__(self, policy: HttpPolicy) -> None:
        self.policy = policy

    async def probe(
        self, source: SourceDefinition, candidate: AcquisitionCandidate, limit: int = 5
    ):
        del limit
        return probe_result(
            source,
            candidate,
            AcquisitionProbeOutcome.PARTIAL,
            "第三方库仅记录元数据，未执行网络、下载或媒体抓取",
            metadata={
                "network_used": False,
                "terms_review_required": True,
                "maintenance": "manual_review",
            },
            decision="manual_only",
        )
