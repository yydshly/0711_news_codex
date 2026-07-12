from newsradar.web.i18n import explain_failure, zh_label


def test_zh_label_covers_dashboard_enums():
    assert zh_label("availability", "ready") == "可直接使用"
    assert zh_label("coverage_mode", "indirect") == "间接发现"
    assert zh_label("probe_type", "capability") == "能力探测"
    assert zh_label("target_type", "community") == "社区"


def test_zh_label_preserves_unknown_value():
    assert zh_label("availability", "future_state") == "future_state"


def test_failure_explanation_is_deterministic():
    assert explain_failure("rate limit", 429, "rate_limited") == "触发远端限流，请等待后重试"
    assert explain_failure("missing token", 401, None) == "需要有效凭据才能访问"
