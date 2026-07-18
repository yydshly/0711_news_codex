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
_URL_LIKE_FEATURE = re.compile(
    r"""
    (?<![\w])[a-z][a-z0-9+.-]*:(?=\S)
    |://
    |(?<!:)//(?=\[?[a-z0-9])
    |(?<![\w])www\.
    |(?<![\w.+-])[\w.+-]+@(?:[a-z0-9-]+\.)+[a-z]{2,63}
    |\b(?:\d{1,3}\.){3}\d{1,3}\b
    |\[[0-9a-f:.]*:[0-9a-f:.]*\]
    |(?<![\w:])::(?=[0-9a-f:.])
    |(?<![\w:])(?=[0-9a-f:.]*:[0-9a-f:.]*:)[0-9a-f:.]+
    |\b(?:[a-z0-9-]+\.)+[a-z]{2,63}\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
_MAX_CONTEXT = 1200
_MAX_CONTEXT_INSPECTION = 16_000
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
    review_recommendation: str
    evidence_assessment: str

    @field_validator(
        "zh_title", "zh_summary", "review_recommendation", "evidence_assessment"
    )
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
    review_recommendation: str
    evidence_assessment: str


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
            review_recommendation="建议先核对现有公开材料，再决定是否进入重点跟踪。",
            evidence_assessment="当前使用规则回退生成说明，需结合已有公开证据继续判断。",
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
        snapshot_copy = rule_based_chinese_copy(candidate.snapshot)
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
                review_recommendation=result.review_recommendation,
                evidence_assessment=result.evidence_assessment,
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
        copy = snapshot_copy or rule_based_chinese_copy(candidate.snapshot)
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
            "只生成简体中文标题、中文文章概述、中文审核建议和中文证据评价。"
            "固定日报材料已经给出审核结论所需事实；不得判断或改变来源合法性、事件确认状态、"
            "证据强度、收录或审核结论。审核建议和证据评价只能解释已有事实与下一步核对动作。\n"
            f"固定日报材料：{json.dumps(context, ensure_ascii=False)}\n"
            f"JSON schema: {json.dumps(_ChineseResponse.model_json_schema())}"
        )


def _snapshot_text(snapshot: dict[str, object], key: str, fallback: str) -> str:
    value = snapshot.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def rule_based_chinese_copy(snapshot: dict[str, object]) -> DailyReportChineseCopy:
    recommendation, assessment = _rule_explanations(snapshot)
    return DailyReportChineseCopy(
        zh_title=_snapshot_text(snapshot, "zh_title", "未命名事件"),
        zh_summary=_snapshot_text(
            snapshot,
            "zh_summary",
            "当前公开材料不足以形成完整中文概述。",
        ),
        review_recommendation=recommendation,
        evidence_assessment=assessment,
    )


def _rule_explanations(snapshot: dict[str, object]) -> tuple[str, str]:
    roots = snapshot.get("independent_root_count")
    root_count = roots if isinstance(roots, int) and not isinstance(roots, bool) else 0
    status = _snapshot_text(snapshot, "status", "emerging")
    if status == "confirmed" or root_count >= 2:
        return (
            "建议跟踪后续影响、正式执行节点和新的权威公开材料。",
            "现有公开材料已具备较强的独立交叉印证，可作为持续跟踪信号。",
        )
    limitations = " ".join(_string_values(snapshot.get("limitations"))).lower()
    confirmation = _snapshot_text(snapshot, "confirmation_summary", "").lower()
    combined = f"{limitations} {confirmation}"
    if any(marker in combined for marker in ("independent", "独立", "second", "第二")):
        return (
            "建议补充第二个独立公开来源，并核对其发布时间与原始材料。",
            "当前已有公开线索，但独立证据根数量不足，仍需交叉确认。",
        )
    if any(marker in combined for marker in ("official", "官方", "一手")):
        return (
            "建议优先核对主管机构、公司或项目方的官方一手发布。",
            "当前公开线索尚未形成可核验的官方一手证据，暂不宜作为已确认事实。",
        )
    return (
        "建议保留为待核对信号，优先补充可追溯的原始发布或独立报道。",
        "现有材料尚不足以形成独立交叉印证，需要结合后续公开信息继续评估。",
    )


def _string_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _safe_context(value: object) -> str:
    rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(rendered) > _MAX_CONTEXT_INSPECTION:
        return "[omitted]"
    normalized = " ".join(rendered.split())
    if _URL_LIKE_FEATURE.search(normalized):
        return "[omitted]"
    return normalized[:_MAX_CONTEXT]


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
    ) and _is_meaningful_chinese_text(
        result.review_recommendation,
        minimum_length=_MIN_SUMMARY_LENGTH,
        maximum_length=_MAX_SUMMARY_LENGTH,
        minimum_han=8,
    ) and _is_meaningful_chinese_text(
        result.evidence_assessment,
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
