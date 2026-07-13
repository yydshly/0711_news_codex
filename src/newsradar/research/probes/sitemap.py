from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from .blocking import blocked_reason
from .robots import allowed as robots_allowed
from .safe_http import ProbeAuthenticationRequired, UnsafeProbeUrl, safe_get
from .schema import (
    AcquisitionProbeOutcome,
    AcquisitionProbeSample,
    InvalidProbeUrl,
    probe_result,
    public_probe_url,
    with_http_evidence,
)


class SitemapResearchProbe:
    def __init__(self, policy: HttpPolicy) -> None:
        self.policy = policy

    async def probe(
        self, source: SourceDefinition, candidate: AcquisitionCandidate, limit: int = 5
    ):
        response = None
        try:
            target = public_probe_url(candidate)
            parts = urlsplit(target)
            robots = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
            robot_response = await safe_get(self.policy, candidate, robots)
            if robot_response.status_code >= 500:
                return with_http_evidence(
                    probe_result(
                        source,
                        candidate,
                        AcquisitionProbeOutcome.BLOCKED,
                        "robots.txt 服务不可达，已停止自动内容探测",
                        "robots_unavailable",
                        metadata={"terms_review_required": True},
                        blocked_condition="robots",
                    ),
                    robot_response,
                    candidate,
                )
            if robot_response.status_code == 401 or robot_response.status_code == 403:
                return with_http_evidence(
                    probe_result(
                        source,
                        candidate,
                        AcquisitionProbeOutcome.BLOCKED,
                        "robots 规则拒绝访问",
                        "robots_denied",
                        metadata={"terms_review_required": True, "blocked_condition": "robots"},
                        blocked_condition="robots",
                    ),
                    robot_response,
                    candidate,
                )
            if not robots_allowed(robot_response.text, parts.path):
                return with_http_evidence(
                    probe_result(
                        source,
                        candidate,
                        AcquisitionProbeOutcome.BLOCKED,
                        "robots 规则禁止目标路径",
                        "robots_denied",
                        metadata={"terms_review_required": True, "blocked_condition": "robots"},
                        blocked_condition="robots",
                    ),
                    robot_response,
                    candidate,
                )
            response = await safe_get(self.policy, candidate, target)
            if reason := blocked_reason(response):
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
            root = ElementTree.fromstring(response.content)
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
                "站点地图不可用",
                type(exc).__name__,
            )
            return with_http_evidence(result, response, candidate) if response else result
        urls = [node.text for node in root.findall(".//{*}loc") if node.text][
            : max(0, min(limit, 5))
        ]
        samples = [AcquisitionProbeSample(canonical_url=url[:1000]) for url in urls]
        return with_http_evidence(
            probe_result(
                source,
                candidate,
                AcquisitionProbeOutcome.SUCCEEDED if samples else AcquisitionProbeOutcome.PARTIAL,
                "已读取站点地图 URL；robots 允许不等于条款批准",
                samples=samples,
                metadata={"terms_review_required": True},
            ),
            response,
            candidate,
        )
