"""Bounded, redacted web projections for event-merge candidate review."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlunsplit

from sqlalchemy import and_, case, func, select, tuple_
from sqlalchemy.orm import Session

from newsradar.db.models import (
    EventItemRecord,
    EventMergeCandidateRecord,
    EventRecord,
    EventVersionRecord,
    RawItemRecord,
)
from newsradar.url_safety import (
    MAX_URL_IDENTITY_LENGTH,
    bounded_url_identity,
    parse_safe_http_url,
    path_has_sensitive_key,
    url_text_is_safe,
)

_MAX_ROWS = 200
_MAX_DISPLAYED_RAW_ITEMS = 500
_MAX_DISPLAYED_IDENTITIES = 100
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
    "partial_membership_overlap": (
        "两个事件的原始条目部分重叠，但成员集合并不完全相同。",
        "人工核对未重叠条目后，确认合并或保持分开。",
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
    current_item_href: str


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
    strong_identity_count: int
    displayed_strong_identity_count: int
    strong_identities_truncated: bool
    members: tuple[EventMergeMemberRow, ...]
    raw_item_count: int
    displayed_raw_item_count: int
    raw_items_truncated: bool
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
    shared_strong_identity_count: int
    displayed_shared_strong_identity_count: int
    shared_strong_identities_truncated: bool
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


@dataclass(frozen=True, slots=True)
class _BuiltEventSide:
    view: EventMergeEventSide
    all_strong_identities: frozenset[str]


class EventMergeQueryService:
    def __init__(self, session: Session):
        self.session = session

    def summary(self) -> EventMergeSummaryView:
        active_memberships = (
            select(
                EventItemRecord.event_id.label("event_id"),
                EventItemRecord.raw_item_id.label("raw_item_id"),
                RawItemRecord.source_id.label("source_id"),
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
            .subquery()
        )
        event_membership_stats = (
            select(
                active_memberships.c.event_id,
                func.count(func.distinct(active_memberships.c.raw_item_id)).label(
                    "member_count"
                ),
                func.count(func.distinct(active_memberships.c.source_id)).label(
                    "source_count"
                ),
            )
            .group_by(active_memberships.c.event_id)
            .subquery()
        )
        current_event_count, single_member_count, cross_source_count = (
            self.session.execute(
                select(
                    func.count(EventRecord.id),
                    func.coalesce(
                        func.sum(
                            case(
                                (event_membership_stats.c.member_count == 1, 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (event_membership_stats.c.source_count > 1, 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
                .outerjoin(
                    event_membership_stats,
                    event_membership_stats.c.event_id == EventRecord.id,
                )
                .where(EventRecord.visibility == "current")
            ).one()
        )
        repeated_current_raw_items = (
            select(active_memberships.c.raw_item_id)
            .group_by(active_memberships.c.raw_item_id)
            .having(func.count(func.distinct(active_memberships.c.event_id)) > 1)
            .subquery()
        )
        raw_items_in_multiple = self.session.scalar(
            select(func.count()).select_from(repeated_current_raw_items)
        )

        def candidate_count(*conditions) -> object:
            return func.coalesce(
                func.sum(case((and_(*conditions), 1), else_=0)),
                0,
            )

        (
            legacy_pending,
            deterministic_pending,
            manual_pending,
            applied_count,
            dismissed_count,
            expired_count,
            failed_count,
        ) = self.session.execute(
            select(
                candidate_count(
                    EventMergeCandidateRecord.status == "pending",
                    EventMergeCandidateRecord.candidate_type == "legacy_identity",
                ),
                candidate_count(
                    EventMergeCandidateRecord.status == "pending",
                    EventMergeCandidateRecord.candidate_type
                    == "deterministic_merge",
                ),
                candidate_count(
                    EventMergeCandidateRecord.status == "pending",
                    EventMergeCandidateRecord.candidate_type == "manual_review",
                ),
                candidate_count(EventMergeCandidateRecord.status == "applied"),
                candidate_count(EventMergeCandidateRecord.status == "dismissed"),
                candidate_count(EventMergeCandidateRecord.status == "expired"),
                candidate_count(EventMergeCandidateRecord.status == "failed"),
            )
        ).one()
        return EventMergeSummaryView(
            current_event_count=int(current_event_count),
            single_member_event_count=int(single_member_count),
            cross_source_event_count=int(cross_source_count),
            raw_items_in_multiple_current_events=int(raw_items_in_multiple or 0),
            legacy_identity_pending_count=int(legacy_pending),
            deterministic_pending_count=int(deterministic_pending),
            manual_pending_count=int(manual_pending),
            applied_count=int(applied_count),
            dismissed_count=int(dismissed_count),
            expired_count=int(expired_count),
            failed_count=int(failed_count),
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
        records = tuple(
            self.session.scalars(
                statement.order_by(EventMergeCandidateRecord.id.desc()).limit(
                    bounded_limit
                )
            )
        )
        version_keys = {
            key
            for record in records
            for key in (
                (record.left_event_id, record.left_version_number),
                (record.right_event_id, record.right_version_number),
            )
        }
        version_titles: dict[tuple[int, int], str] = {}
        if version_keys:
            versions = self.session.scalars(
                select(EventVersionRecord).where(
                    tuple_(
                        EventVersionRecord.event_id,
                        EventVersionRecord.version_number,
                    ).in_(version_keys)
                )
            )
            version_titles = {
                (version.event_id, version.version_number): (
                    _safe_text(version.zh_title, 500) or "未记录标题"
                )
                for version in versions
            }
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
                    left_title=version_titles.get(
                        (record.left_event_id, record.left_version_number),
                        "未记录标题",
                    ),
                    right_event_id=record.right_event_id,
                    right_version_number=record.right_version_number,
                    right_title=version_titles.get(
                        (record.right_event_id, record.right_version_number),
                        "未记录标题",
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
        left_build = self._side(
            snapshot.get("left"), record.left_event_id, record.left_version_number
        )
        right_build = self._side(
            snapshot.get("right"), record.right_event_id, record.right_version_number
        )
        left = left_build.view
        right = right_build.view
        all_shared_strong_identities = tuple(
            sorted(
                left_build.all_strong_identities
                & right_build.all_strong_identities
            )
        )
        displayed_shared_strong_identities = all_shared_strong_identities[
            :_MAX_DISPLAYED_IDENTITIES
        ]
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
            shared_strong_identities=displayed_shared_strong_identities,
            shared_strong_identity_count=len(all_shared_strong_identities),
            displayed_shared_strong_identity_count=len(
                displayed_shared_strong_identities
            ),
            shared_strong_identities_truncated=(
                len(displayed_shared_strong_identities)
                < len(all_shared_strong_identities)
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

    def _side(
        self,
        raw_facts: object,
        event_id: int,
        version_number: int,
    ) -> _BuiltEventSide:
        facts = raw_facts if isinstance(raw_facts, dict) else {}
        version = self.session.scalar(
            select(EventVersionRecord).where(
                EventVersionRecord.event_id == event_id,
                EventVersionRecord.version_number == version_number,
            )
        )
        all_raw_item_ids = _positive_ints(facts.get("raw_item_ids"))
        raw_item_ids = all_raw_item_ids[:_MAX_DISPLAYED_RAW_ITEMS]
        all_strong_identities = _safe_identities(
            facts.get("strong_identities"), limit=None
        )
        displayed_strong_identities = all_strong_identities[
            :_MAX_DISPLAYED_IDENTITIES
        ]
        members = tuple(
            EventMergeMemberRow(
                raw_item_id=raw_item_id,
                current_item_href=f"/items/{raw_item_id}",
            )
            for raw_item_id in raw_item_ids
        )
        return _BuiltEventSide(
            view=EventMergeEventSide(
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
                strong_identities=displayed_strong_identities,
                strong_identity_count=len(all_strong_identities),
                displayed_strong_identity_count=len(
                    displayed_strong_identities
                ),
                strong_identities_truncated=(
                    len(displayed_strong_identities) < len(all_strong_identities)
                ),
                members=members,
                raw_item_count=len(all_raw_item_ids),
                displayed_raw_item_count=len(raw_item_ids),
                raw_items_truncated=len(raw_item_ids) < len(all_raw_item_ids),
                object_entities=_safe_strings(facts.get("object_entities"), 255),
                actions=_safe_strings(facts.get("actions"), 255),
                evidence_roots=_safe_identities(facts.get("evidence_roots")),
                key_numbers=_safe_strings(facts.get("key_numbers"), 120),
            ),
            all_strong_identities=frozenset(all_strong_identities),
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
    parsed = parse_safe_http_url(value)
    if parsed is None:
        return None
    netloc = parsed.hostname.casefold()
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return bounded_url_identity(
        urlunsplit((parsed.scheme, netloc, parsed.path or "/", "", ""))
    )


def _safe_identity(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if value.casefold().startswith(("http://", "https://")):
        return _public_url(value)
    if any(marker in value for marker in ("?", "#", "@")):
        return None
    if not url_text_is_safe(value, max_length=MAX_URL_IDENTITY_LENGTH):
        return None
    if path_has_sensitive_key(value):
        return None
    if _SECRET_ASSIGNMENT.search(value):
        return None
    return value


def _safe_identities(
    value: object, *, limit: int | None = _MAX_DISPLAYED_IDENTITIES
) -> tuple[str, ...]:
    values = value if isinstance(value, (list, tuple)) else ()
    identities = tuple(
        dict.fromkeys(
            identity
            for item in values
            if (identity := _safe_identity(item)) is not None
        )
    )
    return identities if limit is None else identities[:limit]


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
