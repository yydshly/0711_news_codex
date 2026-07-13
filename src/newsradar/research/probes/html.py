from __future__ import annotations

from html.parser import HTMLParser

from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from .schema import AcquisitionProbeOutcome, probe_result


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link" and values.get("rel") == "canonical":
            self.names.add("canonical")
        if tag == "article":
            self.names.add("article")
        if tag == "script" and values.get("type") == "application/ld+json":
            self.names.add("json_ld")
        if tag == "meta" and str(values.get("property", "")).startswith("og:"):
            self.names.add("open_graph")


class HtmlResearchProbe:
    """Static inspection only.  It deliberately contains no HTTP/browser/JS capability."""

    def inspect(self, source: SourceDefinition, candidate: AcquisitionCandidate, html: str):
        parser = _MetadataParser()
        parser.feed(html[:2_000_000])
        return probe_result(
            source,
            candidate,
            AcquisitionProbeOutcome.PARTIAL,
            "仅解析静态 HTML 元数据；未执行 JavaScript 或浏览器会话",
            metadata={
                "static_only": True,
                "canonical": "canonical" in parser.names,
                "json_ld": "json_ld" in parser.names,
                "open_graph": "open_graph" in parser.names,
                "semantic_article": "article" in parser.names,
                "terms_review_required": True,
            },
            decision="manual_only",
        )

    async def probe(
        self, source: SourceDefinition, candidate: AcquisitionCandidate, limit: int = 5
    ):
        del limit
        return self.inspect(source, candidate, "")
