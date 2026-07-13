from __future__ import annotations

import json
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from .blocking import blocked_reason
from .robots import allowed as robots_allowed
from .safe_http import ProbeAuthenticationRequired, UnsafeProbeUrl, safe_get
from .schema import (
    AcquisitionProbeOutcome,
    probe_result,
    public_probe_url,
    sanitize_probe_details,
    with_http_evidence,
)


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()
        self.values: dict[str, list[str]] = {
            "alternate": [],
            "json_ld": [],
            "embedded_json": [],
            "open_graph": [],
            "article": [],
        }
        self._script_type: str | None = None
        self._script: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link" and values.get("rel") == "canonical":
            self.names.add("canonical")
            self.values["canonical"] = [values.get("href", "")]
        if tag == "link" and "alternate" in values.get("rel", ""):
            self.values["alternate"].append(values.get("href", ""))
        if tag == "article":
            self.names.add("article")
        if tag == "script" and values.get("type") == "application/ld+json":
            self.names.add("json_ld")
            self._script_type = "json_ld"
            self._script = []
        if tag == "script" and values.get("type") in {"application/json", "application/ld+json"}:
            self._script_type = (
                "embedded_json" if values.get("type") == "application/json" else "json_ld"
            )
            self._script = []
        if tag == "meta" and str(values.get("property", "")).startswith("og:"):
            self.names.add("open_graph")
            self.values["open_graph"].append(
                f"{values.get('property')}={values.get('content', '')}"
            )
        if tag == "article":
            self.values["article"].append(values.get("class", "article"))

    def handle_data(self, data):
        if self._script_type:
            self._script.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._script_type:
            self.values[self._script_type].append("".join(self._script)[:4000])
            self._script_type = None


class HtmlResearchProbe:
    """Static inspection only.  It deliberately contains no HTTP/browser/JS capability."""

    def __init__(self, policy: HttpPolicy | None = None) -> None:
        self.policy = policy

    def inspect(self, source: SourceDefinition, candidate: AcquisitionCandidate, html: str):
        parser = _MetadataParser()
        parser.feed(html[:2_000_000])

        def sanitized_json(values: list[str]) -> str:
            parsed: list[object] = []
            for value in values[:2]:
                try:
                    parsed.append(sanitize_probe_details(json.loads(value)))
                except json.JSONDecodeError:
                    parsed.append(sanitize_probe_details(value))
            rendered = [
                json.dumps(item, ensure_ascii=False) if not isinstance(item, str) else item
                for item in parsed
            ]
            return "\n".join(rendered)[:4000]

        return probe_result(
            source,
            candidate,
            AcquisitionProbeOutcome.PARTIAL,
            "仅解析静态 HTML 元数据；未执行 JavaScript 或浏览器会话",
            metadata={
                "static_only": True,
                "canonical": "canonical" in parser.names,
                "has_json_ld": "json_ld" in parser.names,
                "open_graph": "open_graph" in parser.names,
                "semantic_article": "article" in parser.names,
                "canonical_url": (parser.values.get("canonical") or [None])[0],
                "alternate_urls": "|".join(parser.values["alternate"][:5]),
                "json_ld": sanitized_json(parser.values["json_ld"]),
                "embedded_json": sanitized_json(parser.values["embedded_json"]),
                "open_graph_values": "|".join(parser.values["open_graph"][:20])[:4000],
                "terms_review_required": True,
            },
            decision="manual_only",
        )

    async def probe(
        self, source: SourceDefinition, candidate: AcquisitionCandidate, limit: int = 5
    ):
        del limit
        if self.policy is None:
            return self.inspect(source, candidate, "")
        target = public_probe_url(candidate)
        parts = urlsplit(target)
        robots = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        try:
            robot = await safe_get(self.policy, candidate, robots)
            if robot.status_code >= 500:
                return with_http_evidence(
                    probe_result(
                        source,
                        candidate,
                        AcquisitionProbeOutcome.BLOCKED,
                        "robots.txt 不可达",
                        "robots_unavailable",
                        blocked_condition="robots",
                    ),
                    robot,
                    candidate,
                )
            if robot.status_code in {401, 403} or not robots_allowed(robot.text, parts.path):
                return with_http_evidence(
                    probe_result(
                        source,
                        candidate,
                        AcquisitionProbeOutcome.BLOCKED,
                        "robots 规则禁止目标路径",
                        "robots_denied",
                        blocked_condition="robots",
                    ),
                    robot,
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
        except ProbeAuthenticationRequired:
            return probe_result(
                source,
                candidate,
                AcquisitionProbeOutcome.BLOCKED,
                "需要认证或批准",
                "authentication_required",
            )
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
                "静态页面不可用",
                type(exc).__name__,
            )
        return with_http_evidence(
            self.inspect(source, candidate, response.text), response, candidate
        )
