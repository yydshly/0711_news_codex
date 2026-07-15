from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from newsradar.ai.minimax import MiniMaxClient, ModelUsage, fallback_topics
from newsradar.ingestion.fetchers.credentials import SettingsCredentials
from newsradar.settings import Settings


def response_payload(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def usage_errors(captured: list[ModelUsage]) -> list[tuple[str, str | None]]:
    return [(usage.outcome, usage.error) for usage in captured]


@pytest.mark.asyncio
async def test_classification_uses_current_chat_api_and_validates_json() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert body["model"] == "MiniMax-M2.7-highspeed"
        assert body["reasoning_split"] is True
        assert body["max_completion_tokens"] == 4096
        assert body["temperature"] == 1.0
        assert "response_format" not in body
        assert "tools" not in body
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
async def test_provider_business_error_falls_back_without_repair() -> None:
    captured: list[ModelUsage] = []
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = response_payload('{"topics":["agents"],"confidence":0.8}')
        payload["base_resp"] = {"status_code": 1004, "status_msg": "do not persist"}
        return httpx.Response(200, json=payload, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        fallback = fallback_topics("agents")
        result = await MiniMaxClient(
            Settings(minimax_api_key="secret"), http, captured.append
        ).structured("purpose", "model", "prompt", type(fallback), fallback)

    assert result is fallback
    assert calls == 1
    assert usage_errors(captured) == [("fallback", "provider_business_error")]


@pytest.mark.asyncio
async def test_truncated_completion_falls_back_without_repair() -> None:
    captured: list[ModelUsage] = []
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = response_payload('{"topics":["agents"],"confidence":0.8}')
        payload["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=payload, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        fallback = fallback_topics("agents")
        result = await MiniMaxClient(
            Settings(minimax_api_key="secret"), http, captured.append
        ).structured("purpose", "model", "prompt", type(fallback), fallback)

    assert result is fallback
    assert calls == 1
    assert usage_errors(captured) == [("fallback", "completion_truncated")]


@pytest.mark.asyncio
async def test_invalid_response_shape_falls_back_without_repair() -> None:
    captured: list[ModelUsage] = []
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"choices": []}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        fallback = fallback_topics("agents")
        result = await MiniMaxClient(
            Settings(minimax_api_key="secret"), http, captured.append
        ).structured("purpose", "model", "prompt", type(fallback), fallback)

    assert result is fallback
    assert calls == 1
    assert usage_errors(captured) == [("fallback", "response_shape_invalid")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [(400, "http_400"), (401, "http_401"), (403, "http_403")],
)
async def test_actionable_http_status_codes_are_preserved_safely(
    status_code: int, expected_error: str
) -> None:
    captured: list[ModelUsage] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        fallback = fallback_topics("agents")
        result = await MiniMaxClient(
            Settings(minimax_api_key="secret"), http, captured.append
        ).structured("purpose", "model", "prompt", type(fallback), fallback)

    assert result is fallback
    assert usage_errors(captured) == [("fallback", expected_error)]


@pytest.mark.asyncio
async def test_json_syntax_error_is_classified_and_repaired_once() -> None:
    captured: list[ModelUsage] = []
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = "not json" if calls == 1 else '{"topics":["agents"],"confidence":0.8}'
        return httpx.Response(200, json=response_payload(content), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await MiniMaxClient(
            Settings(minimax_api_key="secret"), http, captured.append
        ).infer_source_topics("Agent research")

    assert result.confidence == 0.8
    assert calls == 2
    assert usage_errors(captured) == [("retry", "json_syntax_invalid"), ("success", None)]


@pytest.mark.asyncio
async def test_schema_validation_error_is_classified_and_repaired_once() -> None:
    captured: list[ModelUsage] = []
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = (
            '{"topics":["agents"],"confidence":2}'
            if calls == 1
            else '{"topics":["agents"],"confidence":0.8}'
        )
        return httpx.Response(200, json=response_payload(content), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await MiniMaxClient(
            Settings(minimax_api_key="secret"), http, captured.append
        ).infer_source_topics("Agent research")

    assert result.confidence == 0.8
    assert calls == 2
    assert usage_errors(captured) == [
        ("retry", "schema_validation_failed"),
        ("success", None),
    ]


@pytest.mark.asyncio
async def test_legacy_think_block_is_removed_before_json_validation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=response_payload(
                '<think>private reasoning</think>\n{"topics":["agents"],"confidence":0.8}'
            ),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await MiniMaxClient(
            Settings(minimax_api_key="secret"), http
        ).infer_source_topics("Agent research")

    assert result.confidence == 0.8


@pytest.mark.asyncio
async def test_repair_attempt_receives_only_remaining_total_timeout_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 10.0}
    calls = 0

    monkeypatch.setattr(
        "newsradar.ai.minimax.time.perf_counter", lambda: clock["now"]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            clock["now"] += 0.09
            return httpx.Response(200, json=response_payload("not json"), request=request)
        timeout = request.extensions["timeout"]
        assert 0 < timeout["read"] <= 0.011
        return httpx.Response(
            200,
            json=response_payload('{"topics":["agents"],"confidence":0.8}'),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await MiniMaxClient(Settings(minimax_api_key="secret"), http).structured(
            "event_enrichment",
            "model",
            "prompt",
            type(fallback_topics("agents")),
            fallback_topics("agents"),
            timeout_seconds=0.1,
        )

    assert calls == 2
    assert result.confidence == 0.8


@pytest.mark.asyncio
async def test_expired_total_timeout_skips_repair_and_records_timeout_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 10.0}
    captured: list[ModelUsage] = []
    calls = 0

    monkeypatch.setattr(
        "newsradar.ai.minimax.time.perf_counter", lambda: clock["now"]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        clock["now"] += 0.11
        return httpx.Response(200, json=response_payload("not json"), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        fallback = fallback_topics("agents")
        result = await MiniMaxClient(
            Settings(minimax_api_key="secret"), http, captured.append
        ).structured(
            "event_enrichment",
            "model",
            "prompt",
            type(fallback),
            fallback,
            timeout_seconds=0.1,
        )

    assert result is fallback
    assert calls == 1
    assert [(usage.outcome, usage.error) for usage in captured] == [
        ("retry", "json_syntax_invalid"),
        ("fallback", "timeout"),
    ]


@pytest.mark.asyncio
async def test_total_timeout_cancels_slow_valid_transport_before_success() -> None:
    captured: list[ModelUsage] = []
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return httpx.Response(
            200,
            json=response_payload('{"topics":["agents"],"confidence":0.8}'),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        fallback = fallback_topics("agents")
        started = time.perf_counter()
        result = await MiniMaxClient(
            Settings(minimax_api_key="secret"), http, captured.append
        ).structured(
            "event_enrichment",
            "model",
            "prompt",
            type(fallback),
            fallback,
            timeout_seconds=0.01,
        )
        elapsed = time.perf_counter() - started

    assert result is fallback
    assert elapsed < 0.04
    assert calls == 1
    assert [(usage.outcome, usage.error) for usage in captured] == [
        ("fallback", "timeout")
    ]


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


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ['{"topics":["agents"],"confidence":0.8}', "not json"])
async def test_model_usage_sink_failure_does_not_block_model_or_fallback(content: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload(content), request=request)

    def failing_sink(_: ModelUsage) -> None:
        raise RuntimeError("sink failed: Bearer secret")

    settings = Settings(minimax_api_key="secret")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await MiniMaxClient(settings, http, failing_sink).infer_source_topics(
            "Agent research"
        )

    assert result.confidence in {0.0, 0.8}


@pytest.mark.asyncio
async def test_malformed_prompt_token_count_keeps_success_usage_audit() -> None:
    captured: list[ModelUsage] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = response_payload('{"topics":["agents"],"confidence":0.8}')
        payload["usage"]["prompt_tokens"] = "bad"
        return httpx.Response(200, json=payload, request=request)

    settings = Settings(minimax_api_key="secret")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await MiniMaxClient(settings, http, captured.append).infer_source_topics(
            "Agent research"
        )

    assert result.confidence == 0.8
    assert len(captured) == 1
    assert captured[0].outcome == "success"
    assert captured[0].input_tokens == 0
    assert captured[0].output_tokens == 5


@pytest.mark.parametrize("token_count", [-1, float("nan"), 10**100])
def test_untrusted_token_counts_are_nonnegative_and_bounded(token_count: object) -> None:
    captured: list[ModelUsage] = []
    client = MiniMaxClient(Settings(), httpx.AsyncClient(), usage_sink=captured.append)

    client._record_usage(
        "event_enrichment",
        "model",
        {"usage": {"prompt_tokens": token_count, "completion_tokens": token_count}},
        0.0,
        "success",
    )

    assert captured[0].input_tokens == 0
    assert captured[0].output_tokens == 0


def test_settings_repr_never_contains_api_key() -> None:
    settings = Settings(minimax_api_key="secret-value")
    assert "secret-value" not in repr(settings)


def test_event_model_settings_have_safe_operational_defaults() -> None:
    settings = Settings()

    assert settings.event_window_hours == 24
    assert settings.event_candidate_window_hours == 48
    assert settings.event_model_timeout_seconds == 45
    assert settings.event_model_max_concurrency == 2
    assert settings.event_top_limit == 20


def test_model_usage_redacts_error_before_persistence() -> None:
    captured: list[ModelUsage] = []
    settings = Settings(minimax_api_key="secret-value")

    client = MiniMaxClient(settings, httpx.AsyncClient(), usage_sink=captured.append)
    client._record_usage(
        "event_enrichment",
        settings.minimax_fast_model,
        {},
        0.0,
        "fallback",
        "Authorization: Bearer secret-value",
    )

    assert captured[0].error == "Authorization: [REDACTED]"


def test_settings_credentials_only_unwraps_requested_secret() -> None:
    settings = Settings(
        reddit_client_id="reddit-id",
        reddit_client_secret="reddit-secret",
        youtube_api_key="youtube-secret",
        github_token=None,
    )

    credentials = SettingsCredentials(settings)

    assert credentials.require("REDDIT_CLIENT_SECRET") == "reddit-secret"
    assert credentials.configured_names() == {
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "YOUTUBE_API_KEY",
    }
    assert "reddit-secret" not in repr(settings)
