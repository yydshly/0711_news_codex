from newsradar.sources.probes.base import ProbeOutcome
from newsradar.web import app as web_app
from newsradar.web.i18n import explain_failure, format_duration_ms, zh_label


def test_zh_label_covers_dashboard_enums():
    assert zh_label("availability", "ready") == "可直接使用"
    assert zh_label("coverage_mode", "indirect") == "间接发现"
    assert zh_label("probe_type", "capability") == "能力探测"
    assert zh_label("target_type", "community") == "社区"
    assert zh_label("outcome", "succeeded") == "成功"
    assert zh_label("outcome", "no_change") == "无变化"
    assert zh_label("outcome", "partial") == "部分成功"
    assert zh_label("event_visibility", "snapshot") == "运行快照"


def test_probe_outcome_options_match_domain_enum_and_all_have_chinese_labels():
    PROBE_OUTCOME_VALUES = getattr(web_app, "PROBE_OUTCOME_VALUES", ())
    assert PROBE_OUTCOME_VALUES == tuple(outcome.value for outcome in ProbeOutcome)
    assert set(PROBE_OUTCOME_VALUES) == {"success", "degraded", "blocked", "failed"}
    assert all(zh_label("outcome", value) != value for value in PROBE_OUTCOME_VALUES)


def test_zh_label_preserves_unknown_value():
    assert zh_label("availability", "future_state") == "future_state"


def test_failure_explanation_is_deterministic():
    assert explain_failure("rate limit", 429, "rate_limited") == "触发远端限流，请等待后重试"
    assert explain_failure("missing token", 401, None) == "需要有效凭据才能访问"


def test_format_duration_ms_uses_readable_units():
    assert format_duration_ms(245.0) == "245 毫秒"
    assert format_duration_ms(22_538.2334) == "22.5 秒"
    assert format_duration_ms(None) == "未知"
