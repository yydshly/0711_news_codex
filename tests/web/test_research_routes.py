from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from newsradar.db.models import SourceResearchProfileRecord
from newsradar.sources.repository import SourceRepository
from newsradar.sources.yaml_loader import load_source_tree
from newsradar.web.app import create_app
from newsradar.web.queries import DashboardQueryService
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


def test_research_target_explains_duplicate_and_needs_research_status(db_session) -> None:
    db_session.add_all(
        [
            SourceResearchProfileRecord(
                source_id="github-openai-python",
                status="duplicate",
                wanted_information=[],
                conclusion="保留的历史目录项。",
                no_fallback_reason=None,
                reviewed_at=None,
            ),
            SourceResearchProfileRecord(
                source_id="search-ai",
                status="needs_research",
                wanted_information=[],
                conclusion="唯一保留的间接发现入口。",
                no_fallback_reason=None,
                reviewed_at=None,
            ),
        ]
    )
    db_session.commit()

    @contextmanager
    def factory():
        yield DashboardQueryService(db_session)

    client = TestClient(create_app(factory))
    duplicate = client.get("/research/targets/github-openai-python")
    canonical = client.get("/research/targets/search-ai")

    assert "历史目录项" in duplicate.text
    assert "不会参与探测或抓取" in duplicate.text
    assert "尚未完成样本、字段、条款和备用方式验证" in canonical.text


def test_research_target_renders_resolved_openai_catalog_pair(db_session) -> None:
    SourceRepository(db_session).sync(load_source_tree(Path("sources")))
    db_session.commit()

    @contextmanager
    def factory():
        yield DashboardQueryService(db_session)

    client = TestClient(create_app(factory))
    duplicate = client.get("/research/targets/universe-openai-1")
    canonical = client.get("/research/targets/universe-openai-2")

    assert duplicate.status_code == canonical.status_code == 200
    assert "重复" in duplicate.text
    assert "universe-openai-2" in duplicate.text
    assert "待研究" in canonical.text
    assert "尚未完成样本、字段、条款和备用方式验证" in canonical.text
