from __future__ import annotations

from datetime import UTC, datetime

import feedparser

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from .schema import AcquisitionProbeOutcome, AcquisitionProbeSample, probe_result, public_probe_url


class FeedResearchProbe:
    def __init__(self, policy: HttpPolicy) -> None:
        self.policy = policy

    async def probe(
        self, source: SourceDefinition, candidate: AcquisitionCandidate, limit: int = 5
    ):
        try:
            response = await self.policy.get(public_probe_url(candidate), headers={})
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
        except Exception as exc:
            return probe_result(
                source,
                candidate,
                AcquisitionProbeOutcome.FAILED,
                "公开订阅源不可用",
                type(exc).__name__,
            )
        samples = []
        for entry in parsed.entries[: max(0, min(limit, 5))]:
            published = entry.get("published_parsed")
            at = datetime(*published[:6], tzinfo=UTC) if published else None
            samples.append(
                AcquisitionProbeSample(
                    external_id=str(entry.get("id") or entry.get("guid") or "") or None,
                    title=str(entry.get("title") or "")[:500] or None,
                    canonical_url=str(entry.get("link") or "")[:1000] or None,
                    summary=str(entry.get("summary") or "")[:2000] or None,
                    published_at=at,
                )
            )
        return probe_result(
            source,
            candidate,
            AcquisitionProbeOutcome.SUCCEEDED if samples else AcquisitionProbeOutcome.PARTIAL,
            "已读取公开订阅元数据；仍需条款复核",
            samples=samples,
            metadata={
                "terms_review_required": True,
                "content_type": response.headers.get("content-type"),
            },
        )
