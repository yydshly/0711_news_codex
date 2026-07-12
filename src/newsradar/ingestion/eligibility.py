from __future__ import annotations

from collections.abc import Set

from pydantic import BaseModel, ConfigDict

from newsradar.providers.schema import Availability, CoverageMode
from newsradar.sources.schema import AccessKind, AccessMethod, SourceDefinition, SourceStatus


class EligibilityDecision(BaseModel):
    """A deterministic explanation of whether a source may be fetched."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    error_code: str | None = None
    reason: str
    access_method: AccessMethod | None = None


def _blocked(error_code: str, reason: str) -> EligibilityDecision:
    return EligibilityDecision(allowed=False, error_code=error_code, reason=reason)


def evaluate_fetch_eligibility(
    source: SourceDefinition,
    *,
    approved_only: bool,
    configured_env: Set[str],
    hard_block_reason: str | None,
) -> EligibilityDecision:
    """Evaluate only supplied source state; this function has no external side effects."""
    if hard_block_reason or source.risk.hard_block_reason:
        return _blocked("hard_blocked", "禁止抓取：来源存在条款或合规硬性阻塞。")
    if source.status == SourceStatus.PAUSED:
        return _blocked("source_paused", "禁止抓取：来源已暂停。")
    if source.status == SourceStatus.DISABLED:
        return _blocked("source_disabled", "禁止抓取：来源已禁用。")
    if source.availability == Availability.REQUIRES_PAYMENT:
        return _blocked("requires_payment", "禁止抓取：来源需要付费权限。")
    if source.availability == Availability.REQUIRES_APPROVAL:
        return _blocked("requires_approval", "禁止抓取：来源需要人工审批。")
    if source.availability == Availability.MANUAL_ONLY:
        return _blocked("manual_only", "禁止抓取：来源仅允许人工操作。")
    if source.availability == Availability.UNAVAILABLE:
        return _blocked("unavailable", "禁止抓取：来源当前不可用。")
    if source.coverage_mode == CoverageMode.CATALOG_ONLY:
        return _blocked("catalog_only", "禁止抓取：来源仅用于目录覆盖。")
    if approved_only and not source.ingestion.enabled:
        return _blocked("not_approved", "禁止抓取：来源未列入已批准抓取清单。")

    eligible_methods = [
        method for method in source.access_methods if method.kind != AccessKind.HTML
    ]
    if not eligible_methods:
        return _blocked("html_only", "禁止抓取：仅提供 HTML 访问方式。")

    for method in eligible_methods:
        if method.auth_env is None or method.auth_env in configured_env:
            return EligibilityDecision(
                allowed=True,
                reason=f"允许抓取：已选择已审核的 {method.kind.value} 访问方式。",
                access_method=method,
            )
    return _blocked("missing_credentials", "禁止抓取：缺少所选访问方式需要的凭据。")
