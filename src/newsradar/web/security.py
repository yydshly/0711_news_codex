from __future__ import annotations

from urllib.parse import urlsplit


class UnsafeWrite(ValueError):
    """Raised when a local-only write request violates browser safety rules."""


def require_loopback_host(host: str | None) -> None:
    if not host:
        raise UnsafeWrite("loopback host is required")
    name = host.rsplit(":", 1)[0].strip("[]").lower()
    if name not in {"127.0.0.1", "localhost", "::1"}:
        raise UnsafeWrite("loopback host is required")


def require_same_origin(origin: str | None, host: str | None) -> None:
    if not origin or not host:
        raise UnsafeWrite("same origin is required")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host.lower():
        raise UnsafeWrite("same origin is required")
