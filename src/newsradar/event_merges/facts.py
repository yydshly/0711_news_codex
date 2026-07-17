"""Bounded, normalized facts used only for event-merge candidate generation."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from urllib.parse import SplitResult, parse_qsl, urlunsplit

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
from newsradar.url_safety import (
    MAX_URL_QUERY_FIELDS,
    bounded_url_identity,
    normalized_http_netloc,
    parse_safe_http_url,
    path_is_content_identity,
)

EVENT_MERGE_RULE_VERSION = "event-merge-v2"
_INTERMEDIARY_HOSTS = frozenset({"news.google.com", "news.yahoo.com"})
_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"})
_YOUTUBE_SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
_YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_KEY_NUMBER = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)?(?:\s?(?:%|[BMKT]B?|million|billion))?(?!\w)",
    re.I,
)
_MAX_TEXT = 10_000
_SAFE_EVIDENCE_ROOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,999}$")
_SENSITIVE_EVIDENCE_ROOT = re.compile(
    r"(?:api[_-]?key|authorization|bearer|credential|password|secret|token)",
    re.I,
)
_CREDENTIAL_SHAPED_EVIDENCE_ROOT = re.compile(r"^[^:/@\s]+:[^/@\s]+@")


def safe_url_identity(value: str | None) -> str | None:
    parsed = parse_safe_http_url(value)
    if parsed is None:
        return None
    return bounded_url_identity(f"{normalized_http_netloc(parsed)}{parsed.path or '/'}")


def strong_url_identity(value: str | None) -> str | None:
    parsed = parse_safe_http_url(value)
    if parsed is None:
        return None
    hostname = parsed.hostname.casefold()
    if hostname in _INTERMEDIARY_HOSTS:
        return None
    if hostname in _YOUTUBE_HOSTS or hostname in _YOUTUBE_SHORT_HOSTS:
        return _youtube_video_identity(parsed)
    if parsed.query or not path_is_content_identity(parsed.path):
        return None
    return bounded_url_identity(
        urlunsplit(
            (
                parsed.scheme,
                normalized_http_netloc(parsed),
                parsed.path or "/",
                "",
                "",
            )
        )
    )


def _youtube_video_identity(parsed: SplitResult) -> str | None:
    if parsed.username is not None or parsed.password is not None:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    default_port = 443 if parsed.scheme == "https" else 80
    if port not in {None, default_port}:
        return None
    hostname = parsed.hostname.casefold()
    try:
        query_pairs = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=MAX_URL_QUERY_FIELDS,
            errors="strict",
        )
    except (UnicodeDecodeError, ValueError):
        return None
    if hostname in _YOUTUBE_SHORT_HOSTS:
        video_id = _youtube_path_video_id(parsed.path, allowed_prefixes=())
        if any(key == "v" for key, _ in query_pairs):
            return None
    elif parsed.path == "/watch":
        video_ids = [query_value for key, query_value in query_pairs if key == "v"]
        if len(video_ids) != 1:
            return None
        video_id = video_ids[0]
    else:
        video_id = _youtube_path_video_id(
            parsed.path,
            allowed_prefixes=("shorts", "live", "embed"),
        )
        if any(key == "v" for key, _ in query_pairs):
            return None
    if video_id is None or _YOUTUBE_VIDEO_ID.fullmatch(video_id) is None:
        return None
    return f"youtube.com/watch/{video_id}"


def _youtube_path_video_id(path: str, *, allowed_prefixes: tuple[str, ...]) -> str | None:
    segments = path.split("/")
    if allowed_prefixes:
        if len(segments) != 3 or segments[0] or segments[1] not in allowed_prefixes:
            return None
        return segments[2]
    if len(segments) != 2 or segments[0]:
        return None
    return segments[1]


def load_event_facts(session: Session, event_id: int) -> EventMergeFacts:
    event = session.get(EventRecord, event_id)
    if event is None or event.current_version_number <= 0:
        raise LookupError(f"event_merge_event_not_found:{event_id}")
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
    return build_event_facts_from_rows(
        session,
        event,
        tuple((raw, source) for raw, source in rows),
    )


def build_event_facts_from_rows(
    session: Session,
    event: EventRecord,
    rows: tuple[tuple[RawItemRecord, SourceDefinitionRecord], ...],
) -> EventMergeFacts:
    version = session.scalar(
        select(EventVersionRecord).where(
            EventVersionRecord.event_id == event.id,
            EventVersionRecord.version_number == event.current_version_number,
        )
    )
    if version is None or not isinstance(version.payload, dict):
        raise ValueError(f"event_merge_current_version_missing:{event.id}")
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
            " ".join(match.group().casefold().split()) for match in _KEY_NUMBER.finditer(normalized)
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
        safe_root
        for row in evidence[:1000]
        if isinstance(row, dict)
        and isinstance((root := row.get("root_evidence_key")), str)
        and (safe_root := _safe_evidence_root(root)) is not None
    }
    return tuple(sorted(roots))


def _safe_evidence_root(value: str) -> str | None:
    bounded = value.strip()
    if len(bounded) > 1000:
        return None
    if bounded.casefold().startswith(("http://", "https://")):
        return safe_url_identity(bounded)
    if (
        not bounded
        or _SENSITIVE_EVIDENCE_ROOT.search(bounded)
        or _CREDENTIAL_SHAPED_EVIDENCE_ROOT.search(bounded)
        or _SAFE_EVIDENCE_ROOT.fullmatch(bounded) is None
    ):
        return None
    return bounded
