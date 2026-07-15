from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import Float, Select, and_, case, cast, func, or_, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    EventItemRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    RawItemRecord,
)
from newsradar.events.operation_snapshots import (
    EventVersionRef,
    OperationSnapshotRef,
    event_snapshot_by_id,
    latest_complete_event_snapshot,
)
from newsradar.web.capability_queries import (
    EventQualityCoverageQueryService,
    EventQualityCoverageView,
)
from newsradar.web.i18n import zh_label

HOME_WINDOW_HOURS = 24
HOME_MIN_AI_RELEVANCE = 60
SCORE_DIMENSION_KEYS = (
    "ai_relevance",
    "source_coverage",
    "source_authority",
    "recency",
    "engagement_velocity",
    "novelty",
)

_URL_WITH_QUERY = re.compile(r"(?i)(https?://[^\s?#]+)[?#][^\s]*")
_FORBIDDEN_SENSITIVE_KEY = re.compile(
    r"(?i)\b(?:authorization|cookie|minimax_api_key|database_url)\b"
    r"(?:\s*[:=]\s*[^\s；，。]+)?"
)
_ASSIGNED_SECRET = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|token|secret|prompt)\b"
    r"\s*[:=]\s*[^\s；，。]+"
)


@dataclass(frozen=True, slots=True)
class EventRow:
    event_id: int
    visibility: str
    status: str
    display_tier: str
    rank_score: float
    category: str | None
    zh_title: str
    zh_summary: str
    why_it_matters: str
    occurred_at: datetime | None
    heat: float
    importance: float
    credibility: float
    independent_root_count: int
    enrichment_origin: str
    score_reasons: tuple[str, ...]
    tier_reasons: tuple[str, ...]
    detail_href: str


@dataclass(frozen=True, slots=True)
class EventSection:
    title: str
    category: str
    events: tuple[EventRow, ...]


@dataclass(frozen=True, slots=True)
class EventHomeView:
    events: tuple[EventRow, ...]
    hotspots: tuple[EventRow, ...]
    sections: tuple[EventSection, ...]
    signal_count: int
    audit_count: int
    current_confirmed_count: int
    current_emerging_count: int
    coverage: EventQualityCoverageView
    snapshot: SnapshotBannerView | None = None


@dataclass(frozen=True, slots=True)
class EventPage:
    events: tuple[EventRow, ...]
    filters: dict[str, object]


@dataclass(frozen=True, slots=True)
class SnapshotBannerView:
    operation_id: int
    window_hours: int
    window_end: datetime
    finished_at: datetime
    algorithm_versions: tuple[tuple[str, str], ...]
    skipped_newer_count: int


@dataclass(frozen=True, slots=True)
class OperationEventPage:
    events: tuple[EventRow, ...]
    filters: dict[str, object]
    snapshot: SnapshotBannerView
    tier_counts: tuple[tuple[str, int], ...]


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
class ScoreDimensionView:
    key: str
    label: str
    value: float
    reason: str


@dataclass(frozen=True, slots=True)
class ModelRunSummary:
    model: str
    purpose: str
    outcome: str
    latency_ms: float | None


@dataclass(frozen=True, slots=True)
class EventDetailView:
    event: EventRow
    evidence: tuple[EvidenceRow, ...]
    algorithm_version: str
    scores: tuple[ScoreDimensionView, ...]
    why_it_matters: str
    limitations: tuple[str, ...]
    model_runs: tuple[ModelRunSummary, ...]
    minimax_degraded: bool
    snapshot: SnapshotBannerView | None = None

    @property
    def score_reasons(self) -> tuple[str, ...]:
        return self.event.score_reasons

    @property
    def model_versions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(run.model for run in self.model_runs))

    def _score_value(self, key: str) -> float:
        return next((score.value for score in self.scores if score.key == key), 0.0)

    @property
    def ai_relevance(self) -> float:
        return self._score_value("ai_relevance")

    @property
    def source_coverage(self) -> float:
        return self._score_value("source_coverage")

    @property
    def source_authority(self) -> float:
        return self._score_value("source_authority")

    @property
    def recency(self) -> float:
        return self._score_value("recency")

    @property
    def engagement_velocity(self) -> float:
        return self._score_value("engagement_velocity")

    @property
    def novelty(self) -> float:
        return self._score_value("novelty")


@dataclass(frozen=True, slots=True)
class _VersionDisplay:
    status: str
    category: str | None
    display_tier: str
    occurred_at: datetime | None


class EventQueryService:
    """Read-only, bounded projections of complete published event snapshots."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def home(
        self,
        window_hours: int = HOME_WINDOW_HOURS,
        limit: int = 20,
        *,
        now: datetime | None = None,
    ) -> EventHomeView:
        now = now or datetime.now(UTC)
        since = now - timedelta(hours=window_hours)
        snapshots = self._projections(
            {
                "visibility": "current",
                "display_tier": "hotspot",
                "since": since,
                "until": now,
            }
        )
        complete_snapshots = tuple(
            snapshot for snapshot in snapshots if self._home_snapshot_is_complete(snapshot)
        )
        home_events = tuple(
            self._event_row(*snapshot) for snapshot in complete_snapshots
        )[:limit]
        sections = tuple(
            EventSection(
                title=zh_label("event_category", category),
                category=category,
                events=tuple(row for row in home_events if row.category == category),
            )
            for category in ("product_model", "research", "developer_tool", "company")
            if any(row.category == category for row in home_events)
        )
        status_counts = dict(
            self.session.execute(
                select(EventRecord.status, func.count(EventRecord.id))
                .where(
                    EventRecord.visibility == "current",
                    EventRecord.status.in_(("confirmed", "emerging")),
                    EventRecord.occurred_at >= since,
                    EventRecord.occurred_at <= now,
                )
                .group_by(EventRecord.status)
            ).all()
        )
        tier_counts = dict(
            self.session.execute(
                select(EventRecord.display_tier, func.count(EventRecord.id))
                .where(
                    EventRecord.visibility == "current",
                    EventRecord.occurred_at >= since,
                    EventRecord.occurred_at <= now,
                )
                .group_by(EventRecord.display_tier)
            ).all()
        )
        return EventHomeView(
            events=home_events,
            hotspots=home_events,
            sections=sections,
            signal_count=int(tier_counts.get("signal", 0)),
            audit_count=int(tier_counts.get("audit_only", 0)),
            current_confirmed_count=int(status_counts.get("confirmed", 0)),
            current_emerging_count=int(status_counts.get("emerging", 0)),
            coverage=EventQualityCoverageQueryService(self.session).build(now=now),
        )

    def list_events(
        self,
        filters: dict[str, object] | None = None,
        *,
        visibility: str = "current",
    ) -> EventPage:
        active = dict(filters or {})
        active.setdefault("visibility", visibility)
        active.setdefault("limit", 100)
        return EventPage(events=self._list(active), filters=active)

    def latest_operation_home(
        self, *, now: datetime | None = None, limit: int = 20
    ) -> EventHomeView | None:
        page = self.latest_operation_page(now=now)
        if page is None:
            return None
        hotspots = tuple(row for row in page.events if row.display_tier == "hotspot")[:limit]
        sections = tuple(
            EventSection(
                title=zh_label("event_category", category),
                category=category,
                events=tuple(row for row in hotspots if row.category == category),
            )
            for category in ("product_model", "research", "developer_tool", "company")
            if any(row.category == category for row in hotspots)
        )
        counts = Counter(row.status for row in page.events)
        tiers = dict(page.tier_counts)
        return EventHomeView(
            events=hotspots,
            hotspots=hotspots,
            sections=sections,
            signal_count=int(tiers.get("signal", 0)),
            audit_count=int(tiers.get("audit_only", 0)),
            current_confirmed_count=int(counts.get("confirmed", 0)),
            current_emerging_count=int(counts.get("emerging", 0)),
            coverage=EventQualityCoverageQueryService(self.session).build(
                now=page.snapshot.window_end
            ),
            snapshot=page.snapshot,
        )

    def list_emerging(self, limit: int = 50) -> EventPage:
        filters: dict[str, object] = {
            "status": "emerging",
            "visibility": "current",
            "limit": limit,
        }
        return EventPage(events=self._list(filters), filters=filters)

    def latest_operation_page(
        self,
        filters: dict[str, object] | None = None,
        *,
        now: datetime | None = None,
    ) -> OperationEventPage | None:
        snapshot = latest_complete_event_snapshot(self.session, now=now)
        if snapshot is None:
            return None
        active = dict(filters or {})
        rows = self._operation_rows(snapshot)
        filtered = self._filter_operation_rows(rows, active, snapshot.window_end)
        limit = _positive_limit(active.get("limit", 100), default=100)
        return OperationEventPage(
            events=filtered[:limit],
            filters=active,
            snapshot=_banner(snapshot),
            tier_counts=tuple(
                sorted(Counter(row.display_tier for row in rows).items())
            ),
        )

    def get_operation_event(
        self,
        event_id: int,
        operation_id: int,
        version_number: int,
        *,
        now: datetime | None = None,
    ) -> EventDetailView | None:
        snapshot = event_snapshot_by_id(self.session, operation_id, now=now)
        expected = EventVersionRef(event_id, version_number)
        if snapshot is None or expected not in snapshot.event_versions:
            return None
        record = self._version_snapshot(event_id, version_number)
        if record is None:
            return None
        event, version, score = record
        display = _version_display(version)
        if display is None:
            return None
        row = self._event_row(
            event,
            version,
            score,
            display=display,
            detail_href=_operation_detail_href(event_id, operation_id, version_number),
        )
        return self._detail_from_snapshot(
            event,
            version,
            score,
            version_number=version_number,
            row=row,
            snapshot=_banner(snapshot),
        )

    def get_event(self, event_id: int) -> EventDetailView | None:
        snapshot = self._snapshot(event_id)
        if snapshot is None:
            return None
        event, version, score = snapshot
        if event.visibility == "current" and not self._home_snapshot_is_complete(snapshot):
            return None
        return self._detail_from_snapshot(
            event,
            version,
            score,
            version_number=event.current_version_number,
            row=self._event_row(event, version, score),
        )

    def _detail_from_snapshot(
        self,
        event: EventRecord,
        version: EventVersionRecord,
        score: EventScoreRecord,
        *,
        version_number: int,
        row: EventRow,
        snapshot: SnapshotBannerView | None = None,
    ) -> EventDetailView:
        payload = version.payload if isinstance(version.payload, dict) else {}
        evidence_payload = _as_sequence(payload.get("evidence"))
        evidence_by_item = {
            item.get("raw_item_id"): item
            for item in evidence_payload
            if isinstance(item, dict) and isinstance(item.get("raw_item_id"), int)
        }
        evidence = tuple(
            EvidenceRow(
                title=_safe_display_text(item.title, "未命名原始证据", max_length=500),
                original_url=_safe_external_url(item.original_url or item.canonical_url),
                published_at=item.published_at,
                role=str(evidence_by_item.get(item.id, {}).get("role", "unknown")),
                root_evidence_key=_safe_display_text(
                    evidence_by_item.get(item.id, {}).get("root_evidence_key", ""),
                    "",
                    max_length=500,
                ),
                independent=bool(evidence_by_item.get(item.id, {}).get("independent", False)),
                limitations=_localized_limitations(
                    evidence_by_item.get(item.id, {}).get("limitations", ())
                ),
            )
            for item in self.session.scalars(
                select(RawItemRecord)
                .join(EventItemRecord, EventItemRecord.raw_item_id == RawItemRecord.id)
                .where(
                    EventItemRecord.event_id == event.id,
                    EventItemRecord.added_version_number <= version_number,
                    or_(
                        EventItemRecord.removed_version_number.is_(None),
                        EventItemRecord.removed_version_number > version_number,
                    ),
                )
                .order_by(RawItemRecord.published_at.desc(), RawItemRecord.id.desc())
            )
        )
        enrichment = payload.get("enrichment")
        enrichment = enrichment if isinstance(enrichment, dict) else {}
        breakdown = _score_breakdown(score)
        scores = tuple(
            ScoreDimensionView(
                key=key,
                label=zh_label("score_dimension", key),
                value=_numeric_score(breakdown.get(key)),
                reason=_score_dimension_reason(key, _numeric_score(breakdown.get(key))),
            )
            for key in SCORE_DIMENSION_KEYS
        )
        enrichment_limitations = _localized_limitations(enrichment.get("limitations"))
        limitations = tuple(
            dict.fromkeys(
                (
                    *enrichment_limitations,
                    *(item for evidence_row in evidence for item in evidence_row.limitations),
                )
            )
        )
        model_runs = _model_run_summaries(payload.get("model_runs"))
        origin = str(enrichment.get("origin", "rule_fallback"))
        return EventDetailView(
            event=row,
            evidence=evidence,
            algorithm_version=_safe_display_text(
                breakdown.get("rule_version"), "unknown", max_length=120
            ),
            scores=scores,
            why_it_matters=row.why_it_matters,
            limitations=limitations,
            model_runs=model_runs,
            minimax_degraded=origin == "rule_fallback",
            snapshot=snapshot,
        )

    def _list(self, filters: dict[str, object]) -> tuple[EventRow, ...]:
        return tuple(self._event_row(*snapshot) for snapshot in self._projections(filters))

    def _projections(
        self, filters: dict[str, object]
    ) -> tuple[tuple[EventRecord, EventVersionRecord, EventScoreRecord], ...]:
        statement = _published_snapshot_statement().where(
            EventRecord.current_version_number > 0,
            EventRecord.visibility == filters.get("visibility", "current"),
        )
        if status := filters.get("status"):
            statement = statement.where(EventRecord.status == status)
        if category := filters.get("category"):
            statement = statement.where(EventRecord.category == category)
        if display_tier := filters.get("display_tier"):
            statement = statement.where(EventRecord.display_tier == display_tier)
        if since := filters.get("since"):
            statement = statement.where(EventRecord.occurred_at >= since)
        if until := filters.get("until"):
            statement = statement.where(EventRecord.occurred_at <= until)
        if min_ai_relevance := filters.get("min_ai_relevance"):
            statement = statement.where(
                _safe_ai_relevance_expression(self.session.get_bind().dialect.name)
                >= float(min_ai_relevance)
            )
        statement = statement.order_by(
            EventRecord.rank_score.desc(),
            EventRecord.occurred_at.desc(),
            EventRecord.id.desc(),
        )
        if "limit" in filters:
            statement = statement.limit(int(filters["limit"]))
        return tuple(self.session.execute(statement))

    def _snapshot(
        self, event_id: int
    ) -> tuple[EventRecord, EventVersionRecord, EventScoreRecord] | None:
        return self.session.execute(
            _published_snapshot_statement().where(
                EventRecord.id == event_id, EventRecord.current_version_number > 0
            )
        ).one_or_none()

    def _version_snapshot(
        self, event_id: int, version_number: int
    ) -> tuple[EventRecord, EventVersionRecord, EventScoreRecord] | None:
        return self.session.execute(
            select(EventRecord, EventVersionRecord, EventScoreRecord)
            .join(EventVersionRecord, EventVersionRecord.event_id == EventRecord.id)
            .join(
                EventScoreRecord,
                and_(
                    EventScoreRecord.event_id == EventVersionRecord.event_id,
                    EventScoreRecord.version_number == EventVersionRecord.version_number,
                ),
            )
            .where(
                EventRecord.id == event_id,
                EventVersionRecord.version_number == version_number,
            )
        ).one_or_none()

    def _operation_rows(self, snapshot: OperationSnapshotRef) -> tuple[EventRow, ...]:
        refs = set(snapshot.event_versions)
        if not refs:
            return ()
        event_ids = {ref.event_id for ref in refs}
        statement = (
            select(EventRecord, EventVersionRecord, EventScoreRecord)
            .join(EventVersionRecord, EventVersionRecord.event_id == EventRecord.id)
            .join(
                EventScoreRecord,
                and_(
                    EventScoreRecord.event_id == EventVersionRecord.event_id,
                    EventScoreRecord.version_number == EventVersionRecord.version_number,
                ),
            )
            .where(EventVersionRecord.event_id.in_(event_ids))
        )
        rows: list[EventRow] = []
        for event, version, score in self.session.execute(statement):
            ref = EventVersionRef(event.id, version.version_number)
            if ref not in refs:
                continue
            display = _version_display(version)
            if display is None:
                continue
            rows.append(
                self._event_row(
                    event,
                    version,
                    score,
                    display=display,
                    detail_href=_operation_detail_href(
                        event.id, snapshot.operation_id, version.version_number
                    ),
                )
            )
        return tuple(
            sorted(
                rows,
                key=lambda row: (
                    -row.rank_score,
                    -((row.occurred_at or datetime(1970, 1, 1, tzinfo=UTC)).timestamp()),
                    row.event_id,
                ),
            )
        )

    @staticmethod
    def _filter_operation_rows(
        rows: tuple[EventRow, ...], filters: dict[str, object], window_end: datetime
    ) -> tuple[EventRow, ...]:
        status = filters.get("status")
        category = filters.get("category")
        display_tier = filters.get("display_tier")
        hours = filters.get("hours")
        since = None
        if isinstance(hours, int) and not isinstance(hours, bool) and hours > 0:
            since = window_end - timedelta(hours=hours)
        return tuple(
            row
            for row in rows
            if (not isinstance(status, str) or row.status == status)
            and (not isinstance(category, str) or row.category == category)
            and (not isinstance(display_tier, str) or row.display_tier == display_tier)
            and (since is None or (row.occurred_at is not None and row.occurred_at >= since))
        )

    def _event_row(
        self,
        event: EventRecord,
        version: EventVersionRecord,
        score: EventScoreRecord,
        *,
        display: _VersionDisplay | None = None,
        detail_href: str | None = None,
    ) -> EventRow:
        payload = version.payload if isinstance(version.payload, dict) else {}
        enrichment = payload.get("enrichment")
        enrichment = enrichment if isinstance(enrichment, dict) else {}
        breakdown = _score_breakdown(score)
        return EventRow(
            event_id=event.id,
            visibility="snapshot" if display is not None else event.visibility,
            status=display.status if display is not None else event.status,
            display_tier=display.display_tier if display is not None else event.display_tier,
            rank_score=float(score.heat) if display is not None else float(event.rank_score),
            category=display.category if display is not None else event.category,
            zh_title=_safe_display_text(version.zh_title, "未命名事件", max_length=500),
            zh_summary=_safe_display_text(version.zh_summary, "暂无摘要", max_length=2_000),
            why_it_matters=_safe_display_text(
                enrichment.get("why_it_matters"), "暂无关注理由", max_length=2_000
            ),
            occurred_at=display.occurred_at if display is not None else event.occurred_at,
            heat=float(score.heat),
            importance=_numeric_score(breakdown.get("importance")),
            credibility=_numeric_score(breakdown.get("credibility")),
            independent_root_count=_independent_root_count(payload.get("evidence")),
            enrichment_origin=str(enrichment.get("origin", "rule_fallback")),
            score_reasons=tuple(
                _safe_display_text(zh_label("event_reason", str(reason)), "未记录")
                for reason in _as_sequence(breakdown.get("reasons"))
            ),
            tier_reasons=tuple(
                _safe_display_text(zh_label("event_reason", str(reason)), "未记录")
                for reason in _as_sequence(
                    (payload.get("publication") or {}).get("reasons")
                    if isinstance(payload.get("publication"), dict)
                    else ()
                )
            ),
            detail_href=detail_href or f"/events/{event.id}",
        )

    @staticmethod
    def _home_snapshot_is_complete(
        snapshot: tuple[EventRecord, EventVersionRecord, EventScoreRecord],
    ) -> bool:
        _event, version, score = snapshot
        payload = version.payload if isinstance(version.payload, dict) else {}
        breakdown = _score_breakdown(score)
        evidence = payload.get("evidence")
        evidence_complete = isinstance(evidence, (list, tuple)) and bool(evidence) and all(
            isinstance(item, dict)
            and isinstance(item.get("raw_item_id"), int)
            and isinstance(item.get("role"), str)
            and bool(item.get("root_evidence_key"))
            and isinstance(item.get("independent"), bool)
            for item in evidence
        )
        return bool(
            version.zh_title
            and version.zh_summary
            and all(_is_finite_number(breakdown.get(key)) for key in SCORE_DIMENSION_KEYS)
            and isinstance(payload.get("enrichment"), dict)
            and evidence_complete
        )

def _numeric_score(value: object) -> float:
    return float(value) if _is_finite_number(value) else 0.0


def _banner(snapshot: OperationSnapshotRef) -> SnapshotBannerView:
    return SnapshotBannerView(
        operation_id=snapshot.operation_id,
        window_hours=snapshot.window_hours,
        window_end=snapshot.window_end,
        finished_at=snapshot.finished_at,
        algorithm_versions=tuple(sorted(snapshot.algorithm_versions.items())),
        skipped_newer_count=snapshot.skipped_newer_count,
    )


def _operation_detail_href(event_id: int, operation_id: int, version_number: int) -> str:
    return f"/events/{event_id}?operation={operation_id}&version={version_number}"


def _positive_limit(value: object, *, default: int) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else default
    )


def _version_display(version: EventVersionRecord) -> _VersionDisplay | None:
    payload = version.payload if isinstance(version.payload, dict) else None
    if payload is None:
        return None
    status = payload.get("status")
    category = payload.get("category")
    occurred_at = payload.get("occurred_at")
    publication = payload.get("publication")
    if isinstance(publication, dict) and "tier" in publication:
        display_tier = publication.get("tier")
    elif "display_tier" in payload:
        display_tier = payload.get("display_tier")
    else:
        # Event Intelligence v2.0 versions predate the publication block. The
        # reporting contract has always projected those immutable versions as
        # signals, so the web projection uses the same conservative default.
        display_tier = "signal"
    if status not in {"confirmed", "emerging", "developing", "disputed", "stale", "rejected"}:
        return None
    if category not in {
        "product_model",
        "research",
        "developer_tool",
        "company",
        "uncategorized",
    }:
        return None
    if display_tier not in {"hotspot", "signal", "audit_only"}:
        return None
    if not isinstance(occurred_at, str) or len(occurred_at) > 64:
        return None
    try:
        parsed_occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _VersionDisplay(
        status=status,
        category=None if category == "uncategorized" else category,
        display_tier=display_tier,
        occurred_at=(
            parsed_occurred_at.replace(tzinfo=UTC)
            if parsed_occurred_at.tzinfo is None
            else parsed_occurred_at.astimezone(UTC)
        ),
    )


def _is_finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and isfinite(float(value))
    )


def _score_breakdown(score: EventScoreRecord) -> dict[str, object]:
    return score.breakdown if isinstance(score.breakdown, dict) else {}


def _safe_ai_relevance_expression(dialect_name: str):  # type: ignore[no-untyped-def]
    value = EventScoreRecord.breakdown["ai_relevance"]
    if dialect_name == "postgresql":
        is_numeric = func.json_typeof(value) == "number"
    else:
        is_numeric = func.json_type(value).in_(("integer", "real"))
    return case((is_numeric, cast(value.as_string(), Float)), else_=None)


def _published_snapshot_statement() -> Select:
    return (
        select(EventRecord, EventVersionRecord, EventScoreRecord)
        .join(
            EventVersionRecord,
            and_(
                EventVersionRecord.event_id == EventRecord.id,
                EventVersionRecord.version_number == EventRecord.current_version_number,
            ),
        )
        .join(
            EventScoreRecord,
            and_(
                EventScoreRecord.event_id == EventRecord.id,
                EventScoreRecord.version_number == EventRecord.current_version_number,
            ),
        )
    )


def _as_sequence(value: object) -> tuple[object, ...]:
    return tuple(value) if isinstance(value, (list, tuple)) else ()


def _model_run_summaries(value: object) -> tuple[ModelRunSummary, ...]:
    summaries: list[ModelRunSummary] = []
    for item in _as_sequence(value)[:20]:
        if not isinstance(item, dict):
            continue
        model = item.get("model")
        purpose = item.get("purpose")
        outcome = item.get("outcome")
        latency = item.get("latency_ms")
        if not all(isinstance(field, str) and field.strip() for field in (model, purpose, outcome)):
            continue
        if latency is not None and (
            isinstance(latency, bool)
            or not isinstance(latency, (int, float))
            or not isfinite(float(latency))
            or latency < 0
        ):
            continue
        summaries.append(
            ModelRunSummary(
                model=_safe_display_text(model, "未记录模型", max_length=120),
                purpose=_safe_display_text(purpose, "unknown", max_length=64),
                outcome=_safe_display_text(outcome, "unknown", max_length=32),
                latency_ms=float(latency) if latency is not None else None,
            )
        )
    return tuple(summaries)


def _independent_root_count(evidence: object) -> int:
    roots: set[str] = set()
    for index, item in enumerate(_as_sequence(evidence)):
        if not isinstance(item, dict) or not item.get("independent"):
            continue
        root = item.get("root_evidence_key") or f"item:{item.get('raw_item_id', index)}"
        roots.add(str(root))
    return len(roots)


def _localized_limitations(values: object) -> tuple[str, ...]:
    localized = (
        _safe_display_text(zh_label("event_limitation", str(value)), "限制信息已隐藏")
        for value in _as_sequence(values)
    )
    return tuple(dict.fromkeys(value for value in localized if value))


def _score_dimension_reason(key: str, value: float) -> str:
    templates = {
        "ai_relevance": "规则对成员条目的 AI 相关性综合评分为 {value:g} 分。",
        "source_coverage": "按互相独立的证据根计算，来源覆盖为 {value:g} 分。",
        "source_authority": "按独立证据根去重后的来源权威性为 {value:g} 分。",
        "recency": "相对本次事件处理快照，时效得分为 {value:g} 分。",
        "engagement_velocity": "按可用且有上限的互动信号计算为 {value:g} 分。",
        "novelty": "相对近 30 天同类事件，新颖性为 {value:g} 分。",
    }
    return templates[key].format(value=value)


def _safe_display_text(value: object, fallback: str, *, max_length: int = 1_000) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        return fallback
    text = _URL_WITH_QUERY.sub(r"\1", text)
    text = _FORBIDDEN_SENSITIVE_KEY.sub("敏感信息已隐藏", text)
    text = _ASSIGNED_SECRET.sub("敏感信息已隐藏", text)
    return text[:max_length]


def _safe_external_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
