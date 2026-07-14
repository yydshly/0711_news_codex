from __future__ import annotations

from datetime import UTC, datetime

import httpx
from pydantic import AnyHttpUrl

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
        channel_id = method.params.get("id")
        if not channel_id:
            raise ValueError("unaudited_youtube_channel")
        try:
            key = self.credentials.require("YOUTUBE_API_KEY")
        except (KeyError, ValueError):
            return FetchResult(
                outcome=FetchOutcome.BLOCKED,
                error_code="missing_credential",
                error_message="YouTube API key is not configured",
            )
        channel = await self.policy.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={
                "part": "contentDetails,snippet",
                "id": channel_id,
                "key": key,
            },
        )
        if channel.status_code in {401, 403}:
            return _youtube_result(
                channel,
                outcome=FetchOutcome.BLOCKED,
                error_code="quota_exhausted"
                if channel.status_code == 403
                else "permission_required",
            )
        channel.raise_for_status()
        channel_rows = channel.json().get("items", [])
        if not channel_rows:
            return _youtube_result(channel, items=(), items_received=0)
        uploads = (
            channel_rows[0]
            .get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )
        if not isinstance(uploads, str) or not uploads:
            return _youtube_result(
                channel,
                outcome=FetchOutcome.PARTIAL,
                error_code="schema_drift",
                warnings=("missing_uploads_playlist",),
            )

        playlist = await self.policy.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={
                "part": "contentDetails",
                "playlistId": uploads,
                "maxResults": str(min(limit, 50)),
                "key": key,
            },
        )
        if playlist.status_code in {401, 403}:
            return _youtube_result(
                playlist,
                outcome=FetchOutcome.BLOCKED,
                error_code="quota_exhausted"
                if playlist.status_code == 403
                else "permission_required",
            )
        playlist.raise_for_status()
        ids = [
            x.get("contentDetails", {}).get("videoId")
            for x in playlist.json().get("items", [])
            if isinstance(x, dict)
        ]
        ids = [x for x in ids if isinstance(x, str)]
        if not ids:
            return _youtube_result(playlist, items=(), items_received=0)
        videos = await self.policy.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet,statistics", "id": ",".join(ids), "key": key},
        )
        if videos.status_code in {401, 403}:
            return _youtube_result(
                videos,
                outcome=FetchOutcome.BLOCKED,
                error_code="quota_exhausted"
                if videos.status_code == 403
                else "permission_required",
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
        return _youtube_result(videos, items=tuple(items), items_received=len(items))


def _youtube_result(response: httpx.Response, **values: object) -> FetchResult:
    result = response_result(response, **values)
    return result.model_copy(
        update={"final_url": AnyHttpUrl(str(response.url.copy_with(query=None)))}
    )
