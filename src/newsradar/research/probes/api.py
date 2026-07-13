from __future__ import annotations

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.sources.schema import AcquisitionAuth, AcquisitionCandidate, SourceDefinition

from .blocking import blocked_reason
from .safe_http import UnsafeProbeUrl, safe_get
from .schema import (
    AcquisitionProbeOutcome,
    AcquisitionProbeSample,
    probe_result,
    public_probe_url,
    with_http_evidence,
)


class ApiResearchProbe:
    def __init__(self, policy: HttpPolicy) -> None:
        self.policy = policy

    async def probe(
        self, source: SourceDefinition, candidate: AcquisitionCandidate, limit: int = 5
    ):
        del limit
        if candidate.authentication is not AcquisitionAuth.NONE:
            return probe_result(
                source,
                candidate,
                AcquisitionProbeOutcome.BLOCKED,
                "需要 API 凭据或授权，研究探测不会发送凭据",
                "credential_required",
                metadata={"terms_review_required": True},
            )
        try:
            response = await safe_get(self.policy, candidate, public_probe_url(candidate))
            if blocked_reason(response):
                return with_http_evidence(
                    probe_result(
                        source,
                        candidate,
                        AcquisitionProbeOutcome.BLOCKED,
                        "接口要求认证、授权或受限访问",
                        f"http_{response.status_code}",
                        metadata={"terms_review_required": True},
                        blocked_condition="access",
                    ),
                    response,
                    candidate,
                )
            response.raise_for_status()
        except UnsafeProbeUrl:
            return probe_result(
                source,
                candidate,
                AcquisitionProbeOutcome.BLOCKED,
                "目标地址不满足安全网络边界",
                "unsafe_url",
            )
        except Exception as exc:
            return probe_result(
                source,
                candidate,
                AcquisitionProbeOutcome.FAILED,
                "公开 API 不可用",
                type(exc).__name__,
            )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        rows = (
            payload
            if isinstance(payload, list)
            else (payload.get("items", []) if isinstance(payload, dict) else [])
        )
        rows = rows if isinstance(rows, list) else []
        samples = [
            AcquisitionProbeSample(
                external_id=str(row.get("id") or row.get("uuid") or "") or None,
                title=str(row.get("title") or row.get("name") or "")[:500] or None,
                canonical_url=str(row.get("url") or row.get("link") or "")[:1000] or None,
            )
            for row in rows[:5]
            if isinstance(row, dict)
        ]
        return with_http_evidence(
            probe_result(
                source,
                candidate,
                AcquisitionProbeOutcome.SUCCEEDED,
                "已确认公开 API 响应；仍需条款复核",
                metadata={
                    "pagination_detected": isinstance(payload, dict)
                    and any(key in payload for key in ("next", "next_page", "nextPageToken")),
                    "terms_review_required": True,
                },
                samples=samples,
            ),
            response,
            candidate,
        )
