from __future__ import annotations

import json

import httpx
import pytest

from newsradar.ai.minimax import MiniMaxClient
from newsradar.ingestion.fetchers.credentials import SettingsCredentials
from newsradar.settings import Settings


def response_payload(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


@pytest.mark.asyncio
async def test_classification_uses_fast_model_and_validates_json() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "MiniMax-M2.7-highspeed"
        assert body["tools"] == []
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json=response_payload(
                '{"nature":"first_party","roles":["discovery","evidence"],'
                '"topics":["foundation_models"],"confidence":0.95,"explanation":"Official"}'
            ),
            request=request,
        )

    settings = Settings(minimax_api_key="secret")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await MiniMaxClient(settings, http).classify_source_sample(
            "Vendor News", "Model released", "Official announcement"
        )
    assert result.nature == "first_party"
    assert result.confidence == 0.95


@pytest.mark.asyncio
async def test_invalid_json_gets_one_repair_attempt() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = "not json" if calls == 1 else '{"topics":["agents"],"confidence":0.8}'
        return httpx.Response(200, json=response_payload(content), request=request)

    settings = Settings(minimax_api_key="secret")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await MiniMaxClient(settings, http).infer_source_topics("Agent research")
    assert calls == 2
    assert result.topics == ["agents"]


@pytest.mark.asyncio
async def test_missing_api_key_returns_rule_fallback_without_network() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Network must not be called without an API key")

    settings = Settings(minimax_api_key=None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await MiniMaxClient(settings, http).infer_source_topics(
            "Open source model and developer SDK"
        )
    assert "open_source_models" in result.topics
    assert result.confidence == 0.0


def test_settings_repr_never_contains_api_key() -> None:
    settings = Settings(minimax_api_key="secret-value")
    assert "secret-value" not in repr(settings)


def test_settings_credentials_only_unwraps_requested_secret() -> None:
    settings = Settings(
        reddit_client_id="reddit-id",
        reddit_client_secret="reddit-secret",
        youtube_api_key="youtube-secret",
    )

    credentials = SettingsCredentials(settings)

    assert credentials.require("REDDIT_CLIENT_SECRET") == "reddit-secret"
    assert credentials.configured_names() == {
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "YOUTUBE_API_KEY",
    }
    assert "reddit-secret" not in repr(settings)
