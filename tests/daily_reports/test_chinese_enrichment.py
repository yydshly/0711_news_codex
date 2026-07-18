from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from newsradar.daily_reports.chinese_enrichment import (
    _MAX_CONTEXT,
    DailyReportChineseCandidate,
    DailyReportChineseEnricher,
    _safe_context,
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
                                        "review_recommendation": (
                                            "建议继续跟踪正式上线后的影响与后续公开材料。"
                                        ),
                                        "evidence_assessment": (
                                            "现有公开材料可支持当前产品发布信息，仍应关注后续更新。"
                                        ),
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
                                        "review_recommendation": (
                                            "建议继续核对公开材料并补充独立来源。"
                                        ),
                                        "evidence_assessment": (
                                            "当前证据仍需结合后续公开信息进一步确认。"
                                        ),
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
    assert [row.origin for row in results] == ["model_partial", "model_partial"]
    assert all(row.error_code == "zh_title_non_chinese_output" for row in results)
    assert all(
        row.field_errors
        == ("zh_title_non_chinese_output", "zh_summary_non_chinese_output")
        for row in results
    )
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


def test_rule_fallback_explains_distinct_evidence_gaps() -> None:
    only_discovery = candidate(201)
    only_discovery.snapshot["confirmation_summary"] = "仅有发现型媒体报道，尚未找到官方公告。"
    only_discovery.snapshot["limitations"] = ["缺少官方一手发布。"]

    missing_second_root = candidate(202)
    missing_second_root.snapshot["confirmation_summary"] = "已有官方发布，但只有一个独立证据根。"
    missing_second_root.snapshot["limitations"] = ["仍需第二个独立公开来源确认。"]

    async def run():
        async with httpx.AsyncClient() as http:
            return await DailyReportChineseEnricher(
                Settings(_env_file=None), http
            ).enrich_batch((only_discovery, missing_second_root))

    first, second = asyncio.run(run())

    assert first.origin == second.origin == "rule_fallback"
    assert first.copy.review_recommendation != second.copy.review_recommendation
    assert first.copy.evidence_assessment != second.copy.evidence_assessment


def test_model_copy_is_converted_to_simplified_chinese_before_validation(
    monkeypatch,
) -> None:
    async def fake_structured(
        self, purpose, model, prompt, response_type, fallback, timeout_seconds=None
    ):
        return response_type(
            zh_title="產品正式發佈",
            zh_summary="官方材料顯示，這項產品已經正式發佈並提供完整說明。",
            review_recommendation="建議繼續追蹤正式上線後的影響與公開材料。",
            evidence_assessment="現有公開材料可以支持目前的產品發佈資訊。",
        )

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
    assert result.error_code is None
    assert result.copy.zh_title == "产品正式发布"
    assert "建议继续追踪" in result.copy.review_recommendation


def test_invalid_model_field_falls_back_without_discarding_valid_fields(
    monkeypatch,
) -> None:
    async def fake_structured(
        self, purpose, model, prompt, response_type, fallback, timeout_seconds=None
    ):
        return response_type(
            zh_title="产品正式发布",
            zh_summary="官方材料显示，该产品已经正式发布并提供完整说明。",
            review_recommendation="Review this later",
            evidence_assessment="现有公开材料可支持当前产品发布信息。",
        )

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

    assert result.origin == "model_partial"
    assert result.error_code == "review_recommendation_non_chinese_output"
    assert result.field_errors == ("review_recommendation_non_chinese_output",)
    assert result.copy.zh_title == "产品正式发布"
    assert result.copy.zh_summary == "官方材料显示，该产品已经正式发布并提供完整说明。"
    assert result.copy.review_recommendation != "Review this later"
    assert result.copy.evidence_assessment == "现有公开材料可支持当前产品发布信息。"


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
                "x://private-host/a,secret-fragment and keep gamma"
            ),
            "publisher_names": [
                "Keep delta [2001:db8::3]/bracketed-bare-path",
                "Keep epsilon 2001:db8::4/unbracketed-bare-path",
            ],
            "confirmation_summary": (
                "Remove ::1/private-fragment and "
                "::ffff:192.0.2.128/mapped-ipv6-path"
            ),
            "limitations": ["Ordinary surrounding prose remains intact."],
        }
    )

    prompt = DailyReportChineseEnricher._prompt(row)

    for leaked in (
        "2001:db8",
        "secret-path",
        "protocol-path",
        "x:",
        "private-host",
        "secret-fragment",
        "bracketed-bare-path",
        "unbracketed-bare-path",
        "private-fragment",
        "ffff:192.0.2.128",
        "mapped-ipv6-path",
    ):
        assert leaked not in prompt
    assert "Ordinary surrounding prose remains intact" in prompt
    assert '"event_key": "11:2"' in prompt


@pytest.mark.parametrize(
    "prose",
    [
        "Release note: ordinary prose with a non-URL colon remains.",
        "模型版本 M2.7 已完成更新，普通文本应当保留。",
    ],
)
def test_safe_context_preserves_clean_non_url_prose(prose: str) -> None:
    row = candidate()
    row.snapshot.update(
        {
            "zh_title": prose,
            "zh_summary": "Clean ordinary summary without network locations.",
            "publisher_names": ["Clean Publisher"],
            "confirmation_summary": "Clean confirmation prose.",
            "limitations": ["Clean limitation prose."],
        }
    )

    assert prose in DailyReportChineseEnricher._prompt(row)


@pytest.mark.parametrize(
    "contaminated",
    [
        "https://[2001:db8::1]/secret",
        "//[2001:db8::2]/path",
        "x://private-host/a,secret-fragment",
        "[2001:db8::3]/bare-path",
        "2001:db8::4/bare-path",
        "::1/private-fragment",
        "::ffff:192.0.2.128/path",
        "www.example.test/path",
        "example.test/path",
        "mailto:desk@example.test",
        "desk@example.test",
        "192.0.2.5/private-path",
    ],
)
def test_safe_context_omits_entire_url_contaminated_fragment(
    contaminated: str,
) -> None:
    assert _safe_context(f"ordinary prefix {contaminated} ordinary suffix") == "[omitted]"


def test_safe_context_detects_domain_crossing_prompt_truncation_boundary() -> None:
    value = "a" * (_MAX_CONTEXT - 9) + " secret.example.com/private"

    assert value[:_MAX_CONTEXT].endswith("secret.e")
    assert _safe_context(value) == "[omitted]"


def test_safe_context_detects_uri_starting_at_prompt_truncation_boundary() -> None:
    value = "a" * (_MAX_CONTEXT - 2) + " x://private-host/secret"

    assert value[:_MAX_CONTEXT].endswith(" x")
    assert _safe_context(value) == "[omitted]"


def test_safe_context_truncates_clean_overlong_field_after_inspection() -> None:
    value = "普通文本" * ((_MAX_CONTEXT // 4) + 100)

    assert len(value) > _MAX_CONTEXT
    assert _safe_context(value) == value[:_MAX_CONTEXT]


def test_safe_context_fails_closed_above_absolute_inspection_cap() -> None:
    value = "a" * 16_001

    assert _safe_context(value) == "[omitted]"


@pytest.mark.parametrize(
    ("zh_title", "zh_summary", "expected_error"),
    [
        (
            "AI launch 新",
            "This is almost entirely English with only 中文 included.",
            "zh_title_non_chinese_output",
        ),
        (
            "新しいAI製品を発表",
            "この製品は企業向けの新しい機能を提供します。",
            "zh_title_non_chinese_output",
        ),
        ("新产品", "内容太短", "zh_title_non_chinese_output"),
        (
            "新" * 81,
            "这是符合长度要求且包含充分中文信息的产品发布概述。",
            "zh_title_non_chinese_output",
        ),
        ("新产品正式发布", "中" * 801, "zh_summary_non_chinese_output"),
    ],
)
def test_invalid_model_fields_fall_back_independently(
    monkeypatch, zh_title: str, zh_summary: str, expected_error: str
) -> None:
    async def fake_structured(
        self, purpose, model, prompt, response_type, fallback, timeout_seconds=None
    ):
        return response_type(
            zh_title=zh_title,
            zh_summary=zh_summary,
            review_recommendation="建议继续核对公开材料并补充独立来源。",
            evidence_assessment="当前证据仍需结合后续公开信息进一步确认。",
        )

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
    assert result.origin == "model_partial"
    assert result.error_code == expected_error
    assert expected_error in result.field_errors


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
        return response_type(
            zh_title=zh_title,
            zh_summary=zh_summary,
            review_recommendation="建议继续核对公开材料并补充独立来源。",
            evidence_assessment="当前证据仍需结合后续公开信息进一步确认。",
        )

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
