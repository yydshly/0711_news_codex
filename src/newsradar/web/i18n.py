from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

_BEIJING = ZoneInfo("Asia/Shanghai")

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
        "succeeded": "成功",
        "no_change": "无变化",
        "partial": "部分成功",
        "degraded": "降级",
        "blocked": "受阻",
        "failed": "失败",
        "fallback": "规则回退",
    },
    "event_status": {
        "confirmed": "已确认",
        "emerging": "新兴线索",
        "developing": "持续发展",
        "disputed": "存在分歧",
        "stale": "已过时",
        "rejected": "已排除",
    },
    "event_visibility": {
        "current": "当前版本",
        "legacy": "旧版历史",
    },
    "event_category": {
        "product_model": "产品与模型",
        "developer_tool": "开发者工具",
        "company": "公司动态",
        "model_release": "模型发布",
        "research": "研究进展",
        "product": "产品动态",
        "funding": "融资与商业",
        "policy": "政策与治理",
        "security": "安全事件",
        "benchmark": "基准评测",
        "other": "其他",
    },
    "enrichment_origin": {
        "model": "MiniMax 中文增强",
        "previous_version": "沿用已核验中文版本",
        "rule_fallback": "规则中文回退",
    },
    "score_dimension": {
        "ai_relevance": "AI 相关性",
        "source_coverage": "来源覆盖",
        "source_authority": "来源权威性",
        "recency": "时效",
        "engagement_velocity": "互动热度",
        "novelty": "新颖性",
    },
    "event_reason": {
        "official_evidence": "存在独立官方一手证据",
        "two_independent_professional_roots": "至少两个独立专业媒体证据根",
        "insufficient_independent_evidence": "独立证据仍不足",
        "engagement_unavailable": "暂无可用互动数据",
        "importance:versioned_weights": "重要度使用版本化权重",
        "credibility:official_evidence": "可信度由独立官方证据支持",
        "credibility:two_independent_professional_roots": "可信度由两个独立专业媒体支持",
        "credibility:one_independent_professional_root": "目前仅有一个独立专业媒体证据根",
        "credibility:independent_research": "存在独立研究证据",
        "credibility:social_or_community_only_cap": "仅社交或社区证据，可信度受限",
        "heat:60_importance_40_credibility": "热度由重要度与可信度共同计算",
    },
    "event_limitation": {
        "not_peer_reviewed": "未经同行评审",
        "model_unavailable_or_not_configured": "中文模型不可用，当前使用规则回退",
        "upstream_attribution_not_independent": "上游转载归因不独立",
        "source_role_conflict": "来源角色与证据用途存在冲突",
        "source_nature_not_independent": "来源性质不支持独立证据",
        "source_not_evidence": "该来源仅用于发现，不作为事实证据",
    },
    "evidence_role": {
        "official": "官方一手证据",
        "professional_media": "专业媒体",
        "research": "研究材料",
        "community": "社区线索",
        "social": "社交线索",
        "aggregator": "聚合转载",
        "unknown": "未标注",
    },
    "event_processing_reason": {
        "ambiguous_term_only": "仅命中歧义词",
        "game_or_entertainment": "游戏或娱乐内容",
        "advertisement_or_subscription": "广告、促销或订阅引导",
        "generic_technology": "泛科技内容，缺少直接 AI 关联",
        "auto_repost_without_claim": "自动转载且没有可识别事实主张",
        "insufficient_text": "文本不足，无法形成事件候选",
        "no_ai_signal": "未识别到 AI 信号",
        "ai_entity_without_event_context": "仅出现 AI 实体，缺少事件动作",
        "technology_entity_without_ai_context": "技术实体缺少 AI 语境",
    },
    "model_purpose": {
        "event_enrichment": "事件中文增强",
        "event_conflict_explanation": "分歧解释",
        "event_pair_comparison": "事件候选比对",
        "event_entity_suggestions": "实体建议",
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

_SAFE_EVENT_FALLBACKS = {
    "event_status": "其他状态",
    "event_visibility": "未知版本",
    "event_category": "其他",
    "enrichment_origin": "中文来源未标注",
    "score_dimension": "其他评分",
    "event_reason": "其他可审计原因",
    "event_limitation": "其他已知限制",
    "evidence_role": "未标注",
    "event_processing_reason": "其他规则原因",
    "model_purpose": "其他受控用途",
}


def zh_label(group: str, value: str) -> str:
    labels = LABELS.get(group, {})
    return labels.get(value, _SAFE_EVENT_FALLBACKS.get(group, value))


def format_datetime_zh(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return aware.astimezone(_BEIJING).strftime("%Y-%m-%d %H:%M（北京时间）")


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
