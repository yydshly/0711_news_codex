from __future__ import annotations

import ipaddress
import time
from urllib.parse import urljoin, urlsplit

import httpx

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.sources.schema import AcquisitionAuth, AcquisitionCandidate

from .schema import has_sensitive_query


class UnsafeProbeUrl(Exception):
    pass


class ProbeAuthenticationRequired(Exception):
    pass


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
    blocked = (
        "cookie",
        "authorization",
        "authentication",
        "api-key",
        "api_key",
        "token",
        "secret",
        "credential",
    )
    if (
        client.trust_env
        or client.follow_redirects
        or getattr(client, "_mounts", None)
        or bool(list(client.cookies.jar))
        or any(any(part in k.lower() for part in blocked) for k in client.headers)
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
        request = client.build_request("GET", current, headers={})
        response = await client.send(request, stream=True, follow_redirects=False)
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
