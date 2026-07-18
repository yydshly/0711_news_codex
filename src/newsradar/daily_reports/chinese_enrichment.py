from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace

import httpx
from pydantic import BaseModel, ConfigDict, field_validator
from zhconv import convert as convert_chinese

from newsradar.ai.minimax import (
    SAFE_MODEL_ERROR_CODES,
    UNTRUSTED_PREAMBLE,
    MiniMaxClient,
    ModelUsage,
)
from newsradar.settings import Settings

_CJK = re.compile(r"[\u3400-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
_URL_LIKE = re.compile(
    r"""
    (?<![\w])(?:[a-z][a-z0-9+.-]*:(?://)?|//)[^\s"'<> ,}]+
    |(?<![\w])\[[0-9a-f:.]*:[0-9a-f:.]*\](?::\d{1,5})?(?:/[^\s"'<> ,}]*)?
    |(?<![\w:])(?=[0-9a-f:]*:[0-9a-f:]*:)[0-9a-f]+(?::[0-9a-f]*){2,}(?:/[^\s"'<> ,}]*)?
    |(?<![\w])www\.[^\s"'<> ,}]+
    |(?<![\w.+-])[\w.+-]+@(?:[a-z0-9-]+\.)+[a-z]{2,63}
    |\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?:/[^\s"'<>()[\]{},]*)?
    |\b(?:[a-z0-9-]+\.)+[a-z]{2,63}(?::\d{1,5})?(?:/[^\s"'<>()[\]{},]*)?
    """,
    re.IGNORECASE | re.VERBOSE,
)
_MAX_CONTEXT = 1200
_MAX_ITEM_TIMEOUT_SECONDS = 45
_MIN_TITLE_LENGTH = 4
_MAX_TITLE_LENGTH = 80
_MIN_SUMMARY_LENGTH = 12
_MAX_SUMMARY_LENGTH = 800

DAILY_CHINESE_ERROR_LABELS = {
    "budget_limit": "本期安全上限",
    "completion_truncated": "模型返回内容不完整",
    "http_400": "模型请求无效",
    "http_401": "凭据无效",
    "http_403": "缺少文本模型权限",
    "http_429": "请求频率受限",
    "http_4xx": "模型请求被拒绝",
    "http_5xx": "模型服务异常",
    "json_syntax_invalid": "返回内容不是有效 JSON",
    "no_api_key": "未配置文本模型",
    "non_chinese_output": "返回内容不是有效简体中文",
    "provider_business_error": "模型服务拒绝请求",
    "response_shape_invalid": "返回数据形状无效",
    "schema_validation_failed": "返回结构无效",
    "timeout": "请求超时",
    "transport_error": "网络连接异常",
    "unexpected_error": "内部异常",
}
DAILY_CHINESE_SAFE_ERROR_CODES = frozenset(DAILY_CHINESE_ERROR_LABELS)

assert SAFE_MODEL_ERROR_CODES <= DAILY_CHINESE_SAFE_ERROR_CODES


def candidate_key(event_id: int, event_version_number: int) -> str:
    return f"{event_id}:{event_version_number}"


class _ChineseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zh_title: str
    zh_summary: str

    @field_validator("zh_title", "zh_summary")
    @classmethod
    def validate_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("empty_chinese_copy")
        return cleaned


@dataclass(frozen=True, slots=True)
class DailyReportChineseCopy:
    zh_title: str
    zh_summary: str


@dataclass(frozen=True, slots=True)
class DailyReportChineseCandidate:
    event_id: int
    event_version_number: int
    snapshot: dict[str, object]
    decision_item_id: int | None
    overview_item_id: int | None

    @property
    def key(self) -> str:
        return candidate_key(self.event_id, self.event_version_number)


@dataclass(frozen=True, slots=True)
class DailyReportChineseResult:
    candidate: DailyReportChineseCandidate
    copy: DailyReportChineseCopy
    origin: str
    error_code: str | None
    model: str
    usages: tuple[ModelUsage, ...]


class DailyReportChineseEnricher:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        if settings.event_model_max_concurrency <= 0:
            raise ValueError("event_model_max_concurrency must be positive")
        self.settings = settings
        self.http = http
        self._semaphore = asyncio.Semaphore(min(settings.event_model_max_concurrency, 2))

    async def enrich_batch(
        self,
        candidates: tuple[DailyReportChineseCandidate, ...],
        checkpoint: Callable[[str], None] | None = None,
    ) -> tuple[DailyReportChineseResult, ...]:
        async def run_one(row: DailyReportChineseCandidate) -> DailyReportChineseResult:
            async with self._semaphore:
                if checkpoint is not None:
                    checkpoint("daily_autopilot:before_chinese_enrichment_item")
                try:
                    return await self._enrich_one(row)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return self._fallback_result(row, "unexpected_error", [])

        return tuple(await asyncio.gather(*(run_one(row) for row in candidates)))

    async def _enrich_one(
        self, candidate: DailyReportChineseCandidate
    ) -> DailyReportChineseResult:
        usages: list[ModelUsage] = []
        try:
            async with asyncio.timeout(_MAX_ITEM_TIMEOUT_SECONDS):
                return await self._enrich_model_path(candidate, usages)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return self._fallback_result(candidate, "timeout", usages)
        except Exception:
            return self._fallback_result(candidate, "unexpected_error", usages)

    async def _enrich_model_path(
        self,
        candidate: DailyReportChineseCandidate,
        usages: list[ModelUsage],
    ) -> DailyReportChineseResult:
        fallback = _ChineseResponse(
            zh_title="中文增强暂不可用",
            zh_summary="本条内容暂时使用固定快照回退。",
        )
        result = await MiniMaxClient(self.settings, self.http, usages.append).structured(
            "daily_report_chinese_enrichment",
            self.settings.minimax_fast_model,
            self._prompt(candidate),
            _ChineseResponse,
            fallback,
            timeout_seconds=min(
                self.settings.event_model_timeout_seconds,
                _MAX_ITEM_TIMEOUT_SECONDS,
            ),
        )
        snapshot_copy = DailyReportChineseCopy(
            zh_title=_snapshot_text(candidate.snapshot, "zh_title", "未命名事件"),
            zh_summary=_snapshot_text(
                candidate.snapshot,
                "zh_summary",
                "当前公开材料不足以形成完整中文概述。",
            ),
        )
        if result is fallback:
            return self._fallback_result(
                candidate,
                usages[-1].error if usages else "unexpected_error",
                usages,
                snapshot_copy=snapshot_copy,
            )
        if not _is_meaningful_simplified_chinese(result):
            return self._fallback_result(
                candidate,
                "non_chinese_output",
                usages,
                snapshot_copy=snapshot_copy,
            )
        return DailyReportChineseResult(
            candidate=candidate,
            copy=DailyReportChineseCopy(
                zh_title=result.zh_title,
                zh_summary=result.zh_summary,
            ),
            origin="model",
            error_code=None,
            model=self.settings.minimax_fast_model,
            usages=tuple(usages),
        )

    def _fallback_result(
        self,
        candidate: DailyReportChineseCandidate,
        error_code: object,
        usages: list[ModelUsage],
        *,
        snapshot_copy: DailyReportChineseCopy | None = None,
    ) -> DailyReportChineseResult:
        safe_error = (
            error_code
            if isinstance(error_code, str)
            and error_code in DAILY_CHINESE_SAFE_ERROR_CODES
            else "unexpected_error"
        )
        if usages:
            usages[-1] = replace(usages[-1], outcome="fallback", error=safe_error)
        else:
            usages.append(
                ModelUsage(
                    purpose="daily_report_chinese_enrichment",
                    model=self.settings.minimax_fast_model,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0,
                    outcome="fallback",
                    error=safe_error,
                )
            )
        copy = snapshot_copy or DailyReportChineseCopy(
            zh_title=_snapshot_text(candidate.snapshot, "zh_title", "未命名事件"),
            zh_summary=_snapshot_text(
                candidate.snapshot,
                "zh_summary",
                "当前公开材料不足以形成完整中文概述。",
            ),
        )
        return DailyReportChineseResult(
            candidate=candidate,
            copy=copy,
            origin="rule_fallback",
            error_code=safe_error,
            model=self.settings.minimax_fast_model,
            usages=tuple(usages),
        )

    @staticmethod
    def _prompt(candidate: DailyReportChineseCandidate) -> str:
        context = {
            key: _safe_context(candidate.snapshot.get(key))
            for key in (
                "zh_title",
                "zh_summary",
                "publisher_names",
                "confirmation_summary",
                "limitations",
            )
        }
        context["event_key"] = candidate.key
        return (
            f"{UNTRUSTED_PREAMBLE}\n"
            "只生成简体中文标题和中文文章概述。不得判断来源合法性、事件确认状态、"
            "证据强度、收录或审核结论。\n"
            f"固定日报材料：{json.dumps(context, ensure_ascii=False)}\n"
            f"JSON schema: {json.dumps(_ChineseResponse.model_json_schema())}"
        )


def _snapshot_text(snapshot: dict[str, object], key: str, fallback: str) -> str:
    value = snapshot.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _safe_context(value: object) -> str:
    rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    cleaned = " ".join(_URL_LIKE.sub("[omitted]", rendered).split())
    return cleaned[:_MAX_CONTEXT]


def _is_meaningful_simplified_chinese(result: _ChineseResponse) -> bool:
    return _is_meaningful_chinese_text(
        result.zh_title,
        minimum_length=_MIN_TITLE_LENGTH,
        maximum_length=_MAX_TITLE_LENGTH,
        minimum_han=3,
    ) and _is_meaningful_chinese_text(
        result.zh_summary,
        minimum_length=_MIN_SUMMARY_LENGTH,
        maximum_length=_MAX_SUMMARY_LENGTH,
        minimum_han=8,
    )


def _is_meaningful_chinese_text(
    value: str,
    *,
    minimum_length: int,
    maximum_length: int,
    minimum_han: int,
) -> bool:
    length = len(value)
    if length < minimum_length or length > maximum_length or _KANA.search(value):
        return False
    han_count = len(_CJK.findall(value))
    latin_count = len(_LATIN.findall(value))
    if han_count < minimum_han or han_count / max(han_count + latin_count, 1) < 0.35:
        return False
    simplified = convert_chinese(value, "zh-cn")
    variant_changes = sum(
        left != right for left, right in zip(value, simplified, strict=False)
    )
    variant_changes += abs(len(value) - len(simplified))
    return variant_changes < 2
