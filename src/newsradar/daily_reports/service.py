from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.schema import (
    MAX_ITEMS_PER_SECTION,
    REPORT_TIMEZONE,
    DailyReportDraft,
    DailyReportItemDraft,
    ReportSection,
    validate_window_hours,
)
from newsradar.db.models import DailyReportRecord, EventVersionRecord
from newsradar.events.operation_snapshots import (
    OperationSnapshotRef,
    event_snapshot_by_id,
)
from newsradar.web.event_queries import (
    EventDetailView,
    EventQueryService,
    EventRow,
)


class _InvalidEventSnapshot(ValueError):
    pass


def _public_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    normalized_hostname = hostname.rstrip(".").lower()
    if normalized_hostname == "localhost" or normalized_hostname.endswith(".localhost"):
        return None
    try:
        address = ip_address(normalized_hostname)
    except ValueError:
        address = None
    if address is not None and any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_reserved,
            address.is_unspecified,
            address.is_multicast,
        )
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _snapshot_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise _InvalidEventSnapshot("invalid_snapshot_datetime")
    return value.isoformat()


def _snapshot_limitations(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise _InvalidEventSnapshot("invalid_snapshot_limitations")
    return list(value)


def _selected_rows(
    rows: tuple[EventRow, ...],
    section: ReportSection,
) -> tuple[EventRow, ...]:
    return tuple(
        row
        for row in rows
        if row.status == section.value
        and (
            section is ReportSection.CONFIRMED
            or row.display_tier in {"hotspot", "signal"}
        )
    )


def _snapshot_missing_time_count(
    session: Session,
    snapshot: OperationSnapshotRef,
) -> int:
    refs = {(ref.event_id, ref.version_number) for ref in snapshot.event_versions}
    if not refs:
        return 0
    versions = session.scalars(
        select(EventVersionRecord).where(
            EventVersionRecord.event_id.in_({event_id for event_id, _ in refs})
        )
    )
    missing = 0
    for version in versions:
        if (version.event_id, version.version_number) not in refs:
            continue
        payload = version.payload if isinstance(version.payload, dict) else {}
        raw = payload.get("occurred_at")
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            missing += 1
            continue
        if parsed.tzinfo is None:
            missing += 1
    return missing


def _item_snapshot(
    detail: EventDetailView,
    section: ReportSection,
) -> dict[str, object]:
    if not isinstance(detail.evidence, (list, tuple)):
        raise _InvalidEventSnapshot("invalid_snapshot_evidence")
    return {
        "zh_title": detail.event.zh_title,
        "zh_summary": detail.event.zh_summary,
        "why_it_matters": detail.why_it_matters,
        "status": detail.event.status,
        "unconfirmed": section is ReportSection.EMERGING,
        "display_tier": detail.event.display_tier,
        "category": detail.event.category,
        "rank_score": detail.event.rank_score,
        "occurred_at": _snapshot_datetime(detail.event.occurred_at),
        "independent_root_count": detail.event.independent_root_count,
        "confirmation_summary": detail.event.confirmation_summary,
        "enrichment_origin": detail.event.enrichment_origin,
        "limitations": _snapshot_limitations(detail.limitations),
        "evidence": [
            {
                "title": item.title,
                "url": _public_url(item.original_url),
                "published_at": _snapshot_datetime(item.published_at),
                "role": item.role,
                "independent": item.independent,
                "limitations": _snapshot_limitations(item.limitations),
            }
            for item in detail.evidence
        ],
    }


class DailyReportService:
    def __init__(
        self,
        session: Session,
        *,
        utcnow: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._events = EventQueryService(session)
        self._reports = DailyReportRepository(session, utcnow=self._utcnow)

    def generate(
        self,
        window_hours: int,
        *,
        now: datetime | None = None,
    ) -> DailyReportRecord:
        checked_at = now or self._utcnow()
        window_hours = validate_window_hours(window_hours)
        page = self._events.latest_operation_page(
            {"hours": window_hours, "limit": 1000},
            now=checked_at,
        )
        if page is None:
            raise ValueError("complete_event_snapshot_required")
        snapshot = event_snapshot_by_id(
            self.session,
            page.snapshot.operation_id,
            now=checked_at,
        )
        if snapshot is None:
            raise ValueError("complete_event_snapshot_required")

        snapshot_event_ids = tuple(ref.event_id for ref in snapshot.event_versions)
        if len(snapshot_event_ids) != len(set(snapshot_event_ids)):
            raise ValueError("ambiguous_event_snapshot_versions")
        skipped_missing_time = _snapshot_missing_time_count(self.session, snapshot)
        version_by_event = {
            ref.event_id: ref.version_number for ref in snapshot.event_versions
        }
        drafts: list[DailyReportItemDraft] = []
        skipped_invalid = 0
        for section in (ReportSection.CONFIRMED, ReportSection.EMERGING):
            section_position = 0
            for row in _selected_rows(page.events, section):
                if section_position >= MAX_ITEMS_PER_SECTION:
                    break
                version_number = version_by_event.get(row.event_id)
                try:
                    detail = (
                        self._events.get_operation_event(
                            row.event_id,
                            page.snapshot.operation_id,
                            version_number,
                            now=checked_at,
                        )
                        if version_number is not None
                        else None
                    )
                except ValueError:
                    skipped_invalid += 1
                    continue
                if detail is None:
                    skipped_invalid += 1
                    continue
                try:
                    item_snapshot = _item_snapshot(detail, section)
                except _InvalidEventSnapshot:
                    skipped_invalid += 1
                    continue
                section_position += 1
                drafts.append(
                    DailyReportItemDraft(
                        event_id=row.event_id,
                        event_version_number=version_number,
                        section=section,
                        position=section_position,
                        snapshot=item_snapshot,
                    )
                )

        window_end = page.snapshot.window_end
        report_date = window_end.astimezone(ZoneInfo(REPORT_TIMEZONE)).date()
        return self._reports.create_draft(
            DailyReportDraft(
                report_date=report_date,
                window_hours=window_hours,
                window_start=window_end - timedelta(hours=window_hours),
                window_end=window_end,
                source_operation_id=page.snapshot.operation_id,
                generation_summary={
                    "confirmed_count": sum(
                        item.section is ReportSection.CONFIRMED for item in drafts
                    ),
                    "emerging_count": sum(
                        item.section is ReportSection.EMERGING for item in drafts
                    ),
                    "skipped_invalid_event": skipped_invalid,
                    "skipped_missing_time": skipped_missing_time,
                    "minimax_degraded": any(
                        item.snapshot["enrichment_origin"] != "model" for item in drafts
                    ),
                },
                items=tuple(drafts),
            )
        )

    def revise(self, report_id: int) -> DailyReportRecord:
        return self._reports.revise(report_id)
