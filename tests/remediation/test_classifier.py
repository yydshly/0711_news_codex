from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    ("http_status", "error_code", "metrics", "expected"),
    [
        (401, "http_401", {}, "authentication_or_policy"),
        (403, "http_403", {}, "authentication_or_policy"),
        (429, "http_429", {}, "rate_limited"),
        (404, "http_404", {}, "endpoint_changed"),
        (503, "http_503", {}, "network_transient"),
        (None, "timeout", {}, "network_transient"),
        (None, "ConnectError", {}, "network_transient"),
        (None, "dns_error", {}, "network_transient"),
        (None, "tls_error", {}, "network_transient"),
        (None, "invalid_payload", {}, "endpoint_changed"),
        (200, None, {"sample_count": 0, "field_completeness": 0.0}, "content_incomplete"),
        (
            200,
            None,
            {"sample_count": 5, "missing_required_fields": ["title"]},
            "content_incomplete",
        ),
        (None, "unrecognized", {}, "unknown"),
    ],
)
def test_classify_probe_returns_stable_category(http_status, error_code, metrics, expected):
    from newsradar.remediation.classifier import classify_probe

    run = SimpleNamespace(http_status=http_status, error_code=error_code, metrics=metrics)

    assert classify_probe(run).value == expected


def test_classification_does_not_use_model_or_network(monkeypatch):
    from newsradar.remediation.classifier import classify_probe

    monkeypatch.setattr("socket.create_connection", lambda *args: pytest.fail("network used"))
    run = SimpleNamespace(http_status=429, error_code="http_429", metrics={})

    assert classify_probe(run).value == "rate_limited"
