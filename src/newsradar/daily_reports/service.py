from __future__ import annotations

import re
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
    DailyReportOverviewItemDraft,
    ReportSection,
    validate_window_hours,
)
from newsradar.db.models import (
    DailyReportRecord,
    EventVersionRecord,
    OperationRunRecord,
)
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


_BROWSER_NUMERIC_HOST_PART = re.compile(r"(?:[0-9]+|0[xX][0-9a-fA-F]+)\Z")
_LEGACY_REVISION_OVERVIEW_DIAGNOSTIC_ZH = (
    "历史操作快照缺失，本修订版沿用归档版固定条目；"
    "系统没有重新抓取或混入当前事件。"
)


def _browser_numeric_ipv4_host(hostname: str) -> bool:
    parts = hostname.split(".")
    return 1 <= len(parts) <= 4 and all(
        part and _BROWSER_NUMERIC_HOST_PART.fullmatch(part) for part in parts
    )


def _public_url(value: str | None) -> str | None:
    if not value or "\\" in value or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
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
    if (
        "%" in hostname
        or normalized_hostname == "localhost"
        or normalized_hostname.endswith(".localhost")
    ):
        return None
    try:
        address = ip_address(normalized_hostname)
    except ValueError:
        address = None
    if address is not None and (not address.is_global or address.is_multicast):
        return None
    if address is None and _browser_numeric_ipv4_host(normalized_hostname):
        return None
    rendered_hostname = normalized_hostname
    if address is not None and address.version == 6:
        rendered_hostname = f"[{normalized_hostname}]"
    normalized_netloc = (
        f"{rendered_hostname}:{port}" if port is not None else rendered_hostname
    )
    return urlunsplit((parsed.scheme, normalized_netloc, parsed.path, "", ""))


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


def _degraded_item_snapshot(
    row: EventRow,
    section: ReportSection,
    reason: str,
) -> dict[str, object]:
    return {
        "zh_title": row.zh_title,
        "zh_summary": "该事件的日报展示数据不完整，已保留为待补齐条目。",
        "why_it_matters": row.why_it_matters,
        "status": row.status,
        "unconfirmed": section is ReportSection.EMERGING,
        "display_tier": row.display_tier,
        "category": row.category,
        "rank_score": row.rank_score,
        "occurred_at": _snapshot_datetime(row.occurred_at),
        "independent_root_count": row.independent_root_count,
        "confirmation_summary": row.confirmation_summary,
        "enrichment_origin": row.enrichment_origin,
        "limitations": ["日报展示数据待补齐"],
        "evidence": [],
        "display_degradation_reason": reason,
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
        return self._generate(window_hours, now=now, operation_id=None)

    def generate_from_operation(
        self,
        operation_id: int,
        window_hours: int,
        *,
        now: datetime | None = None,
    ) -> DailyReportRecord:
        """Generate from one exact child operation without a latest-snapshot fallback."""
        return self._generate(window_hours, now=now, operation_id=operation_id)

    def _generate(
        self,
        window_hours: int,
        *,
        now: datetime | None,
        operation_id: int | None,
    ) -> DailyReportRecord:
        checked_at = now or self._utcnow()
        window_hours = validate_window_hours(window_hours)
        if operation_id is None:
            page = self._events.latest_operation_page(
                {"hours": window_hours, "limit": 1000},
                now=checked_at,
            )
        else:
            page = self._events.operation_page(
                operation_id,
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
        if snapshot is None or (
            operation_id is not None and snapshot.window_hours != window_hours
        ):
            raise ValueError("complete_event_snapshot_required")

        snapshot_event_ids = tuple(ref.event_id for ref in snapshot.event_versions)
        if len(snapshot_event_ids) != len(set(snapshot_event_ids)):
            raise ValueError("ambiguous_event_snapshot_versions")
        skipped_missing_time = _snapshot_missing_time_count(self.session, snapshot)
        version_by_event = {
            ref.event_id: ref.version_number for ref in snapshot.event_versions
        }
        overview_drafts, skipped_invalid_overview = self._overview_drafts(
            snapshot,
            checked_at=checked_at,
        )
        overview_by_event = {item.event_id: item for item in overview_drafts}
        drafts: list[DailyReportItemDraft] = []
        decision_event_ids: set[int] = set()
        skipped_invalid = 0
        for section in (ReportSection.CONFIRMED, ReportSection.EMERGING):
            section_position = 0
            for row in _selected_rows(page.events, section):
                if section_position >= MAX_ITEMS_PER_SECTION:
                    break
                version_number = version_by_event.get(row.event_id)
                overview_item = overview_by_event.get(row.event_id)
                if (
                    overview_item is None
                    or version_number is None
                    or "display_degradation_reason" in overview_item.snapshot
                ):
                    skipped_invalid += 1
                    continue
                section_position += 1
                decision_event_ids.add(row.event_id)
                drafts.append(
                    DailyReportItemDraft(
                        event_id=row.event_id,
                        event_version_number=version_number,
                        section=section,
                        position=section_position,
                        snapshot=dict(overview_item.snapshot),
                    )
                )

        overview_drafts = tuple(
            DailyReportOverviewItemDraft(
                event_id=item.event_id,
                event_version_number=item.event_version_number,
                position=item.position,
                snapshot=item.snapshot,
                decision_event_id=(item.event_id if item.event_id in decision_event_ids else None),
            )
            for item in overview_drafts
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
                    "skipped_invalid_overview_event": skipped_invalid_overview,
                    "skipped_missing_time": skipped_missing_time,
                    "overview_count": len(overview_drafts),
                    "minimax_degraded": any(
                        item.snapshot["enrichment_origin"] != "model" for item in drafts
                    ),
                },
                items=tuple(drafts),
                overview_items=overview_drafts,
            )
        )

    def revise(self, report_id: int) -> DailyReportRecord:
        original = self._reports.revision_target(report_id)
        if original.status == "draft":
            return original
        operation = self.session.get(OperationRunRecord, original.source_operation_id)
        if operation is None or not isinstance(operation.result_summary, dict):
            raise ValueError("complete_event_snapshot_required")
        generation_summary = {
            **original.generation_summary,
            "revision_overview_source": "archived_report_snapshot",
            "revision_overview_diagnostic_zh": (
                _LEGACY_REVISION_OVERVIEW_DIAGNOSTIC_ZH
            ),
        }
        if "event_version_snapshots" not in operation.result_summary:
            return self._reports.revise(
                report_id,
                generation_summary=generation_summary,
                expected_source_report_id=original.id,
            )
        snapshot = event_snapshot_by_id(
            self.session,
            original.source_operation_id,
            now=original.generated_at,
        )
        if snapshot is None:
            raise ValueError("complete_event_snapshot_required")
        generation_summary["revision_overview_source"] = "event_snapshot"
        generation_summary.pop("revision_overview_diagnostic_zh", None)
        materialized, _skipped = self._overview_drafts(
            snapshot,
            checked_at=original.generated_at,
        )
        decision_event_ids = {row.event_id for row in self._reports.items(original.id)}
        rebuilt_overview_items = tuple(
            DailyReportOverviewItemDraft(
                event_id=item.event_id,
                event_version_number=item.event_version_number,
                position=item.position,
                snapshot=item.snapshot,
                decision_event_id=(
                    item.event_id if item.event_id in decision_event_ids else None
                ),
            )
            for item in materialized
        )
        return self._reports.revise(
            report_id,
            rebuilt_overview_items=rebuilt_overview_items,
            generation_summary=generation_summary,
            expected_source_report_id=original.id,
        )

    def _overview_drafts(
        self,
        snapshot: OperationSnapshotRef,
        *,
        checked_at: datetime,
    ) -> tuple[tuple[DailyReportOverviewItemDraft, ...], int]:
        drafts: list[DailyReportOverviewItemDraft] = []
        skipped_invalid = 0
        version_by_event = {
            ref.event_id: ref.version_number for ref in snapshot.event_versions
        }
        for row in self._events._operation_rows(snapshot):
            if row.status != "confirmed" and row.display_tier not in {"hotspot", "signal"}:
                continue
            version_number = version_by_event[row.event_id]
            try:
                detail = self._events.get_operation_event(
                    row.event_id,
                    snapshot.operation_id,
                    version_number,
                    now=checked_at,
                )
            except ValueError:
                detail = None
            if detail is None:
                skipped_invalid += 1
                drafts.append(
                    DailyReportOverviewItemDraft(
                        event_id=row.event_id,
                        event_version_number=version_number,
                        position=len(drafts) + 1,
                        snapshot=_degraded_item_snapshot(
                            row,
                            (
                                ReportSection.CONFIRMED
                                if row.status == "confirmed"
                                else ReportSection.EMERGING
                            ),
                            "event_detail_unavailable",
                        ),
                    )
                )
                continue
            section = (
                ReportSection.CONFIRMED
                if row.status == "confirmed"
                else ReportSection.EMERGING
            )
            try:
                item_snapshot = _item_snapshot(detail, section)
            except _InvalidEventSnapshot:
                skipped_invalid += 1
                drafts.append(
                    DailyReportOverviewItemDraft(
                        event_id=row.event_id,
                        event_version_number=version_number,
                        position=len(drafts) + 1,
                        snapshot=_degraded_item_snapshot(
                            row, section, "invalid_snapshot_data"
                        ),
                    )
                )
                continue
            drafts.append(
                DailyReportOverviewItemDraft(
                    event_id=row.event_id,
                    event_version_number=version_number,
                    position=len(drafts) + 1,
                    snapshot=item_snapshot,
                )
            )
        return tuple(drafts), skipped_invalid
