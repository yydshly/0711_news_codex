from __future__ import annotations

import asyncio
import json

import httpx

from newsradar.daily_reports.chinese_enrichment import (
    DailyReportChineseCandidate,
    DailyReportChineseEnricher,
    candidate_key,
)
from newsradar.settings import Settings


def candidate(event_id: int = 11) -> DailyReportChineseCandidate:
    return DailyReportChineseCandidate(
        event_id=event_id,
        event_version_number=2,
        snapshot={
            "zh_title": "English source title",
            "zh_summary": "Original material says the product was released.",
            "publisher_names": ["Official publisher"],
            "confirmation_summary": "Only one public evidence item is currently available.",
            "limitations": ["A second independent evidence item is still needed."],
            "evidence": [{"title": "Evidence", "url": "https://example.com/secret-path"}],
        },
        decision_item_id=7,
        overview_item_id=9,
    )


def test_candidate_key_is_version_specific() -> None:
    assert candidate_key(11, 2) == "11:2"
    assert candidate_key(11, 3) == "11:3"


def test_enricher_returns_valid_chinese_without_sending_urls() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "zh_title": "产品正式发布",
                                    "zh_summary": "官方材料显示，该产品已经正式发布。",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 42},
            },
            request=request,
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await DailyReportChineseEnricher(
                Settings(_env_file=None, minimax_api_key="secret"), http
            ).enrich_batch((candidate(),))

    result = asyncio.run(run())[0]
    assert result.origin == "model"
    assert result.copy.zh_title == "产品正式发布"
    assert result.error_code is None
    assert len(result.usages) == 1
    assert result.usages[0].outcome == "success"
    assert "https://example.com" not in requests[0].content.decode("utf-8")


def test_non_chinese_model_output_falls_back_only_that_item() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "zh_title": "English only",
                                    "zh_summary": "Still English only",
                                }
                            )
                        }
                    }
                ]
            },
            request=request,
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await DailyReportChineseEnricher(
                Settings(_env_file=None, minimax_api_key="secret"), http
            ).enrich_batch((candidate(11), candidate(12)))

    results = asyncio.run(run())
    assert [row.origin for row in results] == ["rule_fallback", "rule_fallback"]
    assert all(row.error_code == "non_chinese_output" for row in results)
    assert results[0].copy.zh_title == "English source title"


def test_missing_key_never_calls_http_and_records_no_api_key() -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP must not be called without a MiniMax key")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
            return await DailyReportChineseEnricher(Settings(_env_file=None), http).enrich_batch(
                (candidate(),)
            )

    result = asyncio.run(run())[0]
    assert result.origin == "rule_fallback"
    assert result.error_code == "no_api_key"


def test_timeout_falls_back_with_safe_code() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={}, request=request)

    async def run():
        settings = Settings(
            _env_file=None,
            minimax_api_key="secret",
            event_model_timeout_seconds=0.01,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await DailyReportChineseEnricher(settings, http).enrich_batch(
                (candidate(),)
            )

    result = asyncio.run(run())[0]
    assert result.origin == "rule_fallback"
    assert result.error_code == "timeout"


def test_enricher_caps_total_item_timeout_at_forty_five_seconds(monkeypatch) -> None:
    timeouts: list[float | None] = []

    async def fake_structured(
        self,
        purpose,
        model,
        prompt,
        response_type,
        fallback,
        timeout_seconds=None,
    ):
        timeouts.append(timeout_seconds)
        return fallback

    monkeypatch.setattr(
        "newsradar.daily_reports.chinese_enrichment.MiniMaxClient.structured",
        fake_structured,
    )

    async def run():
        settings = Settings(
            _env_file=None,
            minimax_api_key="secret",
            event_model_timeout_seconds=90,
        )
        async with httpx.AsyncClient() as http:
            return await DailyReportChineseEnricher(settings, http).enrich_batch((candidate(),))

    asyncio.run(run())
    assert timeouts == [45]


def test_batch_never_exceeds_two_concurrent_items(monkeypatch) -> None:
    active = 0
    maximum = 0

    async def fake_one(self, row):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return row

    monkeypatch.setattr(DailyReportChineseEnricher, "_enrich_one", fake_one)

    async def run():
        async with httpx.AsyncClient() as http:
            return await DailyReportChineseEnricher(
                Settings(
                    _env_file=None,
                    minimax_api_key="secret",
                    event_model_max_concurrency=9,
                ),
                http,
            ).enrich_batch((candidate(11), candidate(12), candidate(13)))

    assert len(asyncio.run(run())) == 3
    assert maximum == 2
