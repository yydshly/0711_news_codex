from __future__ import annotations

_BLOCKED_REQUEST_HEADERS = frozenset(
    {
        "authorization",
        "authentication",
        "cookie",
        "set-cookie",
        "proxy-authorization",
    }
)
_SENSITIVE_HEADER_PARTS = ("api-key", "api_key", "token", "secret", "credential")


def is_sensitive_request_header(name: str) -> bool:
    """Return whether a request header may carry authentication material."""
    normalized = name.lower()
    return (
        normalized in _BLOCKED_REQUEST_HEADERS
        or "authorization" in normalized
        or "authentication" in normalized
        or normalized.startswith("x-auth")
        or any(part in normalized for part in _SENSITIVE_HEADER_PARTS)
    )
