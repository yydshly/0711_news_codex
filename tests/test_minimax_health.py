from __future__ import annotations

import httpx
import pytest
from typer.testing import CliRunner

from newsradar.ai.health import check_minimax_config, check_minimax_live
from newsradar.ai.minimax import ModelUsage
from newsradar.cli import app
from newsradar.settings import Settings

runner = CliRunner()


def test_minimax_defaults_use_current_official_models() -> None:
    settings = Settings(_env_file=None)

    assert settings.minimax_deep_model == "MiniMax-M2.7"
    assert settings.minimax_fast_model == "MiniMax-M2.7-highspeed"


def test_config_check_reports_region_without_exposing_key() -> None:
    result = check_minimax_config(
        Settings(
            _env_file=None,
            minimax_api_key="secret-value",
            minimax_base_url="https://api.minimaxi.com",
        )
    )

    assert result.configured is True
    assert result.region == "china"
    assert "secret-value" not in repr(result)


@pytest.mark.asyncio
async def test_live_check_queries_model_and_records_structured_usage() -> None:
    usages: list[ModelUsage] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-value"
        if request.method == "GET":
            assert request.url.path == "/v1/models/MiniMax-M2.7-highspeed"
            return httpx.Response(
                200, json={"id": "MiniMax-M2.7-highspeed"}, request=request
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"topics":["agents"],"confidence":0.9}'}}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
            request=request,
        )

    settings = Settings(
        _env_file=None,
        minimax_api_key="secret-value",
        minimax_base_url="https://api.minimaxi.com",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await check_minimax_live(settings, http, usages.append)

    assert result.model_visible is True
    assert result.structured_outcome == "success"
    assert usages[-1].outcome == "success"
    assert "secret-value" not in repr(result)


def test_check_command_is_configuration_only_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        "newsradar.cli.get_settings",
        lambda: Settings(_env_file=None, minimax_api_key="secret-value"),
    )

    result = runner.invoke(app, ["minimax", "check"])

    assert result.exit_code == 0
    assert "configured=True" in result.stdout
    assert "MiniMax-M2.7" in result.stdout
    assert "secret-value" not in result.stdout
