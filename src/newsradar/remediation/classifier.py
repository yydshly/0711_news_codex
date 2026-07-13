from __future__ import annotations

from typing import Protocol

from .schema import FailureCategory


class ProbeEvidence(Protocol):
    http_status: int | None
    error_code: str | None
    metrics: dict


_POLICY_CODES = frozenset(
    {"missing_credential", "authentication_required", "login_required", "challenge_detected"}
)
_ENDPOINT_CODES = frozenset(
    {"invalid_payload", "invalid_feed", "unsupported_content_type", "schema_drift"}
)
_NETWORK_CODES = frozenset(
    {
        "timeout",
        "connection_error",
        "connecterror",
        "dns_error",
        "tls_error",
        "source_timeout",
    }
)


def classify_probe(run: ProbeEvidence) -> FailureCategory:
    """Classify stored probe evidence without model calls or network I/O."""
    code = (run.error_code or "").lower()
    if run.http_status in {401, 403} or code in _POLICY_CODES:
        return FailureCategory.AUTHENTICATION_OR_POLICY
    if run.http_status == 429 or code == "rate_limited":
        return FailureCategory.RATE_LIMITED
    if run.http_status == 404 or code in _ENDPOINT_CODES:
        return FailureCategory.ENDPOINT_CHANGED
    if run.http_status is not None and 500 <= run.http_status <= 599:
        return FailureCategory.NETWORK_TRANSIENT
    if code in _NETWORK_CODES:
        return FailureCategory.NETWORK_TRANSIENT
    if _incomplete_metrics(run.metrics):
        return FailureCategory.CONTENT_INCOMPLETE
    return FailureCategory.UNKNOWN


def explanation(category: FailureCategory) -> tuple[str, str]:
    return {
        FailureCategory.NETWORK_TRANSIENT: (
            "本次网络或远端服务暂时不可用。",
            "保留证据，后续仅允许低频显式复测。",
        ),
        FailureCategory.RATE_LIMITED: (
            "来源已触发限流。",
            "记录 Retry-After 或限流信息，本批次停止请求。",
        ),
        FailureCategory.ENDPOINT_CHANGED: (
            "端点、内容类型或结构可能已变化。",
            "检查官方 RSS、Atom、Sitemap 或公开 API。",
        ),
        FailureCategory.CONTENT_INCOMPLETE: (
            "响应未提供足够的新闻字段或样本。",
            "核对字段映射，并寻找同一官方来源的备用端点。",
        ),
        FailureCategory.AUTHENTICATION_OR_POLICY: (
            "来源需要凭据、登录或受平台政策限制。",
            "停止自动处理，保留解锁条件或仅发现定位。",
        ),
        FailureCategory.UNKNOWN: (
            "现有探测证据不足以安全判断原因。",
            "保持待人工复核，不猜测访问方式。",
        ),
    }[category]


def _incomplete_metrics(metrics: dict) -> bool:
    sample_count = metrics.get("sample_count")
    completeness = metrics.get("field_completeness")
    missing = metrics.get("missing_required_fields")
    return (
        sample_count == 0
        or bool(missing)
        or (isinstance(completeness, (int, float)) and completeness < 0.60)
    )
