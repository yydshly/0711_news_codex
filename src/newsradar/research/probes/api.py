from __future__ import annotations

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.sources.schema import AcquisitionAuth, AcquisitionCandidate, SourceDefinition

from .safe_http import UnsafeProbeUrl, safe_get
from .schema import AcquisitionProbeOutcome, probe_result, public_probe_url


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
            if response.status_code in {401, 403, 429}:
                return probe_result(
                    source,
                    candidate,
                    AcquisitionProbeOutcome.BLOCKED,
                    "接口要求认证、授权或受限访问",
                    f"http_{response.status_code}",
                    metadata={"terms_review_required": True},
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
        return probe_result(
            source,
            candidate,
            AcquisitionProbeOutcome.SUCCEEDED,
            "已确认公开 API 响应；仍需条款复核",
            metadata={
                "sample_count": min(len(rows) if isinstance(rows, list) else 0, 5),
                "pagination_detected": isinstance(payload, dict)
                and any(key in payload for key in ("next", "next_page", "nextPageToken")),
                "terms_review_required": True,
            },
        )
