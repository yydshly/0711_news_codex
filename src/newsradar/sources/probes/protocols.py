from __future__ import annotations

import json
from html.parser import HTMLParser
from urllib.parse import quote

import httpx

from newsradar.sources.schema import SourceStatus

from .base import ProbeOutcome, utcnow
from .json_api import JsonApiProbe


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if text := data.strip():
            self.parts.append(text)


def html_to_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _TextExtractor()
    parser.feed(value)
    text = " ".join(parser.parts).strip()
    return text or None


def engagement_total(*values: object) -> int:
    return sum(value for value in values if isinstance(value, int))


def synthetic_response(original: httpx.Response, payload: object) -> httpx.Response:
    safe_request = httpx.Request("GET", str(original.request.url.copy_remove_param("key")))
    headers = {
        key: value
        for key, value in original.headers.items()
        if key.lower() not in {"content-encoding", "content-length"}
    }
    return httpx.Response(
        original.status_code,
        content=json.dumps(payload).encode(),
        headers=headers,
        request=safe_request,
    )


class HackerNewsProbe(JsonApiProbe):
    async def parse(self, source, method, response, started, latency_ms):
        payload = response.json()
        if isinstance(payload, list) and payload and all(isinstance(item, int) for item in payload):
            base = "https://hacker-news.firebaseio.com/v0/item"
            details = []
            for item_id in payload[:5]:
                detail = await self.client.get(f"{base}/{item_id}.json")
                detail.raise_for_status()
                if isinstance(detail.json(), dict):
                    details.append(detail.json())
            response = synthetic_response(response, details)
        return await super().parse(source, method, response, started, latency_ms)


class YouTubeProbe(JsonApiProbe):
    async def _request(self, method):
        params = dict(method.params)
        key = self.credentials.require("YOUTUBE_API_KEY")
        params["key"] = key
        if method.url.path.endswith("/channels"):
            params.setdefault("part", "contentDetails")
        response = await self.client.get(
            str(method.url),
            headers={"User-Agent": "NewsCodexSourceProbe/0.1 (+local audited registry)"},
            params=params,
            follow_redirects=True,
        )
        if not method.url.path.endswith("/channels") or response.status_code >= 400:
            return response
        rows = response.json().get("items", [])
        uploads = (
            rows[0]
            .get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
            if rows and isinstance(rows[0], dict)
            else None
        )
        if not isinstance(uploads, str) or not uploads:
            return synthetic_response(response, {"items": []})
        return await self.client.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            headers={"User-Agent": "NewsCodexSourceProbe/0.1 (+local audited registry)"},
            params={
                "part": "snippet",
                "playlistId": uploads,
                "maxResults": "5",
                "key": key,
            },
            follow_redirects=True,
        )

    async def parse(self, source, method, response, started, latency_ms):
        payload = response.json()
        flattened = []
        for item in payload.get("items", []):
            snippet = item.get("snippet", {})
            video_id = snippet.get("resourceId", {}).get("videoId")
            flattened.append(
                {
                    "id": item.get("id") or video_id,
                    "title": snippet.get("title"),
                    "description": snippet.get("description"),
                    "published_at": snippet.get("publishedAt"),
                    "author": snippet.get("channelTitle"),
                    "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
                }
            )
        safe = synthetic_response(
            response, {"items": flattened, "next": payload.get("nextPageToken")}
        )
        return await super().parse(source, method, safe, started, latency_ms)


class BlueskyProbe(JsonApiProbe):
    async def parse(self, source, method, response, started, latency_ms):
        payload = response.json()
        flattened = []
        for row in payload.get("feed", []):
            post = row.get("post", {})
            record = post.get("record", {})
            author = post.get("author", {})
            uri = post.get("uri", "")
            rkey = uri.rsplit("/", 1)[-1] if uri else None
            handle = author.get("handle")
            flattened.append(
                {
                    "id": uri,
                    "title": record.get("text"),
                    "content": record.get("text"),
                    "published_at": record.get("createdAt"),
                    "author": author.get("displayName") or handle,
                    "url": f"https://bsky.app/profile/{quote(handle)}/post/{quote(rkey)}"
                    if handle and rkey
                    else None,
                    "likes": engagement_total(
                        post.get("likeCount"),
                        post.get("repostCount"),
                        post.get("replyCount"),
                    ),
                }
            )
        safe = synthetic_response(response, {"items": flattened, "cursor": payload.get("cursor")})
        return await super().parse(source, method, safe, started, latency_ms)


class MastodonProbe(JsonApiProbe):
    async def parse(self, source, method, response, started, latency_ms):
        payload = response.json()
        flattened = []
        for status in payload if isinstance(payload, list) else []:
            if not isinstance(status, dict):
                continue
            account = status.get("account") if isinstance(status.get("account"), dict) else {}
            reblog = status.get("reblog") if isinstance(status.get("reblog"), dict) else {}
            content = html_to_text(status.get("content")) or html_to_text(reblog.get("content"))
            flattened.append(
                {
                    "id": status.get("id"),
                    "title": content,
                    "content": content,
                    "published_at": status.get("created_at"),
                    "author": account.get("display_name")
                    or account.get("acct")
                    or account.get("username"),
                    "url": status.get("url") or status.get("uri"),
                    "likes": engagement_total(
                        status.get("replies_count"),
                        status.get("reblogs_count"),
                        status.get("favourites_count"),
                    ),
                }
            )
        safe = synthetic_response(response, {"items": flattened})
        return await super().parse(source, method, safe, started, latency_ms)


class RedditProbe(JsonApiProbe):
    async def probe(self, source, method):
        try:
            self.credentials.require("REDDIT_CLIENT_ID")
            self.credentials.require("REDDIT_CLIENT_SECRET")
        except (KeyError, ValueError):
            started = utcnow()
            return self._result(
                source,
                method,
                started,
                ProbeOutcome.BLOCKED,
                SourceStatus.CANDIDATE,
                "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are required for official OAuth access",
                error_code="missing_oauth_credentials",
            )
        return await super().probe(source, method)

    async def _request(self, method):
        client_id = self.credentials.require("REDDIT_CLIENT_ID")
        secret = self.credentials.require("REDDIT_CLIENT_SECRET")
        token_response = await self.client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(client_id, secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": "windows:news-codex:v0.1 (personal source audit)"},
        )
        token_response.raise_for_status()
        token = token_response.json()["access_token"]
        return await self.client.get(
            str(method.url),
            params=method.params,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "windows:news-codex:v0.1 (personal source audit)",
            },
            follow_redirects=True,
        )

    async def parse(self, source, method, response, started, latency_ms):
        payload = response.json()
        flattened = []
        for child in payload.get("data", {}).get("children", []):
            item = child.get("data", {})
            flattened.append(
                {
                    "id": item.get("name") or item.get("id"),
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "time": item.get("created_utc"),
                    "author": item.get("author"),
                    "score": item.get("score"),
                    "discussion_url": f"https://www.reddit.com{item.get('permalink')}"
                    if item.get("permalink")
                    else None,
                    "summary": item.get("selftext"),
                }
            )
        safe = synthetic_response(
            response, {"items": flattened, "cursor": payload.get("data", {}).get("after")}
        )
        return await super().parse(source, method, safe, started, latency_ms)
