from __future__ import annotations

import hashlib

import feedparser

from newsradar.ingestion.schema import FetchOutcome, NormalizedRawItem
from newsradar.sources.probes.rss import feed_datetime
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, response_result


class RssFetcher:
    def __init__(self, policy: HttpPolicy):
        self.policy = policy

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ):
        headers = {"User-Agent": "NewsRadarIngestion/0.1", **method.headers}
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
                link = entry.get("link")
                title = entry.get("title")
                if not link or not title:
                    raise ValueError("missing_title_or_link")
                external_id = str(
                    entry.get("id")
                    or entry.get("guid")
                    or hashlib.sha256(link.encode()).hexdigest()
                )
                items.append(
                    NormalizedRawItem(
                        external_id=external_id,
                        title=title,
                        canonical_url=link,
                        authors=tuple(filter(None, [entry.get("author")])),
                        summary=entry.get("summary") or entry.get("description"),
                        published_at=feed_datetime(entry),
                        source_updated_at=feed_datetime(entry),
                        raw_payload=dict(entry),
                    )
                )
            except (TypeError, ValueError) as exc:
                warnings.append(f"malformed_entry:{exc}")
        return response_result(
            response, items=tuple(items), items_received=len(items), warnings=tuple(warnings)
        )
