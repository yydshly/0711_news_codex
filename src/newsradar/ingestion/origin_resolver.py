from __future__ import annotations

import ipaddress
from urllib.parse import urljoin, urlsplit

import httpx

from newsradar.ingestion.attribution import Attribution, OriginResolutionStatus


class OriginResolver:
    """Resolve an aggregator link through redirects without reading article content."""

    def __init__(self, client: httpx.AsyncClient, *, max_hops: int = 5):
        self.client = client
        self.max_hops = max_hops

    async def resolve(self, url: str) -> Attribution:
        discovery_url = url
        try:
            current = self._require_public_https(url)
        except ValueError:
            return self._unresolved(discovery_url)

        seen: set[str] = set()
        for _ in range(self.max_hops):
            if current in seen:
                return self._too_many(discovery_url)
            seen.add(current)
            try:
                async with self.client.stream("GET", current, follow_redirects=False) as response:
                    if not response.is_redirect:
                        return self._from_final_url(current, discovery_url)
                    location = response.headers.get("location")
                    if not location:
                        return self._unresolved(discovery_url)
                    current = self._require_public_https(urljoin(current, location))
            except (httpx.HTTPError, ValueError):
                return self._unresolved(discovery_url)
        return self._too_many(discovery_url)

    @staticmethod
    def _require_public_https(url: str) -> str:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme != "https" or not host or parts.username or parts.password:
            raise ValueError("non_public_https_url")
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
            raise ValueError("non_public_host")
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError("non_public_host")
        except ValueError as exc:
            if str(exc) == "non_public_host":
                raise
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
