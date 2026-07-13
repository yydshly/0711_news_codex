from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from newsradar.web.app import create_app
from newsradar.web.viewmodels import RemediationDashboardView, RemediationRowView


def test_research_routes_are_read_only_and_render():
    app = create_app()
    routes = {route.path: route.methods for route in app.routes if hasattr(route, "methods")}
    assert routes["/research"] == {"GET"}
    assert routes["/research/targets/{source_id}"] == {"GET"}


def test_remediation_console_route_is_read_only():
    app = create_app()
    routes = {route.path: route.methods for route in app.routes if hasattr(route, "methods")}

    assert routes["/remediation"] == {"GET"}


def test_remediation_console_renders_frozen_batch_summary_and_original_probe() -> None:
    dashboard = RemediationDashboardView(
        baseline_at=datetime(2026, 7, 13, 11, 47, tzinfo=UTC),
        total=27,
        reviewed_count=27,
        verifiable_count=26,
        html_count=0,
        policy_or_unknown_count=1,
        category_counts=(("network_transient", "网络暂态", 26),),
        providers=(("github", "GitHub"),),
        rows=(
            RemediationRowView(
                source_id="alpha",
                source_name="Alpha",
                provider_id="github",
                provider_name="GitHub",
                original_probe_id=38,
                category="network_transient",
                category_label="网络暂态",
                reason_zh="网络暂时不可用。",
                next_action_zh="显式复测。",
                candidate_key="official-api",
                candidate_kind="public_api",
                acquisition_label="succeeded / HTTP 200",
                content_label="success / 100%",
                conclusion="试用抓取已验证",
                conclusion_key="verified",
            ),
        ),
    )

    class Service:
        def remediation_dashboard(self, **_filters):
            return dashboard

        def latest_probe_at(self):
            return dashboard.baseline_at

    @contextmanager
    def factory():
        yield Service()

    response = TestClient(create_app(factory)).get("/remediation")

    assert response.status_code == 200
    assert "固定失败来源" in response.text
    assert ">27<" in response.text
    assert "#38" in response.text


def test_research_target_unknown_is_404():
    app = create_app()
    assert any(route.path == "/research/targets/{source_id}" for route in app.routes)
