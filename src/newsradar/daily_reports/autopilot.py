from __future__ import annotations

from enum import StrEnum

from newsradar.daily_reports.schema import (
    DailyReportEditorialReviewDraft,
    DailyReportOverviewEditorialReviewDraft,
)
from newsradar.sources.catalog_refresh import (
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
    CatalogResultCode,
)
from newsradar.waves.planning import (
    WaveMemberSnapshot,
    WavePlan,
    wave_plan_from_members,
)


class DailyAutopilotStage(StrEnum):
    ENQUEUE_CONTENT_WAVE = "enqueue_content_wave"
    WAIT_CONTENT_WAVE = "wait_content_wave"
    ENQUEUE_SOURCE_REFRESH = "enqueue_source_refresh"
    WAIT_SOURCE_REFRESH = "wait_source_refresh"
    ENQUEUE_EVENT_PIPELINE = "enqueue_event_pipeline"
    WAIT_EVENT_PIPELINE = "wait_event_pipeline"
    GENERATE_REPORT = "generate_report"
    WRITE_REVIEWS = "write_reviews"
    ARCHIVE_AND_ENQUEUE_AUDIO = "archive_and_enqueue_audio"
    WAIT_AUDIO = "wait_audio"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_AUTOPILOT_STAGES = frozenset(
    {
        DailyAutopilotStage.COMPLETED,
        DailyAutopilotStage.FAILED,
        DailyAutopilotStage.CANCELLED,
    }
)


def serialize_catalog_plan(plan: CatalogRefreshPlan) -> dict[str, object]:
    """Store a frozen, secret-free source refresh plan for a durable run."""
    return {
        "catalog_digest": plan.catalog_digest,
        "members": [
            {
                "source_id": member.source_id,
                "provider_id": member.provider_id,
                "definition_hash": member.definition_hash,
                "provider_definition_hash": member.provider_definition_hash,
                "availability": member.availability,
                "coverage_mode": member.coverage_mode,
                "access_kind": member.access_kind,
                "lane": member.lane.value,
                "initial_result_code": (
                    member.initial_result_code.value if member.initial_result_code else None
                ),
            }
            for member in plan.members
        ],
    }


def deserialize_catalog_plan(value: object) -> CatalogRefreshPlan:
    """Reconstruct a frozen refresh plan without consulting settings or the catalog."""
    if not isinstance(value, dict) or not isinstance(value.get("members"), list):
        raise ValueError("invalid_daily_autopilot_catalog_plan")
    members: list[CatalogRefreshMemberSnapshot] = []
    for item in value["members"]:
        if not isinstance(item, dict):
            raise ValueError("invalid_daily_autopilot_catalog_plan")
        try:
            source_id = _required_scope_text(item, "source_id")
            provider_id = _required_scope_text(item, "provider_id")
            definition_hash = _required_scope_text(item, "definition_hash")
            availability = _required_scope_text(item, "availability")
            coverage_mode = _required_scope_text(item, "coverage_mode")
            access_kind = _required_scope_text(item, "access_kind")
            lane = CatalogRefreshLane(_required_scope_text(item, "lane"))
            initial_code_value = item.get("initial_result_code")
            initial_code = (
                CatalogResultCode(initial_code_value)
                if isinstance(initial_code_value, str) and initial_code_value
                else None
            )
            provider_hash = item.get("provider_definition_hash")
            if provider_hash is not None and not isinstance(provider_hash, str):
                raise ValueError("invalid_daily_autopilot_catalog_plan")
        except ValueError as exc:
            raise ValueError("invalid_daily_autopilot_catalog_plan") from exc
        members.append(
            CatalogRefreshMemberSnapshot(
                source_id=source_id,
                provider_id=provider_id,
                definition_hash=definition_hash,
                provider_definition_hash=provider_hash,
                availability=availability,
                coverage_mode=coverage_mode,
                access_kind=access_kind,
                lane=lane,
                initial_result_code=initial_code,
            )
        )
    plan = CatalogRefreshPlan.from_members(members)
    if value.get("catalog_digest") != plan.catalog_digest:
        raise ValueError("invalid_daily_autopilot_catalog_plan")
    return plan


def serialize_wave_plan(plan: WavePlan) -> dict[str, object]:
    """Store a frozen high-value wave without settings, credentials, or tokens."""
    return {
        "profile_id": plan.profile_id,
        "digest": plan.digest,
        "window_hours": plan.window_hours,
        "trend_days": plan.trend_days,
        "members": [
            {
                "source_id": member.source_id,
                "provider_id": member.provider_id,
                "definition_hash": member.definition_hash,
                "roles": list(member.roles),
                "availability": member.availability,
                "access_kind": member.access_kind,
                "fetchable": member.fetchable,
                "blocked_reason": member.blocked_reason,
                "nature": member.nature,
            }
            for member in plan.members
        ],
    }


def deserialize_wave_plan(value: object) -> WavePlan:
    """Restore a high-value wave and reject malformed or tampered digest fields."""
    error = "invalid_daily_autopilot_wave_plan"
    if not isinstance(value, dict) or not isinstance(value.get("members"), list):
        raise ValueError(error)
    try:
        profile_id = _required_scope_text(value, "profile_id", error=error)
        digest = _required_scope_text(value, "digest", error=error)
        window_hours = _required_scope_integer(value, "window_hours", error=error)
        trend_days = _required_scope_integer(value, "trend_days", error=error)
        members = tuple(_deserialize_wave_member(item) for item in value["members"])
    except (TypeError, ValueError) as exc:
        raise ValueError(error) from exc
    plan = wave_plan_from_members(
        profile_id=profile_id,
        members=members,
        window_hours=window_hours,
        trend_days=trend_days,
    )
    if digest != plan.digest:
        raise ValueError(error)
    return plan


def _deserialize_wave_member(value: object) -> WaveMemberSnapshot:
    error = "invalid_daily_autopilot_wave_plan"
    if not isinstance(value, dict):
        raise ValueError(error)
    roles_value = value.get("roles")
    fetchable = value.get("fetchable")
    blocked_reason = value.get("blocked_reason")
    if (
        not isinstance(roles_value, list)
        or any(not isinstance(role, str) or not role for role in roles_value)
        or not isinstance(fetchable, bool)
        or (blocked_reason is not None and not isinstance(blocked_reason, str))
    ):
        raise ValueError(error)
    return WaveMemberSnapshot(
        source_id=_required_scope_text(value, "source_id", error=error),
        provider_id=_required_scope_text(value, "provider_id", error=error),
        definition_hash=_required_scope_text(value, "definition_hash", error=error),
        roles=tuple(roles_value),
        availability=_required_scope_text(value, "availability", error=error),
        access_kind=_required_scope_text(value, "access_kind", error=error),
        fetchable=fetchable,
        blocked_reason=blocked_reason,
        nature=_required_scope_text(value, "nature", error=error),
    )


def build_decision_review(
    snapshot: dict[str, object],
    *,
    zh_title: str | None = None,
    zh_summary: str | None = None,
    review_recommendation: str | None = None,
    evidence_assessment: str | None = None,
) -> DailyReportEditorialReviewDraft:
    title, summary, recommendation, assessment, decision = _review_values(snapshot)
    return DailyReportEditorialReviewDraft.create(
        decision=decision,
        zh_title=zh_title or title,
        zh_summary=zh_summary or summary,
        review_recommendation=review_recommendation or recommendation,
        evidence_assessment=evidence_assessment or assessment,
    )


def build_overview_review(
    snapshot: dict[str, object],
    *,
    zh_title: str | None = None,
    zh_summary: str | None = None,
    review_recommendation: str | None = None,
    evidence_assessment: str | None = None,
) -> DailyReportOverviewEditorialReviewDraft:
    title, summary, recommendation, assessment, decision = _review_values(snapshot)
    return DailyReportOverviewEditorialReviewDraft.create(
        decision=decision,
        zh_title=zh_title or title,
        zh_summary=zh_summary or summary,
        review_recommendation=review_recommendation or recommendation,
        evidence_assessment=evidence_assessment or assessment,
    )


def _review_values(snapshot: dict[str, object]) -> tuple[str, str, str, str, str]:
    title = _text(snapshot, "zh_title", "未命名事件")
    summary = _text(snapshot, "zh_summary", "当前公开材料不足以形成完整中文概述。")
    roots = _integer(snapshot, "independent_root_count")
    if _text(snapshot, "status", "emerging") == "confirmed" or roots >= 2:
        return (
            title,
            summary,
            "建议持续跟踪后续影响与执行细节。",
            "现有公开证据可支持当前判断。",
            "keep",
        )
    return (
        title,
        summary,
        "建议保留为待补证信号，关注新增独立公开来源。",
        "当前独立证据根不足，仍需补充确认。",
        "needs_evidence",
    )


def _text(snapshot: dict[str, object], key: str, fallback: str) -> str:
    value = snapshot.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _integer(snapshot: dict[str, object], key: str) -> int:
    value = snapshot.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _required_scope_text(
    item: dict[object, object],
    key: str,
    *,
    error: str = "invalid_daily_autopilot_catalog_plan",
) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(error)
    return value


def _required_scope_integer(
    item: dict[object, object], key: str, *, error: str
) -> int:
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(error)
    return value
