from __future__ import annotations

from typing import Any

from newsradar.sources.schema import SourceStatus

from .base import (
    BaseProbe,
    ProbeOutcome,
    ProbeSample,
    parse_datetime,
    schema_fingerprint,
    summarize_samples,
)


def first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def extract_items(payload: Any) -> tuple[list[dict[str, Any]], bool]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], False
    if isinstance(payload, dict):
        for key in ("items", "results", "articles", "posts", "feed", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)], bool(
                    payload.get("next") or payload.get("cursor") or payload.get("nextPageToken")
                )
        return [payload], False
    raise ValueError("JSON response must be an object or array")


def normalize_item(item: dict[str, Any]) -> ProbeSample:
    engagement = first(item, "score", "likes", "like_count", "stargazers_count", "view_count")
    author = first(item, "author", "by", "user", "login", "channelTitle")
    if isinstance(author, dict):
        author = first(author, "login", "name", "displayName", "handle")
    return ProbeSample(
        external_id=str(first(item, "id", "external_id", "uri", "node_id") or "") or None,
        title=first(item, "title", "name", "headline", "text"),
        canonical_url=first(item, "url", "html_url", "link", "external_url"),
        published_at=parse_datetime(
            first(
                item,
                "published_at",
                "published",
                "created_at",
                "createdAt",
                "time",
                "date",
                "seendate",
            )
        ),
        author=str(author) if author is not None else None,
        summary=first(item, "summary", "description", "abstract", "body"),
        content=first(item, "content", "body", "text"),
        engagement=float(engagement) if isinstance(engagement, (int, float)) else None,
        discussion_url=first(item, "discussion_url", "comments_url"),
        raw_keys=sorted(item.keys()),
    )


class JsonApiProbe(BaseProbe):
    async def parse(self, source, method, response, started, latency_ms):
        payload = response.json()
        raw_items, pagination = extract_items(payload)
        samples = [normalize_item(item) for item in raw_items[:5]]
        completeness, duplicates, latest = summarize_samples(source, samples)
        outcome = ProbeOutcome.SUCCESS if completeness >= 0.9 else ProbeOutcome.DEGRADED
        status = (
            SourceStatus.CANDIDATE if outcome == ProbeOutcome.SUCCESS else SourceStatus.DEGRADED
        )
        return self._result(
            source,
            method,
            started,
            outcome,
            status,
            f"Parsed {len(samples)} JSON samples; field completeness {completeness:.0%}",
            latency_ms=latency_ms,
            pagination_detected=pagination,
            sample_count=len(samples),
            samples=samples,
            field_completeness=completeness,
            duplicate_ratio=duplicates,
            latest_published_at=latest,
            schema_fingerprint=schema_fingerprint(raw_items[:5]),
            **self.response_metadata(response),
        )
