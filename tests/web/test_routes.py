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


class FakePostgresError(Exception):
    def __init__(self, message: str, sqlstate: str | None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


@contextmanager
def fake_service_context() -> Iterator[FakeDashboardService]:
    yield FakeDashboardService()


@pytest.fixture
def client() -> Iterator[TestClient]:
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


def _response_for_database_error(error: Exception):
    @contextmanager
    def failing_context() -> Iterator[FakeDashboardService]:
        raise error
        yield FakeDashboardService()

    with TestClient(create_app(lambda: failing_context())) as test_client:
        return test_client.get("/")


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


def test_static_shell_assets_preserve_accessible_navigation(client: TestClient):
    css = client.get("/static/styles.css")
    javascript = client.get("/static/app.js")

    assert css.status_code == 200
    assert javascript.status_code == 200
    assert ":focus-visible" in css.text
    assert "@media (max-width: 760px)" in css.text
    assert "aria-expanded" in javascript.text
