from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Mapping
from urllib.parse import urljoin, urlsplit

import httpx

from newsradar.ingestion.attribution import Attribution, OriginResolutionStatus
from newsradar.ingestion.fetchers.base import HttpPolicy, public_headers


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return address.is_global and not address.is_multicast and not address.is_reserved


class OriginResolver:
    """Resolve an aggregator link through redirects without reading article content."""

    def __init__(
        self,
        policy: HttpPolicy | httpx.AsyncClient,
        *,
        max_hops: int = 5,
        headers: Mapping[str, str] | None = None,
    ):
        self.policy = policy if isinstance(policy, HttpPolicy) else HttpPolicy(policy)
        self.max_hops = max_hops
        self.headers = public_headers(dict(headers or {}))

    async def resolve(self, url: str) -> Attribution:
        discovery_url = url
        try:
            current = await self._require_public_https(url)
        except ValueError:
            return self._unresolved(discovery_url)

        seen: set[str] = set()
        for _ in range(self.max_hops):
            if current in seen:
                return self._too_many(discovery_url)
            seen.add(current)
            try:
                async with self.policy.stream(
                    current, follow_redirects=False, headers=self.headers
                ) as response:
                    if not response.is_redirect:
                        return self._from_final_url(current, discovery_url)
                    location = response.headers.get("location")
                    if not location:
                        return self._unresolved(discovery_url)
                    current = await self._require_public_https(urljoin(current, location))
            except (httpx.HTTPError, OSError, ValueError):
                return self._unresolved(discovery_url)
        return self._too_many(discovery_url)

    @staticmethod
    async def _require_public_https(url: str) -> str:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme != "https" or not host or parts.username or parts.password:
            raise ValueError("non_public_https_url")
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
            raise ValueError("non_public_host")
        try:
            address = ipaddress.ip_address(host)
            if not _is_public_address(address):
                raise ValueError("non_public_host")
            return url
        except ValueError as exc:
            if str(exc) == "non_public_host":
                raise
        # httpx does not expose a supported way to pin this connection to these
        # addresses while preserving HTTPS hostname/SNI verification. Resolve at
        # every hop and fail closed on lookup errors; a custom transport is
        # required for strict DNS-rebinding-resistant address pinning.
        results = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
        if not results:
            raise ValueError("unresolved_host")
        for result in results:
            if not _is_public_address(ipaddress.ip_address(result[4][0])):
                raise ValueError("non_public_host")
        return url

    @staticmethod
    def _publisher_name(host: str) -> str | None:
        host = host.lower().removeprefix("www.")
        if host == "news.google.com":
            return None
        label = host.split(".")[0]
        return label.replace("-", " ").title() if label else None

    def _from_final_url(self, url: str, discovery_url: str) -> Attribution:
        name = self._publisher_name(urlsplit(url).hostname or "")
        if not name:
            return self._unresolved(discovery_url)
        return Attribution(name, url, discovery_url, OriginResolutionStatus.RESOLVED)

    @staticmethod
    def _unresolved(discovery_url: str) -> Attribution:
        return Attribution(None, None, discovery_url, OriginResolutionStatus.UNRESOLVED)

    @staticmethod
    def _too_many(discovery_url: str) -> Attribution:
        return Attribution(None, None, discovery_url, OriginResolutionStatus.TOO_MANY_REDIRECTS)
