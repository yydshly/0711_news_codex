from __future__ import annotations

from datetime import UTC, datetime

import feedparser

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from .blocking import blocked_reason
from .safe_http import ProbeAuthenticationRequired, UnsafeProbeUrl, safe_get
from .schema import (
    AcquisitionProbeOutcome,
    AcquisitionProbeSample,
    InvalidProbeUrl,
    probe_result,
    public_probe_url,
    sanitize_response_header_value,
    with_http_evidence,
)


class FeedResearchProbe:
    def __init__(self, policy: HttpPolicy) -> None:
        self.policy = policy

    async def probe(
        self, source: SourceDefinition, candidate: AcquisitionCandidate, limit: int = 5
    ):
        response = None
        try:
            response = await safe_get(self.policy, candidate, public_probe_url(candidate))
            if reason := blocked_reason(response, inspect_body=False):
                return with_http_evidence(
                    probe_result(
                        source,
                        candidate,
                        AcquisitionProbeOutcome.BLOCKED,
                        reason,
                        "access_blocked",
                        blocked_condition="access",
                    ),
                    response,
                    candidate,
                )
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
        except ProbeAuthenticationRequired:
            return probe_result(
                source,
                candidate,
                AcquisitionProbeOutcome.BLOCKED,
                "需要认证或批准，未发起请求",
                "authentication_required",
            )
        except (UnsafeProbeUrl, InvalidProbeUrl):
            return probe_result(
                source,
                candidate,
                AcquisitionProbeOutcome.BLOCKED,
                "目标地址不满足安全网络边界",
                "unsafe_url",
            )
        except Exception as exc:
            result = probe_result(
                source,
                candidate,
                AcquisitionProbeOutcome.FAILED,
                "公开订阅源不可用",
                type(exc).__name__,
            )
            return with_http_evidence(result, response, candidate) if response else result
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
        return with_http_evidence(
            probe_result(
                source,
                candidate,
                AcquisitionProbeOutcome.SUCCEEDED if samples else AcquisitionProbeOutcome.PARTIAL,
                "已读取公开订阅元数据；仍需条款复核",
                samples=samples,
                metadata={
                    "terms_review_required": True,
                    "content_type": sanitize_response_header_value(
                        response.headers.get("content-type")
                    ),
                },
            ),
            response,
            candidate,
        )
