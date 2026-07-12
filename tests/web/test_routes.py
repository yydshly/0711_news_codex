from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, ProgrammingError

from newsradar.web import create_app
from newsradar.web.viewmodels import DashboardSummary


class FakeDashboardService:
    def summary(self) -> DashboardSummary:
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


@contextmanager
def fake_service_context() -> Iterator[FakeDashboardService]:
    yield FakeDashboardService()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(lambda: fake_service_context())) as test_client:
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


def test_security_headers_are_present(client: TestClient):
    response = client.get("/")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_unknown_route_is_chinese_404(client: TestClient):
    response = client.get("/missing")

    assert response.status_code == 404
    assert "页面不存在" in response.text


@pytest.mark.parametrize(
    ("error", "command"),
    [
        (
            OperationalError("connection has password=do-not-leak", {}, Exception("secret")),
            "uv run newsradar db start",
        ),
        (
            ProgrammingError("missing table api_key=do-not-leak", {}, Exception("secret")),
            "uv run alembic upgrade head",
        ),
    ],
)
def test_database_failures_render_safe_commands(error: Exception, command: str):
    @contextmanager
    def failing_context() -> Iterator[FakeDashboardService]:
        raise error
        yield FakeDashboardService()

    with TestClient(create_app(lambda: failing_context())) as test_client:
        response = test_client.get("/")

    assert response.status_code == 503
    assert command in response.text
    assert "do-not-leak" not in response.text
    assert "Traceback" not in response.text


def test_static_shell_assets_preserve_accessible_navigation(client: TestClient):
    css = client.get("/static/styles.css")
    javascript = client.get("/static/app.js")

    assert css.status_code == 200
    assert javascript.status_code == 200
    assert ":focus-visible" in css.text
    assert "@media (max-width: 760px)" in css.text
    assert "aria-expanded" in javascript.text
