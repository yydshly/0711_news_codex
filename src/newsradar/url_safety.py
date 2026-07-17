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
_NON_CONTENT_ROOTS = frozenset(
    {
        "api",
        "aggregate",
        "aggregator",
        "archive",
        "archives",
        "atom",
        "author",
        "authors",
        "categories",
        "category",
        "feed",
        "feeds",
        "list",
        "listing",
        "rss",
        "search",
        "sitemap",
        "tag",
        "tags",
        "topic",
        "topics",
    }
)
_NON_CONTENT_LEAVES = frozenset(
    {
        "all",
        "archive",
        "archives",
        "articles",
        "atom",
        "atom.xml",
        "blog",
        "browse",
        "categories",
        "category",
        "directory",
        "feed",
        "feeds",
        "home",
        "index",
        "index.html",
        "items",
        "latest",
        "list",
        "listing",
        "news",
        "overview",
        "posts",
        "press",
        "releases",
        "results",
        "rss",
        "rss.xml",
        "stories",
        "tags",
        "topics",
        "updates",
        "latest-news",
        "news-list",
        "news-releases",
        "press-releases",
    }
)
_CONTENT_CONTAINER_SEGMENTS = frozenset(
    {"article", "articles", "post", "posts", "release", "releases", "story", "stories"}
)
_NON_CONTENT_SEGMENTS = _NON_CONTENT_ROOTS | {"page"}
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
_NON_CONTENT_SUFFIXES = (".atom", ".json", ".rss", ".xml")
_NON_CONTENT_SLUG_SUFFIXES = ("-archive", "-feed", "-index", "-list", "-listing")


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


def path_is_content_identity(value: str, *, hostname: str | None = None) -> bool:
    decoded = _bounded_decoded_path(value)
    if decoded is None or any(separator in decoded for separator in ("?", "&", ";")):
        return False
    segments = tuple(segment.casefold() for segment in decoded.split("/") if segment)
    if not segments:
        return False
    blocked_segments = tuple(
        (index, segment)
        for index, segment in enumerate(segments)
        if segment in _NON_CONTENT_SEGMENTS
    )
    github_release_tag = (
        hostname is not None
        and hostname.casefold() in _GITHUB_HOSTS
        and len(segments) == 5
        and segments[2:4] == ("releases", "tag")
    )
    if blocked_segments and not (github_release_tag and blocked_segments == ((3, "tag"),)):
        return False
    leaf = segments[-1]
    if (
        leaf in _CONTENT_CONTAINER_SEGMENTS
        or leaf in _NON_CONTENT_LEAVES
        or leaf.endswith((*_NON_CONTENT_SUFFIXES, *_NON_CONTENT_SLUG_SUFFIXES))
    ):
        return False
    if _is_date_archive(segments):
        return False
    if _content_shaped_leaf(leaf):
        return True
    return len(segments) > 1 and segments[-2] in _CONTENT_CONTAINER_SEGMENTS


def _bounded_decoded_path(value: str) -> str | None:
    current = value
    for _ in range(MAX_PATH_UNQUOTE_ROUNDS):
        if _INVALID_PERCENT_ESCAPE.search(current) or not url_text_is_safe(current):
            return None
        try:
            decoded = unquote(current, errors="strict")
        except (UnicodeDecodeError, ValueError):
            return None
        if decoded == current:
            return current
        current = decoded
    try:
        decoded = unquote(current, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    return current if decoded == current else None


def _is_date_archive(segments: tuple[str, ...]) -> bool:
    for index, segment in enumerate(segments):
        if len(segment) == 4 and segment.isdigit() and 1900 <= int(segment) <= 2100:
            tail = segments[index:]
            return len(tail) <= 3 and all(part.isdigit() for part in tail)
    return False


def _content_shaped_leaf(value: str) -> bool:
    return (
        "-" in value
        or any(character.isdigit() for character in value)
        or value.endswith((".htm", ".html"))
    )


def _decoded_path_is_unsafe(value: str) -> bool:
    if _INVALID_PERCENT_ESCAPE.search(value) or not url_text_is_safe(value):
        return True
    for raw_segment in _PATH_TOKEN_SEPARATOR.split(value):
        key = re.split(r"[:=]", raw_segment, maxsplit=1)[0]
        normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
        if normalized in _SENSITIVE_PATH_KEYS:
            return True
    return False
