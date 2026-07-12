from __future__ import annotations

import asyncio
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

from newsradar.ingestion.schema import NormalizedRawItem
from newsradar.sources.probes.rss import feed_datetime
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, response_result


class ArxivFetcher:
    def __init__(self, policy: HttpPolicy, *, delay_seconds: float = 3.0):
        self.policy, self.delay_seconds, self._last_request = policy, delay_seconds, 0.0

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ):
        loop = asyncio.get_running_loop()
        wait = self.delay_seconds - (loop.time() - self._last_request)
        if self._last_request and wait > 0:
            await asyncio.sleep(wait)
        self._last_request = loop.time()
        parsed_url = urlsplit(str(method.url))
        query = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
        query.update(method.params)
        query["max_results"] = str(limit)
        request_url = urlunsplit(
            (parsed_url.scheme, parsed_url.netloc, parsed_url.path, urlencode(query), "")
        )
        response = await self.policy.get(request_url, headers=method.headers)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        items = []
        for entry in parsed.entries[:limit]:
            link = next(
                (
                    link.get("href")
                    for link in entry.get("links", [])
                    if link.get("rel") == "alternate"
                ),
                entry.get("link"),
            )
            if not link or not entry.get("title"):
                continue
            external_id = entry.get("id", "").rsplit("/", 1)[-1]
            version = re.search(r"v(\d+)$", external_id)
            items.append(
                NormalizedRawItem(
                    external_id=external_id,
                    title=" ".join(entry.title.split()),
                    canonical_url=link,
                    authors=tuple(
                        author.get("name")
                        for author in entry.get("authors", [])
                        if author.get("name")
                    ),
                    summary=entry.get("summary"),
                    published_at=feed_datetime(entry),
                    source_updated_at=feed_datetime(entry),
                    raw_payload={**dict(entry), "version": version.group(1) if version else None},
                )
            )
        return response_result(
            response, items=tuple(items), items_received=len(items), next_cursor=None
        )
