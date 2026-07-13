from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from .schema import AcquisitionProbeOutcome, AcquisitionProbeSample, probe_result, public_probe_url


class SitemapResearchProbe:
    def __init__(self, policy: HttpPolicy) -> None:
        self.policy = policy

    async def probe(
        self, source: SourceDefinition, candidate: AcquisitionCandidate, limit: int = 5
    ):
        target = public_probe_url(candidate)
        parts = urlsplit(target)
        robots = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        try:
            robot_response = await self.policy.get(robots, headers={})
            if robot_response.status_code >= 500:
                return probe_result(
                    source,
                    candidate,
                    AcquisitionProbeOutcome.BLOCKED,
                    "robots.txt 服务不可达，已停止自动内容探测",
                    "robots_unavailable",
                    metadata={"terms_review_required": True},
                )
            if robot_response.status_code == 401 or robot_response.status_code == 403:
                return probe_result(
                    source,
                    candidate,
                    AcquisitionProbeOutcome.BLOCKED,
                    "robots 规则拒绝访问",
                    "robots_denied",
                    metadata={"terms_review_required": True},
                )
            response = await self.policy.get(target, headers={})
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except Exception as exc:
            return probe_result(
                source,
                candidate,
                AcquisitionProbeOutcome.FAILED,
                "站点地图不可用",
                type(exc).__name__,
            )
        urls = [node.text for node in root.findall(".//{*}loc") if node.text][
            : max(0, min(limit, 5))
        ]
        samples = [AcquisitionProbeSample(canonical_url=url[:1000]) for url in urls]
        return probe_result(
            source,
            candidate,
            AcquisitionProbeOutcome.SUCCEEDED if samples else AcquisitionProbeOutcome.PARTIAL,
            "已读取站点地图 URL；robots 允许不等于条款批准",
            samples=samples,
            metadata={"terms_review_required": True},
        )
