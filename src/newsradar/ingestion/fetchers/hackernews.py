from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from newsradar.ingestion.schema import NormalizedRawItem
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, response_result


class HackerNewsFetcher:
    def __init__(self, policy: HttpPolicy):
        self.policy = policy

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ):
        response = await self.policy.get(
            str(method.url), headers=method.headers, params=method.params
        )
        response.raise_for_status()
        ids = response.json()[:limit]
        semaphore = asyncio.Semaphore(5)

        async def item(item_id: int):
            async with semaphore:
                result = await self.policy.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
                )
                result.raise_for_status()
                return result.json()

        records = await asyncio.gather(*(item(i) for i in ids), return_exceptions=True)
        items, warnings = [], []
        for record in records:
            if isinstance(record, Exception):
                warnings.append("item_fetch_failed")
                continue
            if (
                not record
                or record.get("deleted")
                or record.get("dead")
                or record.get("type") not in {"story", "job"}
            ):
                continue
            url = record.get("url") or f"https://news.ycombinator.com/item?id={record['id']}"
            title = record.get("title")
            if not title:
                continue
            items.append(
                NormalizedRawItem(
                    external_id=str(record["id"]),
                    title=title,
                    canonical_url=url,
                    discussion_url=f"https://news.ycombinator.com/item?id={record['id']}",
                    authors=(record.get("by"),) if record.get("by") else (),
                    published_at=datetime.fromtimestamp(record["time"], tz=UTC)
                    if record.get("time")
                    else None,
                    engagement={
                        "score": record.get("score", 0),
                        "comments": record.get("descendants", 0),
                    },
                    raw_payload=record,
                )
            )
        return response_result(
            response, items=tuple(items), items_received=len(items), warnings=tuple(warnings)
        )
