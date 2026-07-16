"""Pure coverage metrics derived from immutable event-version payloads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvidenceCoverageMetrics:
    events_with_official_root: int = 0
    events_with_one_professional_root: int = 0
    events_with_two_professional_roots: int = 0
    confirmed_event_count: int = 0


def summarize_event_version_payloads(
    payloads: Iterable[Mapping[str, object]],
) -> EvidenceCoverageMetrics:
    """Count only safe fields from exact immutable version payloads."""
    official = one_professional = two_professional = confirmed = 0
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        raw_summary = payload.get("evidence_summary")
        summary = raw_summary if isinstance(raw_summary, Mapping) else {}
        official_roots = _count(summary.get("official_roots"))
        professional_roots = _count(summary.get("professional_roots"))
        official += int(official_roots > 0)
        one_professional += int(professional_roots == 1)
        two_professional += int(professional_roots >= 2)
        confirmed += int(payload.get("status") == "confirmed")
    return EvidenceCoverageMetrics(
        events_with_official_root=official,
        events_with_one_professional_root=one_professional,
        events_with_two_professional_roots=two_professional,
        confirmed_event_count=confirmed,
    )


def _count(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )
