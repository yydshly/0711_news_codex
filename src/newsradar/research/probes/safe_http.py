from __future__ import annotations

import ipaddress
import time
from urllib.parse import urljoin, urlsplit
from weakref import WeakSet

import httpx

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.settings import get_settings
from newsradar.sources.schema import AcquisitionAuth, AcquisitionCandidate

from .schema import has_sensitive_query


class UnsafeProbeUrl(Exception):
    pass


class ProbeAuthenticationRequired(Exception):
    pass


_PROBE_HEADERS = {
    "User-Agent": "NewsCodexResearchProbe/0.1",
    "Accept": "application/json, application/feed+json, application/xml, text/xml",
}
_OWNED_SAFE_CLIENTS: WeakSet[httpx.AsyncClient] = WeakSet()


def new_safe_probe_client() -> httpx.AsyncClient:
    """Create the only network client trusted for a live research probe."""
    settings = get_settings()
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(20),
        trust_env=settings.http_trust_env,
        follow_redirects=False,
        headers=_PROBE_HEADERS,
    )
    _OWNED_SAFE_CLIENTS.add(client)
    return client


def network_preflight(candidate: AcquisitionCandidate) -> None:
    if candidate.authentication is not AcquisitionAuth.NONE:
        raise ProbeAuthenticationRequired()


def _safe_url(url: str, client: httpx.AsyncClient) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or not parsed.hostname
        or has_sensitive_query(url)
    ):
        raise UnsafeProbeUrl()
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeProbeUrl()
    # Unit-test transports never leave the process.
    if type(client._transport).__name__ == "MockTransport":  # noqa: SLF001
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return  # audited hostname; let HTTPX return any actual DNS/network failure
    if not address.is_global:
        raise UnsafeProbeUrl()


def _safe_client(policy: HttpPolicy) -> httpx.AsyncClient:
    client = policy.client
    is_mock_transport = type(client._transport).__name__ == "MockTransport"  # noqa: SLF001
    if (
        (client.trust_env and client not in _OWNED_SAFE_CLIENTS)
        or client.follow_redirects
        or bool(list(client.cookies.jar))
        or (client not in _OWNED_SAFE_CLIENTS and not is_mock_transport)
    ):
        raise UnsafeProbeUrl()
    return client


async def safe_get(policy: HttpPolicy, candidate: AcquisitionCandidate, url: str) -> httpx.Response:
    """A bounded no-credential GET with explicit validated redirect hops."""
    network_preflight(candidate)
    client = _safe_client(policy)
    started = time.perf_counter()
    current = url
    for _ in range(6):
        _safe_url(current, client)
        # Build a standalone request: AsyncClient.build_request() merges caller
        # defaults and cookies, which is unsafe even when their names look benign.
        request = httpx.Request("GET", current, headers=_PROBE_HEADERS)
        response = await client.send(request, stream=True, follow_redirects=False)
        # HTTPX accepts upstream Set-Cookie headers into the client jar even when
        # the standalone request cannot send cookies.  Research probes are
        # stateless, so discard that response state before any later request.
        client.cookies.clear()
        if response.is_redirect:
            location = response.headers.get("location")
            await response.aclose()
            if not location:
                raise UnsafeProbeUrl()
            current = urljoin(current, location)
            continue
        size = 0
        chunks: list[bytes] = []
        try:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 2_000_000:
                    raise ValueError("response_too_large")
                chunks.append(chunk)
            return httpx.Response(
                response.status_code,
                headers={
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() not in {"content-encoding", "content-length"}
                },
                content=b"".join(chunks),
                request=request,
                extensions={"research_latency_ms": (time.perf_counter() - started) * 1000},
            )
        finally:
            await response.aclose()
    raise UnsafeProbeUrl()
