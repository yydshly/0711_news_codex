from __future__ import annotations

LABELS: dict[str, dict[str, str]] = {
    "provider_category": {
        "social_community": "社交与社区",
        "professional_media": "专业媒体",
        "first_party": "第一方来源",
        "aggregator_search": "聚合与搜索",
        "research_developer": "研究与开发者",
        "newsletter_podcast": "新闻简报与播客",
        "trend_business": "趋势与商业",
    },
    "availability": {
        "ready": "可直接使用",
        "requires_credentials": "需要凭据",
        "requires_approval": "需要审批",
        "requires_payment": "需要付费",
        "manual_only": "仅限手动",
        "unavailable": "不可用",
    },
    "coverage_mode": {
        "direct": "直接覆盖",
        "indirect": "间接发现",
        "catalog_only": "仅目录收录",
    },
    "target_type": {
        "publisher_feed": "发布方订阅源",
        "account": "账号",
        "channel": "频道",
        "keyword": "关键词",
        "topic": "主题",
        "community": "社区",
        "search_query": "搜索查询",
        "trend": "趋势",
        "market": "市场",
    },
    "nature": {
        "first_party": "第一方",
        "research": "研究",
        "community": "社区",
        "professional_media": "专业媒体",
        "aggregator": "聚合平台",
        "social": "社交平台",
    },
    "role": {
        "discovery": "发现",
        "evidence": "证据",
        "engagement": "互动",
        "context": "背景",
    },
    "status": {
        "candidate": "候选",
        "active": "启用",
        "degraded": "降级",
        "paused": "暂停",
        "disabled": "禁用",
    },
    "access_kind": {
        "rss": "RSS",
        "atom": "Atom",
        "rest_api": "REST API",
        "public_api": "公开 API",
        "html": "网页 HTML",
        "sitemap": "站点地图",
    },
    "outcome": {
        "success": "成功",
        "degraded": "降级",
        "blocked": "受阻",
        "failed": "失败",
    },
    "probe_type": {
        "capability": "能力探测",
    },
    "risk_band": {
        "low": "低风险",
        "medium": "中风险",
        "high": "高风险",
        "disabled": "已禁用",
    },
    "cost_tier": {
        "free": "免费",
        "free_quota": "免费额度",
        "freemium": "基础免费",
        "paid": "付费",
        "enterprise": "企业版",
        "unknown": "未知",
    },
    "auth_mode": {
        "none": "无需认证",
        "api_key": "API 密钥",
        "oauth": "OAuth",
        "approval": "审批授权",
        "paid": "付费授权",
        "manual": "手动访问",
    },
}


def zh_label(group: str, value: str) -> str:
    return LABELS.get(group, {}).get(value, value)


def explain_failure(reason: str, http_status: int | None, error_code: str | None) -> str:
    normalized = f"{reason} {error_code or ''}".lower()
    if http_status == 429 or "rate" in normalized:
        return "触发远端限流，请等待后重试"
    if http_status == 401 or "credential" in normalized or "token" in normalized:
        return "需要有效凭据才能访问"
    if http_status == 403 or "approval" in normalized or "permission" in normalized:
        return "当前权限未获批准或被远端拒绝"
    if http_status == 404:
        return "远端入口不存在，可能已经迁移"
    if http_status is not None and http_status >= 500:
        return "远端服务暂时不可用"
    if "timeout" in normalized:
        return "连接远端超时"
    if "schema" in normalized or "field" in normalized:
        return "响应结构或字段可能已经变化"
    return "探测未成功，请查看原始原因"
