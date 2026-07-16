from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceConclusionInput:
    coverage_mode: str
    availability: str
    successful_fetch: bool
    latest_probe_outcome: str | None


@dataclass(frozen=True, slots=True)
class SourceConclusion:
    code: str
    bucket: str
    label: str
    reason: str
    next_action: str


def conclude_source(value: SourceConclusionInput) -> SourceConclusion:
    if value.availability == "requires_payment":
        return _result(
            "payment_required",
            "deferred",
            "需要付费",
            "当前自动访问方式需要付费权限。",
            "近期不接入；获得正式预算和授权后再验收。",
        )
    if value.availability == "unavailable":
        return _result(
            "unavailable",
            "deferred",
            "当前不可用",
            "官方当前没有可用内容或接口。",
            "保留目录记录，等待外部条件变化后复查。",
        )
    if value.availability == "requires_approval":
        return _result(
            "needs_approval",
            "user_action",
            "需要平台或合规审批",
            "自动访问必须先完成官方权限、条款或 robots 审查。",
            "完成审批并保存可验证依据后再启用。",
        )
    if value.availability == "manual_only":
        return _result(
            "manual_only",
            "user_action",
            "只能人工查看",
            "尚未找到经过审核的 RSS、API、Sitemap 或合规 HTML 路径。",
            "人工查看；后续仅复查官方公开访问方式。",
        )
    if value.availability == "requires_credentials" and not value.successful_fetch:
        return _result(
            "needs_credentials",
            "user_action",
            "需要配置凭据",
            "官方接口需要凭据，当前没有成功抓取证据。",
            "配置所需环境变量后通过 Worker 重新验收。",
        )
    if value.coverage_mode == "indirect":
        return _result(
            "indirect_discovery",
            "fixable",
            "只能间接发现",
            "该目标只用于发现线索，不能替代原始媒体证据。",
            "验证原始媒体、原始 URL、发布时间和重复关系。",
        )
    if value.successful_fetch:
        return _result(
            "fetched_successfully",
            "actual_success",
            "已真实抓取成功",
            "数据库中存在成功或内容无变化的真实 FetchRun。",
            "继续按现有频率运行，并监控近期失败。",
        )
    if value.latest_probe_outcome == "success":
        return _result(
            "capable_pending_acceptance",
            "fixable",
            "已具备能力但尚未验收",
            "最新内容探针成功，但尚无真实成功 FetchRun。",
            "通过 Worker 发起一次受控真实抓取验收。",
        )
    return _result(
        "needs_technical_validation",
        "fixable",
        "需要技术验证",
        "当前没有足够的成功探针或真实抓取证据。",
        "检查访问方式、中文诊断和最近失败后重新探测。",
    )


def _result(code: str, bucket: str, label: str, reason: str, next_action: str) -> SourceConclusion:
    return SourceConclusion(code, bucket, label, reason, next_action)
