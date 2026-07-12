from __future__ import annotations

from datetime import UTC, datetime

from newsradar.ingestion.schema import FetchOutcome, FetchResult, NormalizedRawItem
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, response_result
from .credentials import CredentialProvider


class YouTubeFetcher:
    def __init__(self, policy: HttpPolicy, credentials: CredentialProvider):
        self.policy, self.credentials = policy, credentials

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ) -> FetchResult:
        del source, state
        try:
            key = self.credentials.require("YOUTUBE_API_KEY")
        except (KeyError, ValueError):
            return FetchResult(
                outcome=FetchOutcome.BLOCKED,
                error_code="missing_credential",
                error_message="YouTube API key is not configured",
            )
        response = await self.policy.get(
            str(method.url),
            params={
                **method.params,
                "part": "snippet",
                "type": "video",
                "maxResults": str(min(limit, 50)),
                "key": key,
            },
        )
        if response.status_code == 403:
            return response_result(
                response, outcome=FetchOutcome.BLOCKED, error_code="quota_exhausted"
            )
        response.raise_for_status()
        ids = [
            x.get("id", {}).get("videoId")
            for x in response.json().get("items", [])
            if isinstance(x, dict)
        ]
        ids = [x for x in ids if isinstance(x, str)]
        videos = await self.policy.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet,statistics", "id": ",".join(ids), "key": key},
        )
        if videos.status_code == 403:
            return response_result(
                videos, outcome=FetchOutcome.BLOCKED, error_code="quota_exhausted"
            )
        videos.raise_for_status()
        items = []
        for row in videos.json().get("items", []):
            snippet = row.get("snippet", {})
            stats = row.get("statistics", {})
            video_id = row.get("id")
            if not video_id or not snippet.get("title"):
                continue
            items.append(
                NormalizedRawItem(
                    external_id=str(video_id),
                    title=str(snippet["title"]),
                    canonical_url=f"https://www.youtube.com/watch?v={video_id}",
                    authors=(str(snippet["channelTitle"]),) if snippet.get("channelTitle") else (),
                    summary=snippet.get("description"),
                    published_at=datetime.fromisoformat(
                        snippet["publishedAt"].replace("Z", "+00:00")
                    ).astimezone(UTC)
                    if snippet.get("publishedAt")
                    else None,
                    engagement={
                        k: int(v)
                        for k, v in {
                            "views": stats.get("viewCount"),
                            "likes": stats.get("likeCount"),
                            "comments": stats.get("commentCount"),
                        }.items()
                        if isinstance(v, str) and v.isdigit()
                    },
                    item_kind="video",
                    raw_payload=row,
                )
            )
        return response_result(videos, items=tuple(items), items_received=len(items))
