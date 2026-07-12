from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from hashlib import sha256
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from newsradar.ingestion.schema import NormalizedRawItem

_TRACKING_PARAMETERS = {"fbclid"}
_TITLE_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_TITLE_SUFFIX = re.compile(r"\s*[-|—:]\s*[^-|—:]+$")
_MIN_TITLE_TOKENS = 2
_SEVEN_DAYS_SECONDS = 7 * 24 * 60 * 60


def normalize_url(value: str) -> str:
    """Return a local, deterministic URL identity without fetching the URL."""
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    default_port = (parsed.scheme.lower() == "https" and port == 443) or (
        parsed.scheme.lower() == "http" and port == 80
    )
    netloc = hostname
    if port is not None and not default_port:
        netloc = f"{hostname}:{port}"
    if parsed.username:
        credentials = parsed.username
        if parsed.password:
            credentials = f"{credentials}:{parsed.password}"
        netloc = f"{credentials}@{netloc}"
    query = sorted(
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMETERS
    )
    return urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path, urlencode(query, doseq=True), "")
    )


def normalize_title(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", unescape(value)).split())


def content_hash(item: NormalizedRawItem) -> str:
    """Hash content-bearing fields only, deliberately excluding observation metadata."""
    payload = {
        "title": normalize_title(item.title),
        "authors": list(item.authors),
        "summary": item.summary,
        "content": item.content,
        "canonical_url": normalize_url(str(item.canonical_url)),
        "published_at": _timestamp_value(item.published_at),
        "source_updated_at": _timestamp_value(item.source_updated_at),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _timestamp_value(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(UTC).isoformat()
    return value.isoformat()


def _title_tokens(value: str) -> set[str]:
    normalized = normalize_title(value).lower()
    normalized = _TITLE_SUFFIX.sub("", normalized)
    normalized = _TITLE_PUNCTUATION.sub(" ", normalized)
    return set(normalized.split())


def title_similarity(left: NormalizedRawItem, right: NormalizedRawItem) -> float:
    """Return conservative token similarity for title-candidate detection."""
    if left.published_at is None or right.published_at is None:
        return 0.0
    if abs((left.published_at - right.published_at).total_seconds()) > _SEVEN_DAYS_SECONDS:
        return 0.0
    left_tokens = _title_tokens(left.title)
    right_tokens = _title_tokens(right.title)
    if min(len(left_tokens), len(right_tokens)) < _MIN_TITLE_TOKENS:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
