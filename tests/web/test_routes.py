from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, ProgrammingError

from newsradar.web import create_app
from newsradar.web.viewmodels import (
    AccessMethodView,
    DashboardSummary,
    GapGroup,
    ProbeRow,
    ProviderDetail,
    ProviderRow,
    RiskView,
    TargetDetail,
    TargetRow,
)


class FakeDashboardService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.provider_filters: dict[str, str] | None = None
        self.target_filters: dict[str, str] | None = None
        self.content_completeness: float | None = 1.0
        self.has_content_probes = True

    def summary(self) -> DashboardSummary:
        self.calls.append("summary")
        return DashboardSummary(
            provider_count=2,
            target_count=3,
            free_direct_count=1,
            indirect_count=1,
            blocked_count=1,
            three_success_count=0,
            category_counts=(("first_party", 2),),
            latest_probe_at=datetime(2026, 7, 11, 9, 30),
        )

    def providers(self, filters=None):
        self.calls.append("providers")
        self.provider_filters = filters
        return [self._provider_row()]

    @staticmethod
    def _provider_row() -> ProviderRow:
        return ProviderRow(
            provider_id="github",
            name="GitHub",
            category="research_developer",
            category_label="研究与开发者",
            cost_tier="free",
            cost_label="免费",
            availability="ready",
            availability_label="可直接使用",
            target_count=1,
            direct_count=1,
            indirect_count=0,
            latest_outcome="success",
            latest_outcome_label="成功",
            reviewed_at=date(2026, 7, 10),
            auth_mode="api_key",
            auth_label="API 密钥",
            capabilities=("search", "releases"),
        )

    @staticmethod
    def _target_row() -> TargetRow:
        return TargetRow(
            source_id="github-openai-python",
            name="OpenAI Python",
            provider_id="github",
            provider_name="GitHub",
            target_type="publisher_feed",
            target_type_label="发布方订阅源",
            coverage_mode="direct",
            coverage_label="直接覆盖",
            availability="ready",
            availability_label="可直接使用",
            access_kind="rss",
            access_label="RSS",
            risk_total=5,
            latest_content_at=datetime(2026, 7, 11, 9, 30),
            latest_outcome="success",
            latest_outcome_label="成功",
            roles=("discovery",),
            role_labels=("发现",),
        )

    def provider_detail(self, provider_id: str):
        self.calls.append("provider_detail")
        if provider_id != "github":
            return None
        return ProviderDetail(
            row=self._provider_row(),
            homepage="https://github.example/",
            docs_url="https://github.example/docs",
            terms_url="https://github.example/terms",
            auth_mode="api_key",
            auth_label="API 密钥",
            capabilities=("search", "releases"),
            required_env=("GITHUB_TOKEN",),
            evidence=("https://github.example/evidence",),
            unlock_requirements=("配置只读令牌",),
            notes="已审核的 Provider",
            targets=(self._target_row(),),
            probes=(
                ProbeRow(
                    probe_id="capability-1",
                    object_id="github",
                    object_name="GitHub",
                    probe_type="capability",
                    probe_type_label="能力探测",
                    outcome="success",
                    outcome_label="成功",
                    checked_at=datetime(2026, 7, 11, 9, 30),
                    http_status=200,
                    latency_ms=25.0,
                    completeness=None,
                    reason_zh="成功",
                    reason_raw="ok",
                ),
            ),
        )

    def targets(self, filters=None):
        self.calls.append("targets")
        self.target_filters = filters
        return [self._target_row()]

    def target_detail(self, source_id: str):
        self.calls.append("target_detail")
        if source_id != "github-openai-python":
            return None
        return TargetDetail(
            row=self._target_row(),
            official_identity_url="https://github.example/openai-python",
            reviewed_at=date(2026, 7, 10),
            status="active",
            status_label="启用",
            nature="first_party",
            nature_label="第一方",
            language="en",
            roles=(("discovery", "发现"),),
            topics=("ai", "python"),
            expected_fields=("title", "canonical_url"),
            unlock_requirements=("配置只读令牌",),
            notes="已审核的 Target",
            access_methods=(
                AccessMethodView(
                    kind="rss",
                    kind_label="RSS",
                    url="https://feeds.example/openai-python",
                    priority=1,
                    requires_manual_approval=False,
                    auth_env="GITHUB_TOKEN",
                ),
                AccessMethodView(
                    kind="html",
                    kind_label="网页 HTML",
                    url="https://github.example/openai-python",
                    priority=2,
                    requires_manual_approval=False,
                    auth_env=None,
                ),
            ),
            risk=RiskView(
                terms=1,
                authentication=1,
                stability=1,
                data_quality=1,
                operating_cost=1,
                total=5,
                evidence=("https://risk.example/openai-python",),
                hard_block_reason=None,
                assessed_at=datetime(2026, 7, 10, 9, 30),
            ),
            recent_probes=tuple(self.probes()) if self.has_content_probes else (),
        )

    def probes(self):
        self.calls.append("probes")
        return [
            ProbeRow(
                probe_id="content-1",
                object_id="source-1",
                object_name="示例内容源",
                probe_type="content",
                probe_type_label="内容探测",
                outcome="success",
                outcome_label="成功",
                checked_at=datetime(2026, 7, 11, 9, 30),
                http_status=200,
                latency_ms=25.0,
                completeness=self.content_completeness,
                reason_zh="成功",
                reason_raw="ok",
            )
        ]

    def gap_groups(self):
        self.calls.append("gap_groups")
        return (
            GapGroup(
                availability="requires_payment",
                label="需要付费",
                target_count=1,
                targets=(),
            ),
        )


class FakePostgresError(Exception):
    def __init__(self, message: str, sqlstate: str | None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


@pytest.fixture
def fake_service() -> FakeDashboardService:
    return FakeDashboardService()


@pytest.fixture
def client(fake_service: FakeDashboardService) -> Iterator[TestClient]:
    @contextmanager
    def fake_service_context() -> Iterator[FakeDashboardService]:
        yield fake_service

    with TestClient(
        create_app(lambda: fake_service_context()), raise_server_exceptions=False
    ) as test_client:
        yield test_client


def test_root_renders_chinese_read_only_shell(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert "总览指挥台" in response.text
    assert "只读本机模式" in response.text
    assert 'class="skip-link"' in response.text
    assert "<aside" in response.text
    assert "<nav" in response.text
    assert "<main" in response.text
    for label in ("总览指挥台", "来源能力", "探测记录", "目标目录", "阻塞与解锁"):
        assert label in response.text


def test_dashboard_shows_strict_metrics_and_diagnostic(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    for text in (
        "Provider 总数",
        "Target 总数",
        "免费直接覆盖",
        "间接发现",
        "阻塞目标",
        "连续三轮成功",
    ):
        assert text in response.text
    for text in ("当前能感知", "主要盲区", "建议下一步"):
        assert text in response.text
    for text in (
        "社交与社区",
        "专业媒体",
        "第一方来源",
        "聚合与搜索",
        "研究与开发者",
        "新闻简报与播客",
        "趋势与商业",
    ):
        assert text in response.text
    assert "示例内容源" in response.text
    assert "需要付费" in response.text
    assert 'href="/targets?coverage_mode=direct&amp;availability=ready"' in response.text


def test_dashboard_calls_out_missing_probe_history():
    class NoProbeHistoryService(FakeDashboardService):
        def summary(self) -> DashboardSummary:
            summary = super().summary()
            return DashboardSummary(
                provider_count=summary.provider_count,
                target_count=summary.target_count,
                free_direct_count=summary.free_direct_count,
                indirect_count=summary.indirect_count,
                blocked_count=summary.blocked_count,
                three_success_count=summary.three_success_count,
                category_counts=summary.category_counts,
                latest_probe_at=None,
            )

        def probes(self):
            self.calls.append("probes")
            return []

    @contextmanager
    def no_history_context() -> Iterator[NoProbeHistoryService]:
        yield NoProbeHistoryService()

    with TestClient(create_app(lambda: no_history_context())) as test_client:
        response = test_client.get("/")

    assert response.status_code == 200
    assert "暂无探测历史" in response.text


def test_security_headers_are_present(client: TestClient):
    response = client.get("/")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_method_not_allowed_preserves_status_and_security_headers(client: TestClient):
    response = client.post("/")

    assert response.status_code == 405
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_unknown_route_is_chinese_404(client: TestClient):
    response = client.get("/missing")

    assert response.status_code == 404
    assert "页面不存在" in response.text


def _response_for_database_error(error: Exception, path: str = "/"):
    @contextmanager
    def failing_context() -> Iterator[FakeDashboardService]:
        raise error
        yield FakeDashboardService()

    with TestClient(create_app(lambda: failing_context())) as test_client:
        return test_client.get(path)


def test_unavailable_database_renders_safe_command_and_failed_status():
    error = OperationalError(
        "connection has password=do-not-leak", {}, Exception("secret")
    )

    response = _response_for_database_error(error)

    assert response.status_code == 503
    assert "uv run newsradar db start" in response.text
    assert 'class="status status-failed"' in response.text
    assert "数据库连接失败" in response.text
    assert "do-not-leak" not in response.text
    assert "Traceback" not in response.text


def test_undefined_table_renders_migration_command_and_blocked_status():
    error = ProgrammingError(
        "missing table api_key=do-not-leak",
        {},
        FakePostgresError("undefined table secret", "42P01"),
    )

    response = _response_for_database_error(error)

    assert response.status_code == 503
    assert "uv run alembic upgrade head" in response.text
    assert 'class="status status-blocked"' in response.text
    assert "数据库等待迁移" in response.text
    assert "do-not-leak" not in response.text
    assert "undefined table secret" not in response.text


def test_other_programming_error_renders_generic_safe_failure():
    error = ProgrammingError(
        "invalid query api_key=do-not-leak",
        {},
        FakePostgresError("syntax secret", "42601"),
    )

    response = _response_for_database_error(error)

    assert response.status_code == 503
    assert "数据库查询失败" in response.text
    assert 'class="status status-failed"' in response.text
    assert "uv run alembic upgrade head" not in response.text
    assert "do-not-leak" not in response.text
    assert "syntax secret" not in response.text


def test_provider_list_uses_safe_database_error_boundary():
    error = OperationalError(
        "connection has password=do-not-leak", {}, Exception("secret")
    )

    response = _response_for_database_error(error, "/providers")

    assert response.status_code == 503
    assert "uv run newsradar db start" in response.text
    assert "数据库连接失败" in response.text
    assert "do-not-leak" not in response.text


def test_target_detail_uses_safe_migration_error_boundary():
    error = ProgrammingError(
        "missing table api_key=do-not-leak",
        {},
        FakePostgresError("undefined table secret", "42P01"),
    )

    response = _response_for_database_error(error, "/targets/github-openai-python")

    assert response.status_code == 503
    assert "uv run alembic upgrade head" in response.text
    assert "数据库等待迁移" in response.text
    assert "do-not-leak" not in response.text
    assert "undefined table secret" not in response.text


def test_static_shell_assets_preserve_accessible_navigation(client: TestClient):
    css = client.get("/static/styles.css")
    javascript = client.get("/static/app.js")

    assert css.status_code == 200
    assert javascript.status_code == 200
    assert ":focus-visible" in css.text
    assert "@media (max-width: 760px)" in css.text
    assert "aria-expanded" in javascript.text


def test_provider_filter_is_forwarded_and_preserved(client, fake_service):
    response = client.get(
        "/providers?availability=requires_payment&cost_tier=paid&q=%20X%20"
    )

    assert response.status_code == 200
    assert fake_service.provider_filters == {
        "availability": "requires_payment",
        "cost_tier": "paid",
        "q": "X",
    }
    assert 'value="requires_payment" selected' in response.text
    assert 'value="paid" selected' in response.text
    assert 'value="X"' in response.text
    for text in ("GitHub", "研究与开发者", "API 密钥", "search", "releases"):
        assert text in response.text


def test_provider_query_is_trimmed_to_one_hundred_characters(client, fake_service):
    response = client.get(f"/providers?q={'x' * 120}")

    assert response.status_code == 200
    assert fake_service.provider_filters["q"] == "x" * 100


def test_target_filter_is_forwarded_and_catalog_columns_render(client, fake_service):
    response = client.get(
        "/targets?provider_id=github&target_type=publisher_feed"
        "&coverage_mode=direct&availability=ready&q=Python"
    )

    assert response.status_code == 200
    assert fake_service.target_filters == {
        "provider_id": "github",
        "target_type": "publisher_feed",
        "coverage_mode": "direct",
        "availability": "ready",
        "q": "Python",
    }
    for text in (
        "OpenAI Python",
        "GitHub",
        "发布方订阅源",
        "发现",
        "直接覆盖",
        "可直接使用",
        "RSS",
        "成功",
    ):
        assert text in response.text


def test_provider_detail_shows_audit_links_env_names_and_probes(client):
    response = client.get("/providers/github")

    assert response.status_code == 200
    for text in ("官方网站", "文档", "服务条款", "GITHUB_TOKEN", "配置只读令牌"):
        assert text in response.text
    assert "能力探测" in response.text
    assert 'target="_blank" rel="noopener noreferrer"' in response.text


def test_target_detail_explains_access_and_risk_without_secrets(client):
    response = client.get("/targets/github-openai-python")

    assert response.status_code == 200
    for text in (
        "首选访问方式",
        "备用访问方式",
        "风险分项",
        "预期字段",
        "最新样本完整度",
        "GITHUB_TOKEN",
    ):
        assert text in response.text
    assert "100%" in response.text
    assert "secret-token-value" not in response.text
    assert "Authorization" not in response.text
    assert "Cookie" not in response.text


def test_target_detail_marks_missing_sample_completeness(client, fake_service):
    fake_service.content_completeness = None

    response = client.get("/targets/github-openai-python")

    assert response.status_code == 200
    assert "最新样本完整度：未记录" in response.text


def test_target_detail_keeps_never_probed_semantics(client, fake_service):
    fake_service.has_content_probes = False

    response = client.get("/targets/github-openai-python")

    assert response.status_code == 200
    assert "尚未探测" in response.text


def test_catalog_tables_are_keyboard_scroll_regions(client):
    for path, label in (("/providers", "Provider 列表"), ("/targets", "Target 列表")):
        response = client.get(path)
        assert response.status_code == 200
        assert 'class="table-scroll"' in response.text
        assert 'tabindex="0"' in response.text
        assert f'aria-label="{label}"' in response.text


def test_unknown_provider_and_target_return_404(client):
    assert client.get("/providers/unknown").status_code == 404
    assert client.get("/targets/unknown").status_code == 404
