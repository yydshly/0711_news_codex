from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.settings import get_settings
from newsradar.sources.schema import AccessKind, AccessMethod, SourceDefinition

from .retry_after import parse_retry_after


@dataclass(frozen=True)
class FetchState:
    etag: str | None = None
    last_modified: str | None = None
    cursor: str | None = None


class Fetcher(Protocol):
    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ) -> FetchResult: ...


class TrialCredentialFreeFetcherRequiredError(ValueError):
    """Raised when trial mode has no explicitly credential-free fetcher."""

    def __init__(
        self,
        code: str = "credentials_not_allowed",
        reason: str = "试用抓取仅允许明确声明为免凭据的抓取器。",
    ) -> None:
        self.code = code
        self.reason = reason
        super().__init__(code)


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
        settings = get_settings()
        limits = httpx.Limits(max_connections=16, max_keepalive_connections=8)
        timeout = httpx.Timeout(
            settings.http_request_timeout_seconds,
            connect=settings.http_connect_timeout_seconds,
            read=settings.http_read_timeout_seconds,
        )
        return cls(
            httpx.AsyncClient(
                limits=limits,
                timeout=timeout,
                follow_redirects=True,
                trust_env=settings.http_trust_env,
            )
        )

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        host = httpx.URL(url).host or ""
        async with self._semaphores[host]:
            for attempt in range(self.retries + 1):
                try:
                    response = await self._stream_get(url, **kwargs)
                    if response.status_code not in {502, 503, 504, 429} or attempt == self.retries:
                        return response
                    delay = min(parse_retry_after(response.headers.get("retry-after")) or 0, 30.0)
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
            headers = dict(response.headers)
            # aiter_bytes() yields decoded content.  A reconstructed response must not
            # advertise the original wire encoding or compressed content length.
            headers.pop("content-encoding", None)
            headers.pop("content-length", None)
            return httpx.Response(
                response.status_code,
                headers=headers,
                content=b"".join(chunks),
                request=request,
                extensions=response.extensions,
            )
        finally:
            await response.aclose()

    @asynccontextmanager
    async def stream(self, url: str, **kwargs: object):
        """Open a bounded request while sharing the ingestion host limit."""
        host = httpx.URL(url).host or ""
        async with self._semaphores[host]:
            async with self.client.stream("GET", url, **kwargs) as response:
                yield response


def public_headers(headers: dict[str, str]) -> dict[str, str]:
    """Keep public API requests free of configured credentials and cookies."""
    blocked = {"authorization", "authentication", "cookie", "set-cookie", "proxy-authorization"}
    sensitive_parts = ("api-key", "api_key", "token", "secret", "credential")
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in blocked
        and "authorization" not in name.lower()
        and "authentication" not in name.lower()
        and not name.lower().startswith("x-auth")
        and not any(part in name.lower() for part in sensitive_parts)
    }


def response_result(response: httpx.Response, **values: object) -> FetchResult:
    headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower() not in {"cookie", "set-cookie", "authorization"}
    }
    remaining = response.headers.get("x-ratelimit-remaining")
    values.setdefault("outcome", FetchOutcome.SUCCEEDED)
    values.setdefault("retry_after_seconds", parse_retry_after(response.headers.get("retry-after")))
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
    def __init__(self, policy: HttpPolicy, credentials: object | None = None):
        self.policy = policy
        self.credentials = credentials

    def for_method(self, method: AccessMethod, *, credential_free_only: bool = False) -> Fetcher:
        if credential_free_only:
            from newsradar.ingestion.trial import has_sensitive_trial_headers

            if has_sensitive_trial_headers(method):
                raise TrialCredentialFreeFetcherRequiredError(
                    "sensitive_headers_not_allowed",
                    "试用抓取不允许携带认证或 Cookie 请求头。",
                )
        host = (httpx.URL(str(method.url)).host or "").lower()
        path = httpx.URL(str(method.url)).path
        if credential_free_only and not self._is_explicitly_credential_free(method, host, path):
            raise TrialCredentialFreeFetcherRequiredError

        from .arxiv import ArxivFetcher
        from .bluesky import BlueskyFetcher
        from .credentials import EnvironmentCredentials
        from .gdelt import GdeltFetcher
        from .github import GitHubFetcher
        from .google_news import GoogleNewsFetcher
        from .hackernews import HackerNewsFetcher
        from .mastodon import MastodonFetcher
        from .reddit import RedditFetcher
        from .rss import RssFetcher
        from .youtube import YouTubeFetcher

        if host == "hacker-news.firebaseio.com":
            return HackerNewsFetcher(self.policy)
        if host == "api.github.com":
            return GitHubFetcher(self.policy, self.credentials or EnvironmentCredentials())
        if host == "export.arxiv.org":
            return ArxivFetcher(self.policy)
        if host == "public.api.bsky.app":
            return BlueskyFetcher(self.policy)
        if host == "api.gdeltproject.org":
            return GdeltFetcher(self.policy)
        if host == "oauth.reddit.com":
            return RedditFetcher(self.policy, self.credentials or EnvironmentCredentials())
        if host == "www.googleapis.com" and path == "/youtube/v3/channels":
            return YouTubeFetcher(self.policy, self.credentials or EnvironmentCredentials())
        if host == "news.google.com" and method.kind is AccessKind.RSS:
            return GoogleNewsFetcher(self.policy)
        if method.kind is AccessKind.PUBLIC_API and (
            path.startswith("/api/v1/accounts/") or path == "/api/v1/timelines/public"
        ):
            return MastodonFetcher(self.policy)
        if method.kind in {AccessKind.RSS, AccessKind.ATOM}:
            return RssFetcher(self.policy)
        raise ValueError(f"unsupported_fetch_method:{method.kind.value}")

    @staticmethod
    def _is_explicitly_credential_free(method: AccessMethod, host: str, path: str) -> bool:
        """Allow trial construction only for fetchers which never consult credentials."""
        if host in {
            "hacker-news.firebaseio.com",
            "api.github.com",
            "export.arxiv.org",
            "public.api.bsky.app",
            "api.gdeltproject.org",
        }:
            return True
        if host == "news.google.com" and method.kind is AccessKind.RSS:
            return True
        if method.kind in {AccessKind.RSS, AccessKind.ATOM}:
            return True
        return method.kind is AccessKind.PUBLIC_API and (
            path.startswith("/api/v1/accounts/") or path == "/api/v1/timelines/public"
        )
