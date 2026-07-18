from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace

import httpx
from pydantic import BaseModel, ConfigDict, field_validator

from newsradar.ai.minimax import UNTRUSTED_PREAMBLE, MiniMaxClient, ModelUsage
from newsradar.settings import Settings

_CJK = re.compile(r"[\u3400-\u9fff]")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_MAX_CONTEXT = 1200
_MAX_ITEM_TIMEOUT_SECONDS = 45


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
                return await self._enrich_one(row)

        return tuple(await asyncio.gather(*(run_one(row) for row in candidates)))

    async def _enrich_one(
        self, candidate: DailyReportChineseCandidate
    ) -> DailyReportChineseResult:
        usages: list[ModelUsage] = []
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
            return DailyReportChineseResult(
                candidate=candidate,
                copy=snapshot_copy,
                origin="rule_fallback",
                error_code=usages[-1].error if usages else "unexpected_error",
                model=self.settings.minimax_fast_model,
                usages=tuple(usages),
            )
        if not _CJK.search(result.zh_title) or not _CJK.search(result.zh_summary):
            if usages:
                usages[-1] = replace(
                    usages[-1], outcome="fallback", error="non_chinese_output"
                )
            return DailyReportChineseResult(
                candidate=candidate,
                copy=snapshot_copy,
                origin="rule_fallback",
                error_code="non_chinese_output",
                model=self.settings.minimax_fast_model,
                usages=tuple(usages),
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
    cleaned = " ".join(_URL.sub("", rendered).split())
    return cleaned[:_MAX_CONTEXT]
