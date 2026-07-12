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


def require_same_origin(
    origin: str | None,
    host: str | None,
    *,
    fetch_site: str | None = None,
) -> None:
    if not origin or not host:
        raise UnsafeWrite("same origin is required")
    if origin == "null":
        require_loopback_host(host)
        if fetch_site == "same-origin":
            return
        raise UnsafeWrite("same origin is required")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host.lower():
        raise UnsafeWrite("same origin is required")


def consume_one_time_token(state: dict, token: str) -> None:
    tokens = state.get("tokens", [])
    if not isinstance(token, str) or token not in tokens:
        raise UnsafeWrite("invalid or reused token")
    tokens.remove(token)
    state["tokens"] = tokens
