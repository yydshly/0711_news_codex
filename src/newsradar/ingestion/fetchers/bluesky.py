from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

from newsradar.ingestion.schema import FetchOutcome, NormalizedRawItem
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, public_headers, response_result


class BlueskyFetcher:
    _HOST = "public.api.bsky.app"
    _ENDPOINTS = {
        "/xrpc/app.bsky.feed.getAuthorFeed": "actor",
        "/xrpc/app.bsky.feed.getFeed": "feed",
        "/xrpc/app.bsky.feed.searchPosts": "q",
    }

    def __init__(self, policy: HttpPolicy):
        self.policy = policy

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ):
        base_url = str(method.url)
        self._validate_target(base_url, method.params)
        if state.cursor and "://" in state.cursor:
            raise ValueError("unregistered_bluesky_cursor")
        response = await self.policy.get(
            base_url,
            headers={"Accept": "application/json", **public_headers(method.headers)},
            params={
                **method.params,
                "limit": str(min(limit, 100)),
                **({"cursor": state.cursor} if state.cursor else {}),
            },
        )
        if response.status_code in {429, 502, 503, 504} and self._is_search(base_url):
            return response_result(
                response,
                outcome=FetchOutcome.PARTIAL,
                error_code="search_degraded",
                retry_after_seconds=float(response.headers.get("retry-after", "0") or 0),
            )
        if response.status_code == 429:
            return response_result(
                response,
                outcome=FetchOutcome.FAILED,
                error_code="rate_limited",
                retry_after_seconds=float(response.headers.get("retry-after", "0") or 0),
            )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("feed", payload.get("posts", []))
        items = tuple(item for row in rows[:limit] if (item := self._item(row)) is not None)
        return response_result(
            response,
            items=items,
            items_received=len(items),
            next_cursor=payload.get("cursor"),
        )

    @classmethod
    def _validate_target(cls, url: str, params: dict[str, str]) -> None:
        parsed = urlsplit(url)
        required = cls._ENDPOINTS.get(parsed.path)
        if parsed.hostname != cls._HOST or required is None or not params.get(required):
            raise ValueError("unregistered_bluesky_target")

    @classmethod
    def _is_search(cls, url: str) -> bool:
        return urlsplit(url).path == "/xrpc/app.bsky.feed.searchPosts"

    @staticmethod
    def _item(row: object) -> NormalizedRawItem | None:
        if not isinstance(row, dict):
            return None
        post = row.get("post", row)
        if not isinstance(post, dict) or post.get("notFound") or post.get("blocked"):
            return None
        record, author = post.get("record", {}), post.get("author", {})
        if not isinstance(record, dict) or not isinstance(author, dict):
            return None
        uri, cid, text = post.get("uri"), post.get("cid"), record.get("text")
        handle, rkey = author.get("handle"), str(uri or "").rsplit("/", 1)[-1]
        if not uri or not cid or not text or not handle or not rkey:
            return None
        reply = record.get("reply") if isinstance(record.get("reply"), dict) else {}
        root = reply.get("root") if isinstance(reply.get("root"), dict) else {}
        metrics = {
            "likes": post.get("likeCount", 0),
            "reposts": post.get("repostCount", 0),
            "replies": post.get("replyCount", 0),
        }
        return NormalizedRawItem(
            external_id=f"{uri}#{cid}",
            title=text.splitlines()[0][:500],
            canonical_url=f"https://bsky.app/profile/{quote(handle)}/post/{quote(rkey)}",
            authors=(author.get("displayName") or handle,),
            content=text,
            published_at=_timestamp(record.get("createdAt")),
            engagement={key: value for key, value in metrics.items() if isinstance(value, int)},
            item_kind="social_post",
            author_account_id=author.get("did"),
            author_handle=handle,
            thread_root_id=root.get("uri"),
            raw_payload=post,
        )


def _timestamp(value: object) -> datetime | None:
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        if isinstance(value, str)
        else None
    )
