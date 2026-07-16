from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceConclusionInput:
    coverage_mode: str
    availability: str
    successful_fetch: bool
    latest_probe_outcome: str | None
    indirect_item_count: int = 0
    indirect_published_count: int = 0
    indirect_origin_resolved_count: int = 0
    indirect_duplicate_count: int = 0
    has_public_candidate: bool = False
    covered_by_successful_target_id: str | None = None
    managed_by_target_id: str | None = None


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
    if value.covered_by_successful_target_id:
        return _result(
            "covered_by_successful_target",
            "deferred",
            "已由同一官方目标覆盖",
            f"同一官方身份的目标 {value.covered_by_successful_target_id} 已有真实成功抓取证据。",
            "保留此目录记录用于追溯；继续由已验证目标抓取，不重复开发或重复入库。",
        )
    if value.managed_by_target_id:
        return _result(
            "duplicate_catalog_target",
            "deferred",
            "重复目录项",
            f"与目标 {value.managed_by_target_id} 使用同一官方身份，"
            "当前问题和验收由主目标统一承载。",
            "保留历史目录记录；不要重复申请权限、开发抓取器或重复入库。",
        )
    if value.availability == "manual_only" and value.has_public_candidate:
        return _result(
            "public_candidate_pending_acceptance",
            "fixable",
            "已有公开路径待验收",
            "已登记无需凭据的官方公开访问方式，但尚无合格样本。",
            "等待内容出现后复查核心字段，再决定是否启用生产抓取。",
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
        if value.indirect_item_count == 0:
            return _result(
                "indirect_discovery",
                "fixable",
                "只能间接发现",
                "尚无间接发现样本，不能验收原媒体和发布时间字段。",
                "先通过已审核的发现平台获取样本，再检查归因和重复关系。",
            )
        return _result(
            "indirect_discovery",
            "fixable",
            "只能间接发现",
            f"已有 {value.indirect_item_count} 条样本，"
            f"{value.indirect_published_count} 条含发布时间，"
            f"{value.indirect_origin_resolved_count} 条解析出原媒体文章 URL。",
            f"复核归因结果并检查 {value.indirect_duplicate_count} 条重复候选。",
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
