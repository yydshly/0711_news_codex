"""Bounded, normalized facts used only for event-merge candidate generation."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    EventCandidateRecord,
    EventItemRecord,
    EventRecord,
    EventVersionRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.event_merges.schema import EventMergeFacts
from newsradar.events.clustering import _action as clustering_action
from newsradar.events.entities import extract_entities
from newsradar.events.relevance import normalize_text
from newsradar.events.schema import EntityType, RawItemText

EVENT_MERGE_RULE_VERSION = "event-merge-v1"
_INTERMEDIARY_HOSTS = frozenset({"news.google.com", "news.yahoo.com"})
_KEY_NUMBER = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)?(?:\s?(?:%|[BMKT]B?|million|billion))?(?!\w)",
    re.I,
)
_MAX_TEXT = 10_000


def safe_url_identity(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return None
    return f"{parsed.hostname.casefold()}{port}{parsed.path or '/'}"[:1000]


def strong_url_identity(value: str | None) -> str | None:
    identity = safe_url_identity(value)
    if identity is None or identity.split("/", 1)[0] in _INTERMEDIARY_HOSTS:
        return None
    return identity


def load_event_facts(session: Session, event_id: int) -> EventMergeFacts:
    event = session.get(EventRecord, event_id)
    if event is None or event.current_version_number <= 0:
        raise LookupError(f"event_merge_event_not_found:{event_id}")
    version = session.scalar(
        select(EventVersionRecord).where(
            EventVersionRecord.event_id == event.id,
            EventVersionRecord.version_number == event.current_version_number,
        )
    )
    if version is None or not isinstance(version.payload, dict):
        raise ValueError(f"event_merge_current_version_missing:{event_id}")
    rows = session.execute(
        select(RawItemRecord, SourceDefinitionRecord)
        .join(
            EventItemRecord,
            EventItemRecord.raw_item_id == RawItemRecord.id,
        )
        .join(SourceDefinitionRecord, SourceDefinitionRecord.id == RawItemRecord.source_id)
        .where(
            EventItemRecord.event_id == event.id,
            EventItemRecord.added_version_number <= event.current_version_number,
            (
                EventItemRecord.removed_version_number.is_(None)
                | (EventItemRecord.removed_version_number > event.current_version_number)
            ),
        )
        .order_by(RawItemRecord.id)
    ).all()
    algorithms = tuple(
        sorted(
            set(
                session.scalars(
                    select(EventCandidateRecord.algorithm_version).where(
                        EventCandidateRecord.candidate_key == event.canonical_key
                    )
                )
            )
        )
    )
    safe_urls: set[str] = set()
    strong_urls: set[str] = set()
    objects: set[str] = set()
    actions: set[str] = set()
    key_numbers: set[str] = set()
    for raw, source in rows:
        for value in (raw.canonical_url, raw.original_url):
            if identity := safe_url_identity(value):
                safe_urls.add(identity)
            if identity := strong_url_identity(value):
                strong_urls.add(identity)
        text = RawItemText(
            raw_item_id=raw.id,
            title=raw.title or "",
            summary=raw.summary or "",
            content=(raw.content or "")[:_MAX_TEXT],
            item_kind=raw.item_kind,
            publisher_name=raw.publisher_name or source.name,
            source_topics=tuple(source.topics),
        )
        for entity in extract_entities(text):
            if entity.entity_type is not EntityType.ORGANIZATION:
                objects.add(entity.canonical_key)
        normalized = normalize_text(" ".join((text.title, text.summary, text.content)))
        if action := clustering_action(normalized):
            actions.add(action)
        key_numbers.update(
            " ".join(match.group().casefold().split())
            for match in _KEY_NUMBER.finditer(normalized)
        )
    return EventMergeFacts(
        event_id=event.id,
        version_number=event.current_version_number,
        visibility=event.visibility,
        canonical_key=event.canonical_key,
        algorithm_versions=algorithms,
        raw_item_ids=tuple(sorted({raw.id for raw, _ in rows})),
        source_ids=tuple(sorted({raw.source_id for raw, _ in rows})),
        publishers=tuple(sorted({raw.publisher_name or source.name for raw, source in rows})),
        published_at=tuple(sorted({raw.published_at for raw, _ in rows if raw.published_at})),
        safe_url_identities=tuple(sorted(safe_urls)),
        strong_identities=tuple(sorted(strong_urls)),
        object_entities=tuple(sorted(objects)),
        actions=tuple(sorted(actions)),
        evidence_roots=_evidence_roots(version.payload),
        key_numbers=tuple(sorted(key_numbers)),
    )


def merge_input_fingerprint(left: EventMergeFacts, right: EventMergeFacts) -> str:
    ordered = sorted((left, right), key=lambda facts: facts.event_id)
    payload = {
        "algorithm_version": EVENT_MERGE_RULE_VERSION,
        "left": ordered[0].model_dump(mode="json"),
        "right": ordered[1].model_dump(mode="json"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode()).hexdigest()


def _evidence_roots(payload: dict) -> tuple[str, ...]:
    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        return ()
    roots = {
        root[:1000]
        for row in evidence[:1000]
        if isinstance(row, dict)
        and isinstance((root := row.get("root_evidence_key")), str)
        and root
    }
    return tuple(sorted(roots))
