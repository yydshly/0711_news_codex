from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.db.models import (
    DuplicateCandidateRecord,
    FetchRunItemRecord,
    RawItemRecord,
    RawItemSnapshotRecord,
)
from newsradar.ingestion.normalization import (
    content_hash,
    normalize_title,
    normalize_url,
    title_similarity,
)
from newsradar.ingestion.schema import NormalizedRawItem


class ItemAction(StrEnum):
    INSERTED = "inserted"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class ItemWriteResult:
    raw_item_id: int | None
    action: ItemAction
    error_code: str | None = None


class RawItemRepository:
    """Persist normalized observations without automatically merging identities."""

    def __init__(self, session: Session):
        self.session = session

    def upsert(self, fetch_run_id: int, source_id: str, item: NormalizedRawItem) -> ItemWriteResult:
        canonical_url = normalize_url(str(item.canonical_url))
        canonical_url_hash = _hash(canonical_url)
        external_match = self.session.scalar(
            select(RawItemRecord).where(
                RawItemRecord.source_id == source_id, RawItemRecord.external_id == item.external_id
            )
        )
        canonical_match = self.session.scalar(
            select(RawItemRecord).where(
                RawItemRecord.source_id == source_id,
                RawItemRecord.canonical_url_hash == canonical_url_hash,
            )
        )

        if (
            external_match is not None
            and canonical_match is not None
            and external_match.id != canonical_match.id
        ):
            return self._write_audit(
                fetch_run_id, item.external_id, None, ItemAction.SKIPPED, "identity_conflict"
            )

        current = external_match or canonical_match
        if current is None:
            try:
                with self.session.begin_nested():
                    current = self._new_record(
                        fetch_run_id, source_id, item, canonical_url, canonical_url_hash
                    )
                    self.session.add(current)
                    self.session.flush()
                    self._add_snapshot(current, fetch_run_id, item)
                    self._add_candidates(current, item)
                    self._add_audit(fetch_run_id, item.external_id, current.id, ItemAction.INSERTED)
                return ItemWriteResult(current.id, ItemAction.INSERTED)
            except IntegrityError:
                # The unique (source_id, external_id) index is the final guard when
                # another worker inserted the same external identity concurrently.
                current = self.session.scalar(
                    select(RawItemRecord).where(
                        RawItemRecord.source_id == source_id,
                        RawItemRecord.external_id == item.external_id,
                    )
                )
                if current is None:
                    return self._write_audit(
                        fetch_run_id, item.external_id, None, ItemAction.FAILED, "write_conflict"
                    )

        assert current is not None
        return self._observe(fetch_run_id, source_id, item, current)

    def record_failure(
        self, fetch_run_id: int, source_id: str, item: NormalizedRawItem, error_code: str
    ) -> ItemWriteResult:
        del source_id
        return self._write_audit(
            fetch_run_id, item.external_id, None, ItemAction.FAILED, error_code
        )

    def _observe(
        self, fetch_run_id: int, source_id: str, item: NormalizedRawItem, current: RawItemRecord
    ) -> ItemWriteResult:
        next_hash = content_hash(item)
        action = ItemAction.UPDATED if current.content_hash != next_hash else ItemAction.UNCHANGED
        with self.session.begin_nested():
            if action is ItemAction.UPDATED:
                self._apply_item(current, item)
                current.content_hash = next_hash
                current.canonical_url = normalize_url(str(item.canonical_url))
                current.canonical_url_hash = _hash(current.canonical_url)
                current.title_fingerprint = _title_fingerprint(item.title)
                self._add_snapshot(current, fetch_run_id, item)
                self.session.flush()
                self._add_candidates(current, item)
            else:
                current.engagement = dict(item.engagement)
                current.raw_payload = item.raw_payload
            current.last_seen_run_id = fetch_run_id
            current.last_seen_at = _now()
            current.fetched_at = _now()
            self.session.flush()
            self._add_audit(fetch_run_id, item.external_id, current.id, action)
        return ItemWriteResult(current.id, action)

    def _new_record(
        self,
        fetch_run_id: int,
        source_id: str,
        item: NormalizedRawItem,
        canonical_url: str,
        canonical_url_hash: str,
    ) -> RawItemRecord:
        now = _now()
        record = RawItemRecord(
            source_id=source_id,
            external_id=item.external_id,
            canonical_url=canonical_url,
            payload=item.model_dump(mode="json"),
            canonical_url_hash=canonical_url_hash,
            title_fingerprint=_title_fingerprint(item.title),
            content_hash=content_hash(item),
            first_seen_run_id=fetch_run_id,
            last_seen_run_id=fetch_run_id,
            first_seen_at=now,
            last_seen_at=now,
            fetched_at=now,
        )
        self._apply_item(record, item)
        return record

    def _apply_item(self, record: RawItemRecord, item: NormalizedRawItem) -> None:
        record.original_url = str(item.original_url) if item.original_url else None
        record.title = normalize_title(item.title)
        record.authors = list(item.authors)
        record.summary = item.summary
        record.content = item.content
        record.language = item.language
        record.content_type = item.content_type
        record.published_at = item.published_at
        record.source_updated_at = item.source_updated_at
        record.discussion_url = str(item.discussion_url) if item.discussion_url else None
        record.engagement = dict(item.engagement)
        record.raw_payload = item.raw_payload
        record.payload = item.model_dump(mode="json")

    def _add_snapshot(
        self, record: RawItemRecord, fetch_run_id: int, item: NormalizedRawItem
    ) -> None:
        snapshot_hash = content_hash(item)
        existing = self.session.scalar(
            select(RawItemSnapshotRecord).where(
                RawItemSnapshotRecord.raw_item_id == record.id,
                RawItemSnapshotRecord.content_hash == snapshot_hash,
            )
        )
        if existing is None:
            self.session.add(
                RawItemSnapshotRecord(
                    raw_item_id=record.id,
                    fetch_run_id=fetch_run_id,
                    content_hash=snapshot_hash,
                    snapshot=item.model_dump(mode="json"),
                )
            )

    def _add_candidates(self, record: RawItemRecord, item: NormalizedRawItem) -> None:
        canonical_matches = self.session.scalars(
            select(RawItemRecord).where(
                RawItemRecord.canonical_url_hash == record.canonical_url_hash,
                RawItemRecord.id != record.id,
                RawItemRecord.source_id != record.source_id,
            )
        ).all()
        for candidate in canonical_matches:
            self._add_candidate(record.id, candidate.id, "canonical_url", 1.0)

        title_matches = self.session.scalars(
            select(RawItemRecord).where(
                RawItemRecord.id != record.id,
                RawItemRecord.source_id != record.source_id,
            )
        ).all()
        for candidate in title_matches:
            candidate_item = NormalizedRawItem(
                external_id=candidate.external_id,
                title=candidate.title or "",
                canonical_url=candidate.canonical_url,
                authors=tuple(candidate.authors or []),
                summary=candidate.summary,
                content=candidate.content,
                language=candidate.language,
                content_type=candidate.content_type or "article",
                published_at=_as_utc(candidate.published_at),
                source_updated_at=_as_utc(candidate.source_updated_at),
                engagement=candidate.engagement or {},
                raw_payload=candidate.raw_payload or {},
            )
            score = title_similarity(item, candidate_item)
            if score >= 0.9:
                self._add_candidate(record.id, candidate.id, "title", score)

    def _add_candidate(
        self, raw_item_id: int, candidate_id: int, match_type: str, score: float
    ) -> None:
        left, right = sorted((raw_item_id, candidate_id))
        exists = self.session.scalar(
            select(DuplicateCandidateRecord).where(
                DuplicateCandidateRecord.raw_item_id == left,
                DuplicateCandidateRecord.candidate_raw_item_id == right,
                DuplicateCandidateRecord.match_type == match_type,
            )
        )
        if exists is None:
            self.session.add(
                DuplicateCandidateRecord(
                    raw_item_id=left,
                    candidate_raw_item_id=right,
                    match_type=match_type,
                    score=score,
                )
            )

    def _write_audit(
        self,
        fetch_run_id: int,
        external_id: str,
        raw_item_id: int | None,
        action: ItemAction,
        error_code: str | None = None,
    ) -> ItemWriteResult:
        with self.session.begin_nested():
            self._add_audit(fetch_run_id, external_id, raw_item_id, action, error_code)
        return ItemWriteResult(raw_item_id, action, error_code)

    def _add_audit(
        self,
        fetch_run_id: int,
        external_id: str,
        raw_item_id: int | None,
        action: ItemAction,
        error_code: str | None = None,
    ) -> None:
        self.session.add(
            FetchRunItemRecord(
                fetch_run_id=fetch_run_id,
                raw_item_id=raw_item_id,
                external_id=external_id,
                action=action.value,
                error_code=error_code,
            )
        )
        self.session.flush()


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _title_fingerprint(title: str) -> str:
    return _hash(normalize_title(title).lower())


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
