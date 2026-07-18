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


class DailyAutopilotStage(StrEnum):
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


def build_decision_review(snapshot: dict[str, object]) -> DailyReportEditorialReviewDraft:
    title, summary, recommendation, assessment, decision = _review_values(snapshot)
    return DailyReportEditorialReviewDraft.create(
        decision=decision,
        zh_title=title,
        zh_summary=summary,
        review_recommendation=recommendation,
        evidence_assessment=assessment,
    )


def build_overview_review(
    snapshot: dict[str, object],
) -> DailyReportOverviewEditorialReviewDraft:
    title, summary, recommendation, assessment, decision = _review_values(snapshot)
    return DailyReportOverviewEditorialReviewDraft.create(
        decision=decision,
        zh_title=title,
        zh_summary=summary,
        review_recommendation=recommendation,
        evidence_assessment=assessment,
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


def _required_scope_text(item: dict[object, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("invalid_daily_autopilot_catalog_plan")
    return value
