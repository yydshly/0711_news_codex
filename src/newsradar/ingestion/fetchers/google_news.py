from __future__ import annotations

import hashlib

import feedparser
import httpx

from newsradar.ingestion.schema import FetchOutcome, NormalizedRawItem
from newsradar.sources.probes.rss import feed_datetime
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, public_headers, response_result


class GoogleNewsFetcher:
    """Fetch Google News RSS entries and retain them only as attributed discovery."""

    def __init__(self, policy: HttpPolicy, client: httpx.AsyncClient | None = None):
        self.policy = policy
        del client
        from newsradar.ingestion.origin_resolver import OriginResolver

        self.resolver = OriginResolver(policy)

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ):
        del source
        headers = public_headers({"User-Agent": "NewsRadarIngestion/0.1", **method.headers})
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified
        response = await self.policy.get(
            str(method.url), headers=headers, params=method.params or None
        )
        if response.status_code == 304:
            return response_result(response, outcome=FetchOutcome.NO_CHANGE)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            raise ValueError("invalid_feed")
        items, warnings = [], []
        for entry in parsed.entries[:limit]:
            try:
                discovery_url, title = entry.get("link"), entry.get("title")
                if not discovery_url or not title:
                    raise ValueError("missing_title_or_link")
                attribution = await self.resolver.resolve(discovery_url)
                canonical_url = attribution.publisher_url or discovery_url
                items.append(
                    NormalizedRawItem(
                        external_id=str(
                            entry.get("id")
                            or entry.get("guid")
                            or hashlib.sha256(discovery_url.encode()).hexdigest()
                        ),
                        title=title,
                        canonical_url=canonical_url,
                        original_url=discovery_url,
                        authors=(),
                        summary=entry.get("summary") or entry.get("description"),
                        published_at=feed_datetime(entry),
                        source_updated_at=feed_datetime(entry),
                        publisher_name=attribution.publisher_name,
                        publisher_url=attribution.publisher_url,
                        discovery_url=discovery_url,
                        origin_resolution_status=attribution.resolution_status,
                        raw_payload=dict(entry),
                    )
                )
            except (TypeError, ValueError) as exc:
                warnings.append(f"malformed_entry:{exc}")
        return response_result(
            response, items=tuple(items), items_received=len(items), warnings=tuple(warnings)
        )
