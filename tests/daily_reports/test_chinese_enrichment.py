from __future__ import annotations

import asyncio
import json

import httpx
import pytest

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
            return await DailyReportChineseEnricher(settings, http).enrich_batch((candidate(),))

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


def test_unexpected_model_path_exception_falls_back_only_that_item(monkeypatch) -> None:
    async def broken_structured(*_args, **_kwargs):
        raise RuntimeError("provider response body must not escape")

    monkeypatch.setattr(
        "newsradar.daily_reports.chinese_enrichment.MiniMaxClient.structured",
        broken_structured,
    )

    async def run():
        async with httpx.AsyncClient() as http:
            return await DailyReportChineseEnricher(
                Settings(_env_file=None, minimax_api_key="secret"), http
            ).enrich_batch((candidate(),))

    result = asyncio.run(run())[0]
    assert result.origin == "rule_fallback"
    assert result.error_code == "unexpected_error"
    assert "provider response body" not in repr(result)


def test_outer_deadline_covers_work_after_http_returns(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={}, request=request)

    async def stalls_after_http(self, *args, **kwargs):
        await self.http.post("https://example.test/returned")
        await asyncio.sleep(0.05)
        return kwargs.get("fallback")

    monkeypatch.setattr(
        "newsradar.daily_reports.chinese_enrichment._MAX_ITEM_TIMEOUT_SECONDS", 0.01
    )
    monkeypatch.setattr(
        "newsradar.daily_reports.chinese_enrichment.MiniMaxClient.structured",
        stalls_after_http,
    )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await DailyReportChineseEnricher(
                Settings(_env_file=None, minimax_api_key="secret"), http
            ).enrich_batch((candidate(),))

    result = asyncio.run(run())[0]
    assert requests
    assert result.origin == "rule_fallback"
    assert result.error_code == "timeout"


def test_batch_completes_later_item_after_ordinary_item_exception(monkeypatch) -> None:
    completed: list[int] = []
    original = DailyReportChineseEnricher._enrich_one

    async def sometimes_broken(self, row):
        if row.event_id == 11:
            raise RuntimeError("one item failed")
        completed.append(row.event_id)
        return await original(self, row)

    monkeypatch.setattr(DailyReportChineseEnricher, "_enrich_one", sometimes_broken)

    async def run():
        async with httpx.AsyncClient() as http:
            return await DailyReportChineseEnricher(Settings(_env_file=None), http).enrich_batch(
                (candidate(11), candidate(12))
            )

    results = asyncio.run(run())
    assert completed == [12]
    assert [row.error_code for row in results] == ["unexpected_error", "no_api_key"]


def test_cancellation_propagates_without_becoming_item_fallback(monkeypatch) -> None:
    started = asyncio.Event()

    async def wait_forever(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "newsradar.daily_reports.chinese_enrichment.MiniMaxClient.structured",
        wait_forever,
    )

    async def run() -> None:
        async with httpx.AsyncClient() as http:
            task = asyncio.create_task(
                DailyReportChineseEnricher(
                    Settings(_env_file=None, minimax_api_key="secret"), http
                ).enrich_batch((candidate(),))
            )
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())


@pytest.mark.parametrize("value", [0, -1])
def test_enricher_rejects_non_positive_concurrency(value: int) -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as http:
            with pytest.raises(ValueError, match="event_model_max_concurrency"):
                DailyReportChineseEnricher(
                    Settings(_env_file=None, event_model_max_concurrency=value), http
                )

    asyncio.run(run())


def test_prompt_omits_adversarial_url_like_tokens_but_preserves_prose() -> None:
    row = candidate()
    row.snapshot.update(
        {
            "zh_title": "Useful prose example.com/path remains around the omission",
            "zh_summary": "Keep this sentence; remove www.bad.test/a and //cdn.bad.test/x",
            "publisher_names": [
                "mailto:desk@publisher.test",
                "ftp://192.0.2.3/file",
                "custom+app://host.invalid/secret",
            ],
            "confirmation_summary": "Contact editor@news.test or 203.0.113.4:8080/a",
            "limitations": ["The surrounding non-URL prose must survive."],
        }
    )

    prompt = DailyReportChineseEnricher._prompt(row)

    for leaked in (
        "example.com",
        "www.bad.test",
        "cdn.bad.test",
        "mailto:",
        "publisher.test",
        "ftp://",
        "192.0.2.3",
        "custom+app:",
        "host.invalid",
        "editor@news.test",
        "203.0.113.4",
    ):
        assert leaked not in prompt
    assert "Useful prose" in prompt
    assert "surrounding non-URL prose must survive" in prompt


def test_prompt_omits_complete_ipv6_and_one_character_scheme_tokens() -> None:
    row = candidate()
    row.snapshot.update(
        {
            "zh_title": (
                "Keep alpha https://[2001:db8::1]/secret-path and keep omega"
            ),
            "zh_summary": (
                "Keep beta //[2001:db8::2]/protocol-path plus "
                "x://private-host/one-char-secret and keep gamma"
            ),
            "publisher_names": [
                "Keep delta [2001:db8::3]/bracketed-bare-path",
                "Keep epsilon 2001:db8::4/unbracketed-bare-path",
            ],
            "confirmation_summary": "Ordinary surrounding prose remains intact.",
        }
    )

    prompt = DailyReportChineseEnricher._prompt(row)

    for leaked in (
        "2001:db8",
        "secret-path",
        "protocol-path",
        "x:",
        "private-host",
        "one-char-secret",
        "bracketed-bare-path",
        "unbracketed-bare-path",
    ):
        assert leaked not in prompt
    for prose in ("Keep alpha", "keep omega", "Keep beta", "keep gamma", "Keep delta"):
        assert prose in prompt


@pytest.mark.parametrize(
    ("zh_title", "zh_summary"),
    [
        ("AI launch 新", "This is almost entirely English with only 中文 included."),
        ("人工智慧產品正式發佈", "這項產品採用新模型，並為企業提供更完整的資料處理能力。"),
        (
            "蘋果推出全新電腦",
            "蘋果推出全新電腦，支援人工智能，效能顯著提升，帶來更佳使用經驗。",
        ),
        (
            "軟體開發工具獲得重大更新",
            "這次更新改善網絡連線與資料處理，並為開發團隊帶來更穩定的使用體驗。",
        ),
        ("新しいAI製品を発表", "この製品は企業向けの新しい機能を提供します。"),
        ("新产品", "内容太短"),
        ("新" * 81, "这是符合长度要求且包含充分中文信息的产品发布概述。"),
        ("新产品正式发布", "中" * 801),
    ],
)
def test_invalid_or_non_simplified_model_copy_falls_back(
    monkeypatch, zh_title: str, zh_summary: str
) -> None:
    async def fake_structured(
        self, purpose, model, prompt, response_type, fallback, timeout_seconds=None
    ):
        return response_type(zh_title=zh_title, zh_summary=zh_summary)

    monkeypatch.setattr(
        "newsradar.daily_reports.chinese_enrichment.MiniMaxClient.structured",
        fake_structured,
    )

    async def run():
        async with httpx.AsyncClient() as http:
            return await DailyReportChineseEnricher(
                Settings(_env_file=None, minimax_api_key="secret"), http
            ).enrich_batch((candidate(),))

    result = asyncio.run(run())[0]
    assert result.origin == "rule_fallback"
    assert result.error_code == "non_chinese_output"


@pytest.mark.parametrize(
    ("zh_title", "zh_summary"),
    [
        (
            "OpenAI 发布新一代 AI 模型",
            "OpenAI 今天发布新一代 AI 模型，重点提升推理效率与开发者使用体验。",
        ),
        ("国产 GPU 平台完成升级", "该平台完成软硬件协同升级，并为企业提供更稳定的 AI 推理服务。"),
        (
            "苹果推出全新电脑",
            "苹果推出全新电脑，支持人工智能，性能显著提升，带来更佳使用体验。",
        ),
        (
            "软件开发工具获得重大更新",
            "这次更新改善网络连接与数据处理，并为开发团队带来更稳定的使用体验。",
        ),
    ],
)
def test_meaningful_simplified_chinese_with_ascii_terms_is_accepted(
    monkeypatch, zh_title: str, zh_summary: str
) -> None:
    async def fake_structured(
        self, purpose, model, prompt, response_type, fallback, timeout_seconds=None
    ):
        return response_type(zh_title=zh_title, zh_summary=zh_summary)

    monkeypatch.setattr(
        "newsradar.daily_reports.chinese_enrichment.MiniMaxClient.structured",
        fake_structured,
    )

    async def run():
        async with httpx.AsyncClient() as http:
            return await DailyReportChineseEnricher(
                Settings(_env_file=None, minimax_api_key="secret"), http
            ).enrich_batch((candidate(),))

    result = asyncio.run(run())[0]
    assert result.origin == "model"
    assert result.copy.zh_title == zh_title


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
