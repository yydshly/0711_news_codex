from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

import feedparser

from newsradar.ingestion.attribution import OriginResolutionStatus
from newsradar.ingestion.schema import FetchOutcome, NormalizedRawItem
from newsradar.sources.probes.rss import feed_datetime
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, public_headers, response_result

_TITLE_ATTRIBUTION = re.compile(r"\s+\((?:[^()/]+/)?([^()]+)\)\s*$")
_TECHMEME_HOSTS = frozenset({"techmeme.com", "www.techmeme.com"})


class _ExternalLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if href and _is_external_https_url(href):
            self.urls.append(href)


class TechmemeFetcher:
    """Fetch Techmeme RSS while preserving the original publisher story identity."""

    def __init__(self, policy: HttpPolicy):
        self.policy = policy

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ):
        del source
        headers = public_headers(
            {"User-Agent": "NewsRadarIngestion/0.1", **method.headers}
        )
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified
        response = await self.policy.get(str(method.url), headers=headers, params=method.params)
        if response.status_code == 304:
            return response_result(response, outcome=FetchOutcome.NO_CHANGE)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            raise ValueError("invalid_feed")

        items, warnings = [], []
        for entry in parsed.entries[:limit]:
            try:
                discovery_url = entry.get("link")
                title = entry.get("title")
                if not discovery_url or not title:
                    raise ValueError("missing_title_or_link")
                summary = entry.get("summary") or entry.get("description")
                publisher_url = _first_external_url(summary or "")
                publisher_name, clean_title = _publisher_and_title(title)
                resolved = publisher_url is not None
                items.append(
                    NormalizedRawItem(
                        external_id=str(
                            entry.get("id")
                            or entry.get("guid")
                            or hashlib.sha256(discovery_url.encode()).hexdigest()
                        ),
                        title=clean_title,
                        canonical_url=publisher_url or discovery_url,
                        original_url=discovery_url,
                        authors=tuple(filter(None, [entry.get("author")])),
                        summary=summary,
                        published_at=feed_datetime(entry),
                        source_updated_at=feed_datetime(entry),
                        publisher_name=publisher_name,
                        publisher_url=publisher_url,
                        discovery_url=discovery_url,
                        origin_resolution_status=(
                            OriginResolutionStatus.RESOLVED
                            if resolved
                            else OriginResolutionStatus.UNRESOLVED
                        ),
                        raw_payload=dict(entry),
                    )
                )
            except (TypeError, ValueError) as exc:
                warnings.append(f"malformed_entry:{exc}")
        return response_result(
            response, items=tuple(items), items_received=len(items), warnings=tuple(warnings)
        )


def _first_external_url(summary: str) -> str | None:
    parser = _ExternalLinkParser()
    parser.feed(summary)
    return parser.urls[0] if parser.urls else None


def _publisher_and_title(title: str) -> tuple[str | None, str]:
    match = _TITLE_ATTRIBUTION.search(title)
    if not match:
        return None, title
    publisher = match.group(1).strip()[:255]
    return publisher or None, title[: match.start()].rstrip()


def _is_external_https_url(value: str) -> bool:
    parts = urlsplit(value.strip())
    return bool(
        parts.scheme == "https"
        and parts.hostname
        and parts.hostname.casefold() not in _TECHMEME_HOSTS
        and not parts.username
        and not parts.password
    )
