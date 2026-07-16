from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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


def _public_url(value: str | None) -> str | None:
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
    return {
        "zh_title": detail.event.zh_title,
        "zh_summary": detail.event.zh_summary,
        "why_it_matters": detail.why_it_matters,
        "status": detail.event.status,
        "unconfirmed": section is ReportSection.EMERGING,
        "display_tier": detail.event.display_tier,
        "category": detail.event.category,
        "rank_score": detail.event.rank_score,
        "occurred_at": (
            detail.event.occurred_at.isoformat() if detail.event.occurred_at else None
        ),
        "independent_root_count": detail.event.independent_root_count,
        "confirmation_summary": detail.event.confirmation_summary,
        "enrichment_origin": detail.event.enrichment_origin,
        "limitations": list(detail.limitations),
        "evidence": [
            {
                "title": item.title,
                "url": _public_url(item.original_url),
                "published_at": (
                    item.published_at.isoformat() if item.published_at else None
                ),
                "role": item.role,
                "independent": item.independent,
                "limitations": list(item.limitations),
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
                if detail is None:
                    skipped_invalid += 1
                    continue
                section_position += 1
                drafts.append(
                    DailyReportItemDraft(
                        event_id=row.event_id,
                        event_version_number=version_number,
                        section=section,
                        position=section_position,
                        snapshot=_item_snapshot(detail, section),
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
