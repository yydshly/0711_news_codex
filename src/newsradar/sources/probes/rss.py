from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import feedparser

from newsradar.sources.schema import SourceStatus

from .base import BaseProbe, ProbeOutcome, ProbeSample, schema_fingerprint, summarize_samples


def feed_datetime(entry: dict) -> datetime | None:
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct:
        return datetime(*struct[:6], tzinfo=UTC)
    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            parsed = parsedate_to_datetime(raw)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            return None
    return None


class RssProbe(BaseProbe):
    async def parse(self, source, method, response, started, latency_ms):
        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"Invalid feed: {parsed.bozo_exception}")
        samples = [
            ProbeSample(
                external_id=entry.get("id") or entry.get("guid"),
                title=entry.get("title"),
                canonical_url=entry.get("link"),
                published_at=feed_datetime(entry),
                author=entry.get("author"),
                summary=entry.get("summary") or entry.get("description"),
                content=(entry.get("content") or [{}])[0].get("value")
                if entry.get("content")
                else None,
                raw_keys=sorted(entry.keys()),
            )
            for entry in parsed.entries[:5]
        ]
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
            f"Parsed {len(samples)} feed samples; field completeness {completeness:.0%}",
            latency_ms=latency_ms,
            sample_count=len(samples),
            samples=samples,
            field_completeness=completeness,
            duplicate_ratio=duplicates,
            latest_published_at=latest,
            schema_fingerprint=schema_fingerprint([dict(entry) for entry in parsed.entries[:5]]),
            **self.response_metadata(response),
        )
