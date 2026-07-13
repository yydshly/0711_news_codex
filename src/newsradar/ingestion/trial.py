from __future__ import annotations

from datetime import datetime
from math import isfinite

from pydantic import BaseModel, ConfigDict

from newsradar.providers.schema import Availability, CoverageMode
from newsradar.sources.schema import AccessKind, AccessMethod, SourceDefinition

_SENSITIVE_TRIAL_HEADER_NAMES = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie"}
)


def has_sensitive_trial_headers(method: AccessMethod) -> bool:
    """Return whether a method carries headers forbidden for trial fetches."""
    return any(name.lower() in _SENSITIVE_TRIAL_HEADER_NAMES for name in method.headers)


class ProbeSnapshot(BaseModel):
    """The persisted outcome of a source's most recently completed probe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: str
    sample_count: int
    field_completeness: float
    sample_fields: frozenset[str]
    finished_at: datetime


class TrialDecision(BaseModel):
    """A deterministic explanation of a source's trial eligibility."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    eligible: bool
    code: str | None = None
    reason: str

    def __init__(
        self,
        eligible: bool,
        code: str | None = None,
        reason: str = "",
        **data: object,
    ) -> None:
        super().__init__(eligible=eligible, code=code, reason=reason, **data)


def _ineligible(code: str, reason: str) -> TrialDecision:
    return TrialDecision(eligible=False, code=code, reason=reason)


def evaluate_trial_eligibility(
    source: SourceDefinition, probe: ProbeSnapshot | None
) -> TrialDecision:
    """Evaluate supplied source and probe state without external side effects."""
    if probe is None:
        return _ineligible("no_probe", "不可试用抓取：尚无完成的探测记录。")
    if source.coverage_mode == CoverageMode.CATALOG_ONLY:
        return _ineligible("catalog_only", "仅目录收录，不提供试用抓取。")
    if source.coverage_mode != CoverageMode.DIRECT:
        return _ineligible("discovery_only", "仅用于发现，需回源确认")
    if source.availability != Availability.READY:
        return _ineligible("not_ready", "不可试用抓取：来源当前未就绪。")
    if source.risk.hard_block_reason:
        return _ineligible("hard_blocked", "不可试用抓取：来源存在条款或合规硬性阻塞。")

    automatic_methods = [
        method
        for method in source.access_methods
        if method.kind != AccessKind.HTML and not method.requires_manual_approval
    ]
    if not automatic_methods:
        return _ineligible("no_automatic_method", "不可试用抓取：没有非 HTML 自动访问方式。")
    public_methods = [method for method in automatic_methods if not method.auth_envs]
    if not public_methods:
        return _ineligible("credentials_not_allowed", "试用抓取不使用凭据访问方式。")
    if not any(not has_sensitive_trial_headers(method) for method in public_methods):
        return _ineligible(
            "sensitive_headers_not_allowed",
            "试用抓取不允许携带认证或 Cookie 请求头。",
        )
    if probe.outcome != "success":
        return _ineligible("probe_not_successful", "不可试用抓取：最新探测未成功。")
    if probe.sample_count <= 0:
        return _ineligible("no_samples", "不可试用抓取：最新探测未获得样本。")
    if not isfinite(probe.field_completeness) or not 0 <= probe.field_completeness <= 1:
        return _ineligible(
            "invalid_field_completeness",
            "不可试用抓取：样本字段完整度必须是 0 到 1 之间的有限值。",
        )
    if probe.field_completeness < 0.60:
        return _ineligible("incomplete_fields", "不可试用抓取：样本字段完整度低于 0.60。")
    if not {"title", "canonical_url"}.issubset(probe.sample_fields):
        return _ineligible(
            "missing_required_fields",
            "不可试用抓取：样本缺少 title 或 canonical_url。",
        )
    return TrialDecision(True, None, "可试用抓取：公开直连且首次探测合格")
