"""Bounded, redacted web projections for event-merge candidate review."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    EventItemRecord,
    EventMergeCandidateRecord,
    EventRecord,
    EventVersionRecord,
    RawItemRecord,
)

_MAX_ROWS = 200
_CANDIDATE_TYPES = frozenset(
    {"legacy_identity", "deterministic_merge", "manual_review"}
)
_CANDIDATE_STATUSES = frozenset(
    {"pending", "confirmed", "dismissed", "applied", "expired", "failed"}
)
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|authorization|bearer|credential|password|secret|token)"
    r"\s*[:=]\s*[^\s,;]+"
)

_REASON_COPY: dict[str, tuple[str, str]] = {
    "exact_cross_algorithm_membership": (
        "旧算法与当前算法事件包含完全相同的原始条目。",
        "保留当前算法事件，并把旧身份转入历史目录。",
    ),
    "same_strong_identity": (
        "两个事件共享同一个可验证的原始内容标识。",
        "复核原始媒体后应用确定性合并。",
    ),
    "same_object_action_without_strong_identity": (
        "对象、动作和时间接近，但缺少可自动证明同一事件的强标识。",
        "人工核对两侧原始报道后确认合并或保持分开。",
    ),
    "event_merge_algorithm_changed": (
        "候选所依据的合并算法已经变化。",
        "重新检查并生成使用当前算法的新候选。",
    ),
    "event_merge_event_not_current": (
        "候选中的事件已经不在当前事件目录。",
        "查看事件历史；如仍需处理，请重新扫描候选。",
    ),
    "event_merge_version_changed": (
        "候选生成后事件版本已经变化。",
        "重新检查并生成新的候选。",
    ),
    "event_merge_membership_changed": (
        "候选生成后事件包含的原始条目已经变化。",
        "重新检查当前成员关系后生成新的候选。",
    ),
    "event_merge_identity_not_strong": (
        "当前事实已不足以支持原候选结论。",
        "保持事件分开，或在新证据出现后重新检查。",
    ),
    "event_merge_recheck_requested": (
        "该候选已按人工请求重新检查。",
        "查看后续修订候选或重新扫描结果。",
    ),
    "event_merge_lease_unavailable": (
        "事件正在被其他任务处理，本次无法取得处理权。",
        "稍后从运行任务页重试。",
    ),
    "event_merge_candidate_expired": (
        "该候选已经过期。",
        "重新检查当前事件事实并生成新候选。",
    ),
    "event_merge_fact_conflict": (
        "两侧当前事实存在不能自动忽略的冲突。",
        "保持事件分开并人工核对冲突事实。",
    ),
    "event_merge_quality_input_unavailable": (
        "合并所需的质量输入暂时不可用。",
        "修复事件质量输入后重新检查。",
    ),
    "event_merge_already_applied": (
        "该候选已经应用。",
        "查看合并后的当前事件与历史事件。",
    ),
    "event_merge_candidate_failed": (
        "候选处理未能完成。",
        "查看对应 Operation 的稳定错误码后重试或保持分开。",
    ),
}

_TYPE_LABELS = {
    "legacy_identity": "旧算法身份重复",
    "deterministic_merge": "确定性强身份合并",
    "manual_review": "需要人工核对",
}

_STATUS_LABELS = {
    "pending": "待处理",
    "confirmed": "已确认，等待执行",
    "dismissed": "已排除",
    "applied": "已应用",
    "expired": "已过期",
    "failed": "处理失败",
}


@dataclass(frozen=True, slots=True)
class EventMergeSummaryView:
    current_event_count: int
    single_member_event_count: int
    cross_source_event_count: int
    raw_items_in_multiple_current_events: int
    legacy_identity_pending_count: int
    deterministic_pending_count: int
    manual_pending_count: int
    applied_count: int
    dismissed_count: int
    expired_count: int
    failed_count: int

    @property
    def pending_count(self) -> int:
        return (
            self.legacy_identity_pending_count
            + self.deterministic_pending_count
            + self.manual_pending_count
        )


@dataclass(frozen=True, slots=True)
class EventMergeCandidateRow:
    candidate_id: int
    revision: int
    candidate_type: str
    candidate_type_label: str
    status: str
    status_label: str
    left_event_id: int
    left_version_number: int
    left_title: str
    right_event_id: int
    right_version_number: int
    right_title: str
    zh_reason: str
    zh_next_action: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EventMergeMemberRow:
    raw_item_id: int
    title: str
    source_id: str
    publisher: str
    published_at: datetime | None
    public_url: str | None
    origin_resolution_status: str


@dataclass(frozen=True, slots=True)
class EventMergeEventSide:
    event_id: int
    version_number: int
    visibility: str
    title: str
    summary: str
    source_ids: tuple[str, ...]
    publishers: tuple[str, ...]
    published_at: tuple[datetime, ...]
    safe_urls: tuple[str, ...]
    strong_identities: tuple[str, ...]
    members: tuple[EventMergeMemberRow, ...]
    object_entities: tuple[str, ...]
    actions: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    key_numbers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EventMergeCandidateDetail:
    candidate_id: int
    revision: int
    supersedes_candidate_id: int | None
    candidate_type: str
    candidate_type_label: str
    status: str
    status_label: str
    algorithm_version: str
    left: EventMergeEventSide
    right: EventMergeEventSide
    shared_strong_identities: tuple[str, ...]
    shared_objects: tuple[str, ...]
    shared_actions: tuple[str, ...]
    time_distance_seconds: int | None
    conflicts: tuple[str, ...]
    reason_code: str
    zh_reason: str
    zh_next_action: str
    allowed_decisions: tuple[str, ...]
    generated_operation_id: int
    reviewed_operation_id: int | None
    applied_operation_id: int | None
    created_at: datetime
    updated_at: datetime


class EventMergeQueryService:
    def __init__(self, session: Session):
        self.session = session

    def summary(self) -> EventMergeSummaryView:
        current_ids = tuple(
            self.session.scalars(
                select(EventRecord.id).where(EventRecord.visibility == "current")
            )
        )
        members: dict[int, set[int]] = {event_id: set() for event_id in current_ids}
        sources: dict[int, set[str]] = {event_id: set() for event_id in current_ids}
        item_events: dict[int, set[int]] = {}
        if current_ids:
            rows = self.session.execute(
                select(
                    EventItemRecord.event_id,
                    EventItemRecord.raw_item_id,
                    RawItemRecord.source_id,
                )
                .join(EventRecord, EventRecord.id == EventItemRecord.event_id)
                .join(RawItemRecord, RawItemRecord.id == EventItemRecord.raw_item_id)
                .where(
                    EventRecord.visibility == "current",
                    EventItemRecord.added_version_number
                    <= EventRecord.current_version_number,
                    (
                        EventItemRecord.removed_version_number.is_(None)
                        | (
                            EventItemRecord.removed_version_number
                            > EventRecord.current_version_number
                        )
                    ),
                )
            )
            for event_id, raw_item_id, source_id in rows:
                members[event_id].add(raw_item_id)
                sources[event_id].add(source_id)
                item_events.setdefault(raw_item_id, set()).add(event_id)

        pending_counts = {candidate_type: 0 for candidate_type in _CANDIDATE_TYPES}
        state_counts = {status: 0 for status in _CANDIDATE_STATUSES}
        for candidate_type, status in self.session.execute(
            select(
                EventMergeCandidateRecord.candidate_type,
                EventMergeCandidateRecord.status,
            )
        ):
            if status in state_counts:
                state_counts[status] += 1
            if status == "pending" and candidate_type in pending_counts:
                pending_counts[candidate_type] += 1
        return EventMergeSummaryView(
            current_event_count=len(current_ids),
            single_member_event_count=sum(len(value) == 1 for value in members.values()),
            cross_source_event_count=sum(len(value) > 1 for value in sources.values()),
            raw_items_in_multiple_current_events=sum(
                len(event_ids) > 1 for event_ids in item_events.values()
            ),
            legacy_identity_pending_count=pending_counts["legacy_identity"],
            deterministic_pending_count=pending_counts["deterministic_merge"],
            manual_pending_count=pending_counts["manual_review"],
            applied_count=state_counts["applied"],
            dismissed_count=state_counts["dismissed"],
            expired_count=state_counts["expired"],
            failed_count=state_counts["failed"],
        )

    def list_candidates(
        self,
        status: str | None = None,
        candidate_type: str | None = None,
        limit: int = _MAX_ROWS,
        *,
        event_id: int | None = None,
    ) -> tuple[EventMergeCandidateRow, ...]:
        bounded_limit = min(max(limit, 1), _MAX_ROWS)
        statement = select(EventMergeCandidateRecord)
        if status in _CANDIDATE_STATUSES:
            statement = statement.where(EventMergeCandidateRecord.status == status)
        elif status:
            return ()
        if candidate_type in _CANDIDATE_TYPES:
            statement = statement.where(
                EventMergeCandidateRecord.candidate_type == candidate_type
            )
        elif candidate_type:
            return ()
        if event_id is not None:
            statement = statement.where(
                (EventMergeCandidateRecord.left_event_id == event_id)
                | (EventMergeCandidateRecord.right_event_id == event_id)
            )
        records = self.session.scalars(
            statement.order_by(EventMergeCandidateRecord.id.desc()).limit(bounded_limit)
        )
        rows: list[EventMergeCandidateRow] = []
        for record in records:
            _, reason, next_action = _reason_projection(record.reason_codes)
            rows.append(
                EventMergeCandidateRow(
                    candidate_id=record.id,
                    revision=record.revision,
                    candidate_type=record.candidate_type,
                    candidate_type_label=_TYPE_LABELS.get(
                        record.candidate_type, "未知候选类型"
                    ),
                    status=record.status,
                    status_label=_STATUS_LABELS.get(record.status, "未知状态"),
                    left_event_id=record.left_event_id,
                    left_version_number=record.left_version_number,
                    left_title=self._version_title(
                        record.left_event_id, record.left_version_number
                    ),
                    right_event_id=record.right_event_id,
                    right_version_number=record.right_version_number,
                    right_title=self._version_title(
                        record.right_event_id, record.right_version_number
                    ),
                    zh_reason=reason,
                    zh_next_action=next_action,
                    created_at=record.created_at,
                )
            )
        return tuple(rows)

    def get_candidate(self, candidate_id: int) -> EventMergeCandidateDetail | None:
        record = self.session.get(EventMergeCandidateRecord, candidate_id)
        if record is None:
            return None
        snapshot = record.facts_snapshot if isinstance(record.facts_snapshot, dict) else {}
        left = self._side(
            snapshot.get("left"), record.left_event_id, record.left_version_number
        )
        right = self._side(
            snapshot.get("right"), record.right_event_id, record.right_version_number
        )
        reason_code, reason, next_action = _reason_projection(record.reason_codes)
        return EventMergeCandidateDetail(
            candidate_id=record.id,
            revision=record.revision,
            supersedes_candidate_id=record.supersedes_candidate_id,
            candidate_type=record.candidate_type,
            candidate_type_label=_TYPE_LABELS.get(record.candidate_type, "未知候选类型"),
            status=record.status,
            status_label=_STATUS_LABELS.get(record.status, "未知状态"),
            algorithm_version=_safe_text(record.algorithm_version, 120),
            left=left,
            right=right,
            shared_strong_identities=tuple(
                sorted(set(left.strong_identities) & set(right.strong_identities))
            ),
            shared_objects=tuple(
                sorted(set(left.object_entities) & set(right.object_entities))
            ),
            shared_actions=tuple(sorted(set(left.actions) & set(right.actions))),
            time_distance_seconds=_minimum_time_distance(
                left.published_at, right.published_at
            ),
            conflicts=_conflicts(left, right),
            reason_code=reason_code,
            zh_reason=reason,
            zh_next_action=next_action,
            allowed_decisions=_allowed_decisions(record.status, record.candidate_type),
            generated_operation_id=record.generated_operation_id,
            reviewed_operation_id=record.reviewed_operation_id,
            applied_operation_id=record.applied_operation_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _version_title(self, event_id: int, version_number: int) -> str:
        version = self.session.scalar(
            select(EventVersionRecord).where(
                EventVersionRecord.event_id == event_id,
                EventVersionRecord.version_number == version_number,
            )
        )
        return _safe_text(version.zh_title if version else None, 500) or "未记录标题"

    def _side(
        self,
        raw_facts: object,
        event_id: int,
        version_number: int,
    ) -> EventMergeEventSide:
        facts = raw_facts if isinstance(raw_facts, dict) else {}
        version = self.session.scalar(
            select(EventVersionRecord).where(
                EventVersionRecord.event_id == event_id,
                EventVersionRecord.version_number == version_number,
            )
        )
        raw_item_ids = _positive_ints(facts.get("raw_item_ids"))[:500]
        raw_items = {
            raw.id: raw
            for raw in self.session.scalars(
                select(RawItemRecord).where(RawItemRecord.id.in_(raw_item_ids))
            )
        } if raw_item_ids else {}
        members = tuple(
            _member(raw_items[raw_item_id])
            for raw_item_id in raw_item_ids
            if raw_item_id in raw_items
        )
        return EventMergeEventSide(
            event_id=event_id,
            version_number=version_number,
            visibility=(
                facts.get("visibility")
                if facts.get("visibility") in {"current", "legacy"}
                else "unknown"
            ),
            title=_safe_text(version.zh_title if version else None, 500)
            or "未记录标题",
            summary=_safe_text(version.zh_summary if version else None, 2_000)
            or "未记录摘要",
            source_ids=_safe_strings(facts.get("source_ids"), 255),
            publishers=_safe_strings(facts.get("publishers"), 255),
            published_at=_datetimes(facts.get("published_at")),
            safe_urls=_safe_identities(facts.get("safe_url_identities")),
            strong_identities=_safe_identities(facts.get("strong_identities")),
            members=members,
            object_entities=_safe_strings(facts.get("object_entities"), 255),
            actions=_safe_strings(facts.get("actions"), 255),
            evidence_roots=_safe_identities(facts.get("evidence_roots")),
            key_numbers=_safe_strings(facts.get("key_numbers"), 120),
        )


def _reason_projection(reason_codes: object) -> tuple[str, str, str]:
    codes = reason_codes if isinstance(reason_codes, (list, tuple)) else ()
    for code in reversed(codes):
        if isinstance(code, str) and code in _REASON_COPY:
            reason, next_action = _REASON_COPY[code]
            return code, reason, next_action
    return (
        "unknown",
        "候选原因暂未提供可公开的中文说明。",
        "请查看冻结事实并保持事件分开，必要时重新检查。",
    )


def _allowed_decisions(status: str, candidate_type: str) -> tuple[str, ...]:
    if status != "pending":
        return ()
    if candidate_type == "manual_review":
        return ("confirm", "dismiss", "recheck")
    if candidate_type in {"legacy_identity", "deterministic_merge"}:
        return ("apply", "dismiss", "recheck")
    return ()


def _safe_text(value: object, max_length: int) -> str:
    text = value.strip() if isinstance(value, str) else ""

    def redact_url(match: re.Match[str]) -> str:
        return _public_url(match.group()) or "[链接已隐藏]"

    text = _URL.sub(redact_url, text)
    text = _SECRET_ASSIGNMENT.sub("敏感信息已隐藏", text)
    return text[:max_length]


def _public_url(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    netloc = parsed.hostname.casefold()
    try:
        if parsed.port is not None:
            netloc += f":{parsed.port}"
    except ValueError:
        return None
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", "", ""))[:1000]


def _safe_identity(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if value.casefold().startswith(("http://", "https://")):
        return _public_url(value)
    if any(marker in value for marker in ("?", "#", "@")):
        return None
    if _SECRET_ASSIGNMENT.search(value):
        return None
    return _safe_text(value, 1000) or None


def _safe_identities(value: object) -> tuple[str, ...]:
    values = value if isinstance(value, (list, tuple)) else ()
    return tuple(
        dict.fromkeys(
            identity
            for item in values[:100]
            if (identity := _safe_identity(item)) is not None
        )
    )


def _safe_strings(value: object, max_length: int) -> tuple[str, ...]:
    values = value if isinstance(value, (list, tuple)) else ()
    return tuple(
        dict.fromkeys(
            text
            for item in values[:500]
            if (text := _safe_text(item, max_length))
        )
    )


def _positive_ints(value: object) -> tuple[int, ...]:
    values = value if isinstance(value, (list, tuple)) else ()
    return tuple(
        dict.fromkeys(
            item
            for item in values
            if isinstance(item, int) and not isinstance(item, bool) and item > 0
        )
    )


def _datetimes(value: object) -> tuple[datetime, ...]:
    values = value if isinstance(value, (list, tuple)) else ()
    result: list[datetime] = []
    for item in values[:500]:
        if isinstance(item, datetime):
            parsed = item
        elif isinstance(item, str) and len(item) <= 64:
            try:
                parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
            except ValueError:
                continue
        else:
            continue
        result.append(
            parsed.replace(tzinfo=UTC)
            if parsed.tzinfo is None
            else parsed.astimezone(UTC)
        )
    return tuple(result)


def _member(raw: RawItemRecord) -> EventMergeMemberRow:
    return EventMergeMemberRow(
        raw_item_id=raw.id,
        title=_safe_text(raw.title, 500) or "未记录标题",
        source_id=_safe_text(raw.source_id, 255),
        publisher=_safe_text(raw.publisher_name, 255) or "未记录发布方",
        published_at=raw.published_at,
        public_url=_public_url(raw.original_url) or _public_url(raw.canonical_url),
        origin_resolution_status=(
            raw.origin_resolution_status
            if raw.origin_resolution_status in {"resolved", "unresolved"}
            else "unknown"
        ),
    )


def _minimum_time_distance(
    left: tuple[datetime, ...], right: tuple[datetime, ...]
) -> int | None:
    if not left or not right:
        return None
    return int(min(abs((first - second).total_seconds()) for first in left for second in right))


def _conflicts(
    left: EventMergeEventSide, right: EventMergeEventSide
) -> tuple[str, ...]:
    conflicts: list[str] = []
    for left_values, right_values, label in (
        (left.object_entities, right.object_entities, "对象不一致"),
        (left.actions, right.actions, "动作不一致"),
        (left.key_numbers, right.key_numbers, "关键数字不一致"),
    ):
        if left_values and right_values and not (set(left_values) & set(right_values)):
            conflicts.append(label)
    return tuple(conflicts)
