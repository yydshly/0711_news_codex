from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.sources.schema import AccessKind, AccessMethod, SourceDefinition


@dataclass(frozen=True)
class FetchState:
    etag: str | None = None
    last_modified: str | None = None
    cursor: str | None = None


class Fetcher(Protocol):
    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ) -> FetchResult: ...


class HttpPolicy:
    """The single request policy used by ingestion fetchers (and no database handles)."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_response_bytes: int = 2_000_000,
        per_host: int = 2,
        retries: int = 2,
    ):
        self.client = client
        self.max_response_bytes = max_response_bytes
        self.per_host = per_host
        self.retries = retries
        self._semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(per_host)
        )

    @classmethod
    def default(cls) -> HttpPolicy:
        limits = httpx.Limits(max_connections=16, max_keepalive_connections=8)
        timeout = httpx.Timeout(45.0, connect=10.0, read=30.0)
        return cls(httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True))

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        host = httpx.URL(url).host or ""
        async with self._semaphores[host]:
            for attempt in range(self.retries + 1):
                try:
                    response = await self._stream_get(url, **kwargs)
                    if response.status_code not in {502, 503, 504, 429} or attempt == self.retries:
                        return response
                    delay = min(float(response.headers.get("retry-after", "0") or 0), 30.0)
                except (httpx.TransportError, httpx.TimeoutException):
                    if attempt == self.retries:
                        raise
                    delay = 0.1 * (attempt + 1)
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable")

    async def _stream_get(self, url: str, **kwargs: object) -> httpx.Response:
        request = self.client.build_request("GET", url, **kwargs)
        response = await self.client.send(request, stream=True)
        length = response.headers.get("content-length")
        if length and int(length) > self.max_response_bytes:
            await response.aclose()
            raise ValueError("response_too_large")
        chunks: list[bytes] = []
        size = 0
        try:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self.max_response_bytes:
                    raise ValueError("response_too_large")
                chunks.append(chunk)
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=b"".join(chunks),
                request=request,
                extensions=response.extensions,
            )
        finally:
            await response.aclose()


def response_result(response: httpx.Response, **values: object) -> FetchResult:
    headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower() not in {"cookie", "set-cookie", "authorization"}
    }
    remaining = response.headers.get("x-ratelimit-remaining")
    values.setdefault("outcome", FetchOutcome.SUCCEEDED)
    return FetchResult(
        http_status=response.status_code,
        final_url=str(response.url),
        response_headers=headers,
        etag=response.headers.get("etag"),
        last_modified=response.headers.get("last-modified"),
        rate_limit_remaining=int(remaining) if remaining and remaining.isdigit() else None,
        completed_at=datetime.now(UTC),
        **values,
    )


class FetcherFactory:
    def __init__(self, policy: HttpPolicy):
        self.policy = policy

    def for_method(self, method: AccessMethod) -> Fetcher:
        from .arxiv import ArxivFetcher
        from .bluesky import BlueskyFetcher
        from .github import GitHubFetcher
        from .hackernews import HackerNewsFetcher
        from .mastodon import MastodonFetcher
        from .rss import RssFetcher

        host = (httpx.URL(str(method.url)).host or "").lower()
        path = httpx.URL(str(method.url)).path
        if host == "hacker-news.firebaseio.com":
            return HackerNewsFetcher(self.policy)
        if host == "api.github.com":
            return GitHubFetcher(self.policy)
        if host == "export.arxiv.org":
            return ArxivFetcher(self.policy)
        if host == "public.api.bsky.app":
            return BlueskyFetcher(self.policy)
        if method.kind is AccessKind.PUBLIC_API and (
            path.startswith("/api/v1/accounts/") or path == "/api/v1/timelines/public"
        ):
            return MastodonFetcher(self.policy)
        if method.kind in {AccessKind.RSS, AccessKind.ATOM}:
            return RssFetcher(self.policy)
        raise ValueError(f"unsupported_fetch_method:{method.kind.value}")
