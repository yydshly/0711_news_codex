from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    EventItemRecord,
    EventModelRunRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    RawItemRecord,
)


@dataclass(frozen=True, slots=True)
class EventRow:
    event_id: int
    status: str
    zh_title: str
    zh_summary: str
    occurred_at: datetime | None
    heat: float
    score_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EventHomeView:
    events: tuple[EventRow, ...]


@dataclass(frozen=True, slots=True)
class EventPage:
    events: tuple[EventRow, ...]
    filters: dict[str, object]


@dataclass(frozen=True, slots=True)
class EvidenceRow:
    title: str
    original_url: str | None
    published_at: datetime | None
    role: str
    root_evidence_key: str
    independent: bool
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EventDetailView:
    event: EventRow
    evidence: tuple[EvidenceRow, ...]
    algorithm_version: str
    model_versions: tuple[str, ...]
    minimax_degraded: bool

    @property
    def score_reasons(self) -> tuple[str, ...]:
        return self.event.score_reasons


class EventQueryService:
    """Read-only projection of published event versions for the web UI."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def home(
        self, window_hours: int = 24, limit: int = 20, *, now: datetime | None = None
    ) -> EventHomeView:
        now = now or datetime.now(UTC)
        filters = {
            "status": "confirmed",
            "since": now - timedelta(hours=window_hours),
            "limit": limit,
        }
        return EventHomeView(events=self._list(filters))

    def list_events(
        self,
        filters: dict[str, object] | None = None,
        *,
        visibility: str = "current",
    ) -> EventPage:
        active = dict(filters or {})
        active.setdefault("visibility", visibility)
        return EventPage(events=self._list(active), filters=active)

    def list_emerging(self, limit: int = 50) -> EventPage:
        filters: dict[str, object] = {"status": "emerging", "limit": limit}
        return EventPage(events=self._list(filters), filters=filters)

    def get_event(self, event_id: int) -> EventDetailView | None:
        row = self._event_row(event_id)
        if row is None:
            return None
        version = self._current_version(event_id)
        payload = version.payload if version is not None else {}
        evidence_by_item = {
            item.get("raw_item_id"): item
            for item in (payload.get("evidence", ()) if isinstance(payload, dict) else ())
            if isinstance(item, dict) and isinstance(item.get("raw_item_id"), int)
        }
        evidence = tuple(
            EvidenceRow(
                title=item.title or "未命名原始证据",
                original_url=_safe_external_url(item.original_url or item.canonical_url),
                published_at=item.published_at,
                role=str(evidence_by_item.get(item.id, {}).get("role", "未标注")),
                root_evidence_key=str(
                    evidence_by_item.get(item.id, {}).get("root_evidence_key", "")
                ),
                independent=bool(evidence_by_item.get(item.id, {}).get("independent", False)),
                limitations=tuple(
                    str(value)
                    for value in evidence_by_item.get(item.id, {}).get("limitations", ())
                ),
            )
            for item in self.session.scalars(
                select(RawItemRecord)
                .join(EventItemRecord, EventItemRecord.raw_item_id == RawItemRecord.id)
                .where(
                    EventItemRecord.event_id == event_id,
                    EventItemRecord.removed_version_number.is_(None),
                )
                .order_by(RawItemRecord.published_at.desc(), RawItemRecord.id.desc())
            )
        )
        enrichment = payload.get("enrichment") if isinstance(payload, dict) else None
        degraded = isinstance(enrichment, dict) and enrichment.get("origin") == "rule_fallback"
        model_versions = tuple(
            sorted(
                {
                    run.algorithm_version
                    for run in self.session.scalars(
                        select(EventModelRunRecord).where(EventModelRunRecord.event_id == event_id)
                    )
                }
            )
        )
        algorithm_version = str(self._score_breakdown(event_id).get("rule_version", "unknown"))
        return EventDetailView(row, evidence, algorithm_version, model_versions, degraded)

    def _list(self, filters: dict[str, object]) -> tuple[EventRow, ...]:
        statement = select(EventRecord.id).where(
            EventRecord.current_version_number > 0,
            EventRecord.visibility == filters.get("visibility", "current"),
        )
        if status := filters.get("status"):
            statement = statement.where(EventRecord.status == status)
        if since := filters.get("since"):
            statement = statement.where(EventRecord.occurred_at >= since)
        ids = self.session.scalars(
            statement.order_by(EventRecord.occurred_at.desc(), EventRecord.id.desc())
        ).all()
        rows = [row for event_id in ids if (row := self._event_row(event_id)) is not None]
        rows.sort(
            key=lambda row: (
                -row.heat,
                -(row.occurred_at or datetime.min.replace(tzinfo=UTC)).timestamp(),
                row.event_id,
            )
        )
        return tuple(rows[: int(filters.get("limit", 100))])

    def _event_row(self, event_id: int) -> EventRow | None:
        event = self.session.get(EventRecord, event_id)
        if event is None or event.current_version_number <= 0:
            return None
        version = self._current_version(event_id)
        if version is None:
            return None
        score = self.session.scalar(
            select(EventScoreRecord).where(
                EventScoreRecord.event_id == event_id,
                EventScoreRecord.version_number == event.current_version_number,
            )
        )
        breakdown = dict(score.breakdown) if score else {}
        return EventRow(
            event_id,
            event.status,
            version.zh_title or "未命名事件",
            version.zh_summary or "暂无摘要",
            event.occurred_at,
            score.heat if score else 0,
            tuple(str(reason) for reason in breakdown.get("reasons", ())),
        )

    def _current_version(self, event_id: int) -> EventVersionRecord | None:
        event = self.session.get(EventRecord, event_id)
        if event is None:
            return None
        return self.session.scalar(
            select(EventVersionRecord).where(
                EventVersionRecord.event_id == event_id,
                EventVersionRecord.version_number == event.current_version_number,
            )
        )

    def _score_breakdown(self, event_id: int) -> dict:
        event = self.session.get(EventRecord, event_id)
        if event is None:
            return {}
        score = self.session.scalar(
            select(EventScoreRecord).where(
                EventScoreRecord.event_id == event_id,
                EventScoreRecord.version_number == event.current_version_number,
            )
        )
        return dict(score.breakdown) if score else {}


def _safe_external_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None
