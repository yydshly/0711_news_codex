from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from newsradar.db.models import (
    DuplicateCandidateRecord,
    FetchRunRecord,
    RawItemRecord,
    RawItemSnapshotRecord,
    SourceDefinitionRecord,
)


@dataclass(frozen=True, slots=True)
class RawItemListRow:
    raw_item_id: int
    title: str
    source_id: str
    source_name: str
    provider_id: str
    language: str | None
    published_at: datetime | None
    first_seen_at: datetime | None
    duplicate_count: int
    evidence_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ItemPage:
    rows: tuple[RawItemListRow, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class FetchRunRow:
    fetch_run_id: int
    source_id: str
    source_name: str
    started_at: datetime
    finished_at: datetime | None
    outcome: str
    item_count: int
    items_received: int | None
    items_inserted: int | None
    items_updated: int | None
    items_unchanged: int | None
    items_failed: int | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class RawItemVersionRow:
    snapshot_id: int
    content_hash: str
    fetch_run_id: int | None
    created_at: datetime
    snapshot: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class RawItemDetail:
    raw_item_id: int
    source_id: str
    source_name: str
    provider_id: str
    title: str
    canonical_url: str
    original_url: str | None
    discovery_url: str | None
    published_at: datetime | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    authors: tuple[str, ...]
    summary: str | None
    content: str | None
    language: str | None
    content_type: str | None
    source_updated_at: datetime | None
    discussion_url: str | None
    engagement: Mapping[str, object]
    item_kind: str | None
    publisher_name: str | None
    publisher_url: str | None
    origin_resolution_status: str | None
    payload: Mapping[str, object]
    versions: tuple[RawItemVersionRow, ...]


@dataclass(frozen=True, slots=True)
class DuplicateCandidateRow:
    duplicate_id: int
    left_item_id: int
    left_title: str
    right_item_id: int
    right_title: str
    match_type: str
    score: float
    status: str
    detected_at: datetime
    reviewed_at: datetime | None


class ItemQueryService:
    """Read-only, database-projected views for ingestion content pages."""

    def __init__(self, session: Session):
        self.session = session

    def list_items(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        source_id: str | None = None,
        provider_id: str | None = None,
        language: str | None = None,
        title_query: str | None = None,
        published_after: datetime | None = None,
        published_before: datetime | None = None,
        first_seen_after: datetime | None = None,
        first_seen_before: datetime | None = None,
    ) -> ItemPage:
        limit, offset = _pagination(limit, offset)
        filters = _item_filters(
            source_id=source_id,
            provider_id=provider_id,
            language=language,
            title_query=title_query,
            published_after=published_after,
            published_before=published_before,
            first_seen_after=first_seen_after,
            first_seen_before=first_seen_before,
        )
        duplicate_count = (
            select(func.count(DuplicateCandidateRecord.id))
            .where(
                or_(
                    DuplicateCandidateRecord.raw_item_id == RawItemRecord.id,
                    DuplicateCandidateRecord.candidate_raw_item_id == RawItemRecord.id,
                )
            )
            .correlate(RawItemRecord)
            .scalar_subquery()
        )
        projection = (
            select(
                RawItemRecord.id,
                RawItemRecord.title,
                RawItemRecord.source_id,
                SourceDefinitionRecord.name,
                SourceDefinitionRecord.provider_id,
                RawItemRecord.language,
                RawItemRecord.published_at,
                RawItemRecord.first_seen_at,
                duplicate_count.label("duplicate_count"),
                SourceDefinitionRecord.roles,
            )
            .join(SourceDefinitionRecord, SourceDefinitionRecord.id == RawItemRecord.source_id)
            .where(*filters)
        )
        total = self.session.scalar(
            select(func.count())
            .select_from(RawItemRecord)
            .join(SourceDefinitionRecord, SourceDefinitionRecord.id == RawItemRecord.source_id)
            .where(*filters)
        ) or 0
        records = self.session.execute(
            projection.order_by(
                RawItemRecord.published_at.desc().nullslast(),
                RawItemRecord.first_seen_at.desc(),
                RawItemRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return ItemPage(
            rows=tuple(
                RawItemListRow(
                    raw_item_id=record.id,
                    title=record.title or "（无标题）",
                    source_id=record.source_id,
                    source_name=record.name,
                    provider_id=record.provider_id,
                    language=record.language,
                    published_at=record.published_at,
                    first_seen_at=record.first_seen_at,
                    duplicate_count=record.duplicate_count,
                    evidence_roles=tuple(record.roles or ()),
                )
                for record in records
            ),
            total=total,
            limit=limit,
            offset=offset,
        )

    def list_fetch_runs(
        self, *, source_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[FetchRunRow, ...]:
        limit, offset = _pagination(limit, offset)
        statement = select(
            FetchRunRecord,
            SourceDefinitionRecord.name.label("source_name"),
        ).join(SourceDefinitionRecord, SourceDefinitionRecord.id == FetchRunRecord.source_id)
        if source_id:
            statement = statement.where(FetchRunRecord.source_id == source_id)
        records = self.session.execute(
            statement.order_by(FetchRunRecord.started_at.desc(), FetchRunRecord.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return tuple(
            FetchRunRow(
                fetch_run_id=record.FetchRunRecord.id,
                source_id=record.FetchRunRecord.source_id,
                source_name=record.source_name,
                started_at=record.FetchRunRecord.started_at,
                finished_at=record.FetchRunRecord.finished_at,
                outcome=record.FetchRunRecord.outcome,
                item_count=record.FetchRunRecord.item_count,
                items_received=record.FetchRunRecord.items_received,
                items_inserted=record.FetchRunRecord.items_inserted,
                items_updated=record.FetchRunRecord.items_updated,
                items_unchanged=record.FetchRunRecord.items_unchanged,
                items_failed=record.FetchRunRecord.items_failed,
                error_code=record.FetchRunRecord.error_code,
                error_message=record.FetchRunRecord.error_message,
            )
            for record in records
        )

    def get_item(self, raw_item_id: int) -> RawItemDetail | None:
        record = self.session.execute(
            select(RawItemRecord, SourceDefinitionRecord.name, SourceDefinitionRecord.provider_id)
            .join(SourceDefinitionRecord, SourceDefinitionRecord.id == RawItemRecord.source_id)
            .where(RawItemRecord.id == raw_item_id)
        ).one_or_none()
        if record is None:
            return None
        versions = self.session.scalars(
            select(RawItemSnapshotRecord)
            .where(RawItemSnapshotRecord.raw_item_id == raw_item_id)
            .order_by(RawItemSnapshotRecord.created_at.desc(), RawItemSnapshotRecord.id.desc())
        ).all()
        item = record.RawItemRecord
        return RawItemDetail(
            raw_item_id=item.id,
            source_id=item.source_id,
            source_name=record.name,
            provider_id=record.provider_id,
            title=item.title or "（无标题）",
            canonical_url=item.canonical_url,
            original_url=item.original_url,
            discovery_url=item.discovery_url,
            published_at=item.published_at,
            first_seen_at=item.first_seen_at,
            last_seen_at=item.last_seen_at,
            authors=tuple(item.authors or ()),
            summary=item.summary,
            content=item.content,
            language=item.language,
            content_type=item.content_type,
            source_updated_at=item.source_updated_at,
            discussion_url=item.discussion_url,
            engagement=_freeze_mapping(item.engagement or {}),
            item_kind=item.item_kind,
            publisher_name=item.publisher_name,
            publisher_url=item.publisher_url,
            origin_resolution_status=item.origin_resolution_status,
            payload=_freeze_mapping(item.payload),
            versions=tuple(
                RawItemVersionRow(
                    snapshot_id=version.id,
                    content_hash=version.content_hash,
                    fetch_run_id=version.fetch_run_id,
                    created_at=version.created_at,
                    snapshot=_freeze_mapping(version.snapshot),
                )
                for version in versions
            ),
        )

    def list_duplicate_candidates(
        self, *, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[DuplicateCandidateRow, ...]:
        limit, offset = _pagination(limit, offset)
        left = aliased(RawItemRecord)
        right = aliased(RawItemRecord)
        statement = (
            select(
                DuplicateCandidateRecord,
                left.title.label("left_title"),
                right.title.label("right_title"),
            )
            .join(left, left.id == DuplicateCandidateRecord.raw_item_id)
            .join(right, right.id == DuplicateCandidateRecord.candidate_raw_item_id)
        )
        if status:
            statement = statement.where(DuplicateCandidateRecord.status == status)
        records = self.session.execute(
            statement.order_by(
                DuplicateCandidateRecord.detected_at.desc(),
                DuplicateCandidateRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return tuple(
            DuplicateCandidateRow(
                duplicate_id=record.DuplicateCandidateRecord.id,
                left_item_id=record.DuplicateCandidateRecord.raw_item_id,
                left_title=record.left_title or "（无标题）",
                right_item_id=record.DuplicateCandidateRecord.candidate_raw_item_id,
                right_title=record.right_title or "（无标题）",
                match_type=record.DuplicateCandidateRecord.match_type,
                score=record.DuplicateCandidateRecord.score,
                status=record.DuplicateCandidateRecord.status,
                detected_at=record.DuplicateCandidateRecord.detected_at,
                reviewed_at=record.DuplicateCandidateRecord.reviewed_at,
            )
            for record in records
        )

    def review_duplicate(
        self, duplicate_id: int, status: Literal["confirmed", "dismissed"]
    ) -> bool:
        record = self.session.get(DuplicateCandidateRecord, duplicate_id, with_for_update=True)
        if record is None or record.status != "pending":
            return False
        record.status = status
        record.reviewed_at = datetime.now(UTC)
        self.session.commit()
        return True


def _item_filters(
    *,
    source_id: str | None,
    provider_id: str | None,
    language: str | None,
    title_query: str | None,
    published_after: datetime | None,
    published_before: datetime | None,
    first_seen_after: datetime | None,
    first_seen_before: datetime | None,
) -> tuple[object, ...]:
    filters: list[object] = []
    if source_id:
        filters.append(RawItemRecord.source_id == source_id)
    if provider_id:
        filters.append(SourceDefinitionRecord.provider_id == provider_id)
    if language:
        filters.append(RawItemRecord.language == language)
    if title_query:
        filters.append(RawItemRecord.title.ilike(f"%{title_query.strip()}%"))
    if published_after:
        filters.append(RawItemRecord.published_at >= published_after)
    if published_before:
        filters.append(RawItemRecord.published_at <= published_before)
    if first_seen_after:
        filters.append(RawItemRecord.first_seen_at >= first_seen_after)
    if first_seen_before:
        filters.append(RawItemRecord.first_seen_at <= first_seen_before)
    return tuple(filters)


def _pagination(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    return limit, offset


def _freeze_mapping(value: dict | None) -> Mapping[str, object]:
    return MappingProxyType(dict(value or {}))
