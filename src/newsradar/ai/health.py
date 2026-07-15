from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Literal
from urllib.parse import urlsplit

import httpx

from newsradar.ai.minimax import MiniMaxClient, ModelUsage, UsageSink
from newsradar.settings import Settings


@dataclass(frozen=True, slots=True)
class MiniMaxConfigView:
    configured: bool
    region: Literal["china", "international", "custom"]
    fast_model: str
    deep_model: str


@dataclass(frozen=True, slots=True)
class MiniMaxLiveCheck:
    config: MiniMaxConfigView
    model_visible: bool
    model_http_status: int | None
    structured_outcome: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    error_code: str | None = None


def check_minimax_config(settings: Settings) -> MiniMaxConfigView:
    host = urlsplit(settings.minimax_base_url).hostname
    region: Literal["china", "international", "custom"] = (
        "china"
        if host == "api.minimaxi.com"
        else "international"
        if host == "api.minimax.io"
        else "custom"
    )
    return MiniMaxConfigView(
        configured=settings.minimax_api_key is not None,
        region=region,
        fast_model=settings.minimax_fast_model,
        deep_model=settings.minimax_deep_model,
    )


async def check_minimax_live(
    settings: Settings,
    http: httpx.AsyncClient,
    usage_sink: UsageSink | None = None,
) -> MiniMaxLiveCheck:
    """Perform a bounded, secret-free MiniMax runtime verification."""
    config = check_minimax_config(settings)
    if not settings.minimax_api_key:
        return MiniMaxLiveCheck(
            config=config,
            model_visible=False,
            model_http_status=None,
            structured_outcome="not_configured",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0.0,
            error_code="no_api_key",
        )

    started = perf_counter()
    try:
        response = await http.get(
            f"{settings.minimax_base_url.rstrip('/')}/v1/models/{settings.minimax_fast_model}",
            headers={"Authorization": f"Bearer {settings.minimax_api_key.get_secret_value()}"},
            timeout=settings.event_model_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return _live_failure(config, exc.response.status_code, _http_error_code(exc))
    except (httpx.TimeoutException, TimeoutError):
        return _live_failure(config, None, "timeout")
    except httpx.HTTPError:
        return _live_failure(config, None, "transport_error")

    usages: list[ModelUsage] = []

    def collect(usage: ModelUsage) -> None:
        usages.append(usage)
        if usage_sink is not None:
            usage_sink(usage)

    await MiniMaxClient(settings, http, collect).infer_source_topics("AI agent SDK release")
    usage = usages[-1] if usages else None
    return MiniMaxLiveCheck(
        config=config,
        model_visible=True,
        model_http_status=response.status_code,
        structured_outcome=usage.outcome if usage is not None else "fallback",
        input_tokens=usage.input_tokens if usage is not None else 0,
        output_tokens=usage.output_tokens if usage is not None else 0,
        latency_ms=usage.latency_ms if usage is not None else (perf_counter() - started) * 1000,
        error_code=usage.error if usage is not None else "transport_error",
    )


def _live_failure(
    config: MiniMaxConfigView, status: int | None, error_code: str
) -> MiniMaxLiveCheck:
    return MiniMaxLiveCheck(
        config=config,
        model_visible=False,
        model_http_status=status,
        structured_outcome="not_run",
        input_tokens=0,
        output_tokens=0,
        latency_ms=0.0,
        error_code=error_code,
    )


def _http_error_code(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    if status == 429:
        return "http_429"
    if 500 <= status <= 599:
        return "http_5xx"
    if status in {400, 401, 403}:
        return f"http_{status}"
    return "http_4xx"
