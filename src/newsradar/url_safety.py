"""Fail-closed URL parsing shared by persistence and public projections."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import SplitResult, unquote, urlsplit

MAX_URL_INPUT_LENGTH = 4096
MAX_URL_IDENTITY_LENGTH = 1000
MAX_URL_QUERY_LENGTH = 2048
MAX_URL_QUERY_FIELDS = 32
MAX_PATH_UNQUOTE_ROUNDS = 4

_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_PATH_TOKEN_SEPARATOR = re.compile(r"[/?&;]+")
_SENSITIVE_PATH_KEYS = frozenset(
    {
        "token",
        "accesstoken",
        "apikey",
        "credential",
        "credentials",
        "password",
        "secret",
        "authorization",
        "bearer",
        "cookie",
        "session",
    }
)


def parse_safe_http_url(value: str | None) -> SplitResult | None:
    if not value or not url_text_is_safe(value):
        return None
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or len(parsed.query) > MAX_URL_QUERY_LENGTH
        or path_has_sensitive_key(parsed.path)
    ):
        return None
    return parsed


def bounded_url_identity(value: str) -> str | None:
    if not value or len(value) > MAX_URL_IDENTITY_LENGTH:
        return None
    return value


def normalized_http_netloc(parsed: SplitResult) -> str:
    hostname = parsed.hostname.casefold()
    host = f"[{hostname}]" if ":" in hostname else hostname
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{host}{port}"


def url_text_is_safe(value: str, *, max_length: int = MAX_URL_INPUT_LENGTH) -> bool:
    return (
        bool(value)
        and len(value) <= max_length
        and not any(
            character == "\\" or character.isspace() or unicodedata.category(character) == "Cc"
            for character in value
        )
    )


def path_has_sensitive_key(value: str) -> bool:
    current = value
    for _ in range(MAX_PATH_UNQUOTE_ROUNDS):
        if _decoded_path_is_unsafe(current):
            return True
        try:
            decoded = unquote(current, errors="strict")
        except (UnicodeDecodeError, ValueError):
            return True
        if decoded == current:
            return False
        current = decoded

    if _decoded_path_is_unsafe(current):
        return True
    try:
        decoded = unquote(current, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return True
    return decoded != current


def _decoded_path_is_unsafe(value: str) -> bool:
    if _INVALID_PERCENT_ESCAPE.search(value) or not url_text_is_safe(value):
        return True
    for raw_segment in _PATH_TOKEN_SEPARATOR.split(value):
        key = re.split(r"[:=]", raw_segment, maxsplit=1)[0]
        normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
        if normalized in _SENSITIVE_PATH_KEYS:
            return True
    return False
