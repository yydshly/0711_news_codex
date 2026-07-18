# Automatic Daily Report Chinese Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every eligible automatic daily-report event a validated simplified-Chinese title and summary while keeping evidence, confirmation, inclusion, and source-policy decisions deterministic.

**Architecture:** Add a focused per-event MiniMax adapter used only by the automatic report review stage. The Worker enriches each unique report event once, persists the resulting review pair and a safe audit summary in one transaction, then reuses the existing atomic archive and dual-audio flow. Manual report generation remains read-only, and no database migration is introduced.

**Tech Stack:** Python 3.12, Pydantic 2, HTTPX, SQLAlchemy 2, FastAPI/Jinja2, PostgreSQL/SQLite test fixtures, pytest, Ruff.

## Global Constraints

- Work only in `D:\codex_project_work\news_codex\.worktrees\daily-report-chinese-enrichment` on `codex/daily-report-chinese-enrichment`.
- Do not read, print, copy, stage, or commit `.env` or any credential value.
- Do not modify, stage, or commit the user-owned reports in the main working tree.
- Do not broaden event-pipeline MiniMax eligibility; automatic daily-report enrichment is a separate boundary.
- MiniMax may generate only `zh_title` and `zh_summary`; deterministic rules continue to own evidence, confirmation, inclusion, and source-policy decisions.
- Use `MiniMax-M2.7-highspeed`, a 45-second total per-item deadline, at most one schema-repair retry, concurrency at most 2, and `daily_report_model_max_items=60` by default.
- A single model failure must fall back only that item and must not block later items, report archival, or either audio rendition.
- Persist only bounded model metadata and safe error codes; never persist prompts, provider response bodies, URLs in prompts, or secrets.
- Manual report generation, manual review, archived-report revision, and standalone audio regeneration must not trigger text-model calls.
- Every network path must retain timeout, bounded retry, cancellation checkpoint, and structured diagnostic behavior.
- No database migration is allowed for this feature; use existing review rows, `model_usage`, and `daily_reports.generation_summary`.

---

### Task 1: Add the bounded per-event Chinese enrichment adapter

**Files:**
- Create: `src/newsradar/daily_reports/chinese_enrichment.py`
- Modify: `src/newsradar/settings.py:10-25`
- Create: `tests/daily_reports/test_chinese_enrichment.py`
- Modify: `tests/test_minimax_health.py:12-25`

**Interfaces:**
- Consumes: `MiniMaxClient.structured(...)`, `UNTRUSTED_PREAMBLE`, `ModelUsage`, `Settings.minimax_fast_model`, and detached daily-report item snapshots.
- Produces: `DailyReportChineseCandidate`, `DailyReportChineseCopy`, `DailyReportChineseResult`, `DailyReportChineseEnricher.enrich_batch(...)`, and `candidate_key(event_id, event_version_number)`.

- [ ] **Step 1: Write failing schema, sanitization, success, fallback, and concurrency tests**

```python
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
            "confirmation_summary": "当前只有一个公开证据根。",
            "limitations": ["仍需第二条独立证据"],
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
                "choices": [{"message": {"content": json.dumps({
                    "zh_title": "产品正式发布",
                    "zh_summary": "官方材料显示，该产品已经正式发布。",
                }, ensure_ascii=False)}}],
                "usage": {"total_tokens": 42},
            },
            request=request,
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await DailyReportChineseEnricher(
                Settings(minimax_api_key="secret"), http
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
            json={"choices": [{"message": {"content": json.dumps({
                "zh_title": "English only",
                "zh_summary": "Still English only",
            })}}]},
            request=request,
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await DailyReportChineseEnricher(
                Settings(minimax_api_key="secret"), http
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
            return await DailyReportChineseEnricher(Settings(), http).enrich_batch(
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
                Settings(minimax_api_key="secret", event_model_max_concurrency=9), http
            ).enrich_batch((candidate(11), candidate(12), candidate(13)))

    assert len(asyncio.run(run())) == 3
    assert maximum == 2
```

- [ ] **Step 2: Run the focused tests and verify the missing module/settings fail**

Run: `uv run --extra dev pytest tests/daily_reports/test_chinese_enrichment.py tests/test_minimax_health.py -q`

Expected: FAIL during import because `newsradar.daily_reports.chinese_enrichment` does not exist and because `Settings` has no `daily_report_model_max_items` field.

- [ ] **Step 3: Implement the strict response schema and bounded adapter**

```python
# src/newsradar/daily_reports/chinese_enrichment.py
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, replace
from typing import Callable

import httpx
from pydantic import BaseModel, ConfigDict, field_validator

from newsradar.ai.minimax import UNTRUSTED_PREAMBLE, MiniMaxClient, ModelUsage
from newsradar.settings import Settings

_CJK = re.compile(r"[\u3400-\u9fff]")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_MAX_CONTEXT = 1200


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
        result = await MiniMaxClient(
            self.settings, self.http, usages.append
        ).structured(
            "daily_report_chinese_enrichment",
            self.settings.minimax_fast_model,
            self._prompt(candidate),
            _ChineseResponse,
            fallback,
            timeout_seconds=self.settings.event_model_timeout_seconds,
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
            "请只生成简体中文标题和中文文章概述。不得判断来源合法性、"
            "事件确认状态、证据根、收录或审核结论。\n"
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
```

The adapter records a structurally valid but non-Chinese provider response as `non_chinese_output`, replaces the corresponding success audit with a fallback audit, and uses the immutable snapshot copy. Pydantic structural failures continue through the existing one-repair path and preserve the last safe MiniMax error code.

Add to `Settings`:

```python
daily_report_model_max_items: int = 60
```

- [ ] **Step 4: Run the focused tests and Ruff**

Run: `uv run --extra dev pytest tests/daily_reports/test_chinese_enrichment.py tests/test_minimax_health.py -q`

Expected: PASS.

Run: `uv run --extra dev ruff check src/newsradar/daily_reports/chinese_enrichment.py src/newsradar/settings.py tests/daily_reports/test_chinese_enrichment.py tests/test_minimax_health.py`

Expected: `All checks passed!`

- [ ] **Step 5: Commit the adapter milestone**

```powershell
git add src/newsradar/daily_reports/chinese_enrichment.py src/newsradar/settings.py tests/daily_reports/test_chinese_enrichment.py tests/test_minimax_health.py
git commit -m "feat: add bounded daily report Chinese enrichment"
```

---

### Task 2: Persist one enrichment audit and one review pair per unique event

**Files:**
- Modify: `src/newsradar/daily_reports/autopilot.py:190-243`
- Modify: `src/newsradar/daily_reports/repository.py:150-345,570-606`
- Modify: `tests/daily_reports/test_autopilot.py`
- Modify: `tests/daily_reports/test_repository.py`

**Interfaces:**
- Consumes: `DailyReportChineseCandidate`, `DailyReportChineseResult`, `ModelUsage`, existing decision/overview item rows, and existing review draft types.
- Produces: `DailyReportRepository.chinese_enrichment_candidates(report_id)`, `DailyReportRepository.save_automatic_chinese_reviews(...)`, and review builders with optional `zh_title`/`zh_summary` overrides.

- [ ] **Step 1: Write failing deterministic-decision and repository idempotency tests**

```python
from newsradar.ai.minimax import ModelUsage
from newsradar.daily_reports.autopilot import build_decision_review, build_overview_review
from newsradar.daily_reports.chinese_enrichment import (
    DailyReportChineseCopy,
    DailyReportChineseResult,
)


def seed_report_with_shared_event(db_session):
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    report = repository.create_draft(_draft(db_session))
    return report, repository.items(report.id)[0], repository.overview_items(report.id)[0]


def model_result_for(candidate):
    return DailyReportChineseResult(
        candidate=candidate,
        copy=DailyReportChineseCopy(
            zh_title="模型中文标题",
            zh_summary="模型生成的中文文章概述。",
        ),
        origin="model",
        error_code=None,
        model="MiniMax-M2.7-highspeed",
        usages=(ModelUsage(
            purpose="daily_report_chinese_enrichment",
            model="MiniMax-M2.7-highspeed",
            input_tokens=20,
            output_tokens=10,
            latency_ms=12.5,
            outcome="success",
        ),),
    )


def test_model_copy_cannot_change_rule_decision() -> None:
    snapshot = {
        "status": "emerging",
        "independent_root_count": 0,
        "zh_title": "English",
        "zh_summary": "English summary",
    }
    review = build_decision_review(
        snapshot,
        zh_title="模型中文标题",
        zh_summary="模型只负责中文表达。",
    )
    assert review.decision.value == "needs_evidence"
    assert review.zh_title == "模型中文标题"
    assert review.review_recommendation == "建议保留为待补证信号，关注新增独立公开来源。"


def test_candidates_deduplicate_decision_and_overview_event(db_session) -> None:
    report, decision_item, overview_item = seed_report_with_shared_event(db_session)
    rows = DailyReportRepository(db_session).chinese_enrichment_candidates(report.id)
    assert len(rows) == 1
    assert rows[0].decision_item_id == decision_item.id
    assert rows[0].overview_item_id == overview_item.id


def test_automatic_review_save_is_atomic_audited_and_idempotent(db_session) -> None:
    report, decision_item, overview_item = seed_report_with_shared_event(db_session)
    repository = DailyReportRepository(db_session)
    result = model_result_for(repository.chinese_enrichment_candidates(report.id)[0])

    assert repository.save_automatic_chinese_reviews(
        report.id,
        result,
        build_decision_review(result.candidate.snapshot, zh_title=result.copy.zh_title,
                              zh_summary=result.copy.zh_summary),
        build_overview_review(result.candidate.snapshot, zh_title=result.copy.zh_title,
                              zh_summary=result.copy.zh_summary),
        candidate_total=1,
        model_budget=60,
    ) is True
    assert repository.save_automatic_chinese_reviews(
        report.id,
        result,
        build_decision_review(result.candidate.snapshot),
        build_overview_review(result.candidate.snapshot),
        candidate_total=1,
        model_budget=60,
    ) is False

    assert len(repository.editorial_reviews(decision_item.id)) == 1
    assert len(repository.overview_editorial_reviews(overview_item.id)) == 1
    summary = db_session.get(DailyReportRecord, report.id).generation_summary[
        "daily_chinese_enrichment"
    ]
    assert summary["candidate_total"] == 1
    assert summary["model_success"] == 1
    assert summary["rule_fallback"] == 0
    assert summary["items"][result.candidate.key]["origin"] == "model"
    assert summary["model_usage_ids"]
```

- [ ] **Step 2: Run the focused tests and verify the new signatures fail**

Run: `uv run --extra dev pytest tests/daily_reports/test_autopilot.py tests/daily_reports/test_repository.py -q`

Expected: FAIL because review builders do not accept overrides and repository audit methods do not exist.

- [ ] **Step 3: Add optional copy overrides without changing rule decisions**

```python
def build_decision_review(
    snapshot: dict[str, object],
    *,
    zh_title: str | None = None,
    zh_summary: str | None = None,
) -> DailyReportEditorialReviewDraft:
    title, summary, recommendation, assessment, decision = _review_values(snapshot)
    return DailyReportEditorialReviewDraft.create(
        decision=decision,
        zh_title=zh_title or title,
        zh_summary=zh_summary or summary,
        review_recommendation=recommendation,
        evidence_assessment=assessment,
    )
```

Apply the same override-only signature to `build_overview_review`. Do not accept a model-provided decision, recommendation, evidence assessment, root count, status, or inclusion flag.

- [ ] **Step 4: Add candidate projection and atomic audit persistence**

Add `commit: bool = True` keyword-only parameters to `save_editorial_review` and `save_overview_editorial_review`; call `session.flush()` when false and retain the existing `session.commit()` behavior when true.

Add these production imports to `repository.py`:

```python
from collections import Counter
from dataclasses import replace

from newsradar.daily_reports.chinese_enrichment import (
    DailyReportChineseCandidate,
    DailyReportChineseResult,
    candidate_key,
)
from newsradar.db.models import ModelUsageRecord
```

Implement `chinese_enrichment_candidates` by iterating `items(report_id)` first and `overview_items(report_id)` second, deduplicating with `candidate_key`, and using `dataclasses.replace` to attach both item IDs. Implement `save_automatic_chinese_reviews` with this exact boundary:

```python
def chinese_enrichment_candidates(
    self, report_id: int
) -> tuple[DailyReportChineseCandidate, ...]:
    rows: dict[str, DailyReportChineseCandidate] = {}
    for item in self.items(report_id):
        row = DailyReportChineseCandidate(
            event_id=item.event_id,
            event_version_number=item.event_version_number,
            snapshot=dict(item.snapshot),
            decision_item_id=item.id,
            overview_item_id=None,
        )
        rows[row.key] = row
    for item in self.overview_items(report_id):
        key = candidate_key(item.event_id, item.event_version_number)
        existing = rows.get(key)
        rows[key] = (
            replace(existing, overview_item_id=item.id)
            if existing is not None
            else DailyReportChineseCandidate(
                event_id=item.event_id,
                event_version_number=item.event_version_number,
                snapshot=dict(item.snapshot),
                decision_item_id=None,
                overview_item_id=item.id,
            )
        )
    return tuple(rows.values())


def completed_chinese_enrichment_keys(self, report_id: int) -> frozenset[str]:
    report = self._draft_report(report_id)
    summary = report.generation_summary if isinstance(report.generation_summary, dict) else {}
    audit = summary.get("daily_chinese_enrichment")
    items = audit.get("items") if isinstance(audit, dict) else None
    candidates = {row.key: row for row in self.chinese_enrichment_candidates(report_id)}
    if not isinstance(items, dict):
        return frozenset()
    return frozenset(
        key for key in items
        if isinstance(key, str)
        and key in candidates
        and self._automatic_reviews_complete(candidates[key])
    )
```

```python
def save_automatic_chinese_reviews(
    self,
    report_id: int,
    result: DailyReportChineseResult,
    decision_draft: DailyReportEditorialReviewDraft | None,
    overview_draft: DailyReportOverviewEditorialReviewDraft | None,
    *,
    candidate_total: int,
    model_budget: int,
) -> bool:
    report = self._draft_report(report_id)
    summary = dict(report.generation_summary)
    audit = dict(summary.get("daily_chinese_enrichment") or {})
    item_audits = dict(audit.get("items") or {})
    if result.candidate.key in item_audits and self._automatic_reviews_complete(
        result.candidate
    ):
        return False

    usage_ids: list[int] = []
    for usage in result.usages:
        record = ModelUsageRecord(
            purpose=usage.purpose,
            model=usage.model,
            input_tokens=max(0, usage.input_tokens),
            output_tokens=max(0, usage.output_tokens),
            latency_ms=usage.latency_ms,
            outcome=usage.outcome,
            error=usage.error[:1000] if usage.error else None,
        )
        self.session.add(record)
        self.session.flush()
        usage_ids.append(record.id)

    if decision_draft is not None and result.candidate.decision_item_id is not None:
        self.save_editorial_review(
            report_id, result.candidate.decision_item_id, decision_draft, commit=False
        )
    if overview_draft is not None and result.candidate.overview_item_id is not None:
        self.save_overview_editorial_review(
            report_id, result.candidate.overview_item_id, overview_draft, commit=False
        )

    item_audits[result.candidate.key] = {
        "origin": result.origin,
        "error_code": result.error_code,
        "model": result.model,
        "model_usage_ids": usage_ids,
    }
    audit = rebuild_chinese_enrichment_summary(
        item_audits, candidate_total=candidate_total, model_budget=model_budget
    )
    summary["daily_chinese_enrichment"] = audit
    report.generation_summary = summary
    self.session.commit()
    return True
```

`rebuild_chinese_enrichment_summary` must derive `processed`, `model_success`, `rule_fallback`, `budget_fallback`, sorted `error_counts`, and a flattened sorted unique `model_usage_ids` from `items`; no model text or prompt is copied into the summary.

```python
def _automatic_reviews_complete(self, row: DailyReportChineseCandidate) -> bool:
    decision_complete = (
        row.decision_item_id is None
        or self._latest_editorial_review(row.decision_item_id) is not None
    )
    overview_complete = (
        row.overview_item_id is None
        or self._latest_overview_editorial_review(row.overview_item_id) is not None
    )
    return decision_complete and overview_complete


def rebuild_chinese_enrichment_summary(
    items: dict[str, dict[str, object]],
    *,
    candidate_total: int,
    model_budget: int,
) -> dict[str, object]:
    origins = Counter(
        row.get("origin") for row in items.values() if isinstance(row, dict)
    )
    errors = Counter(
        row.get("error_code")
        for row in items.values()
        if isinstance(row, dict) and isinstance(row.get("error_code"), str)
    )
    usage_ids = sorted({
        usage_id
        for row in items.values()
        if isinstance(row, dict)
        for usage_id in row.get("model_usage_ids", [])
        if isinstance(usage_id, int) and not isinstance(usage_id, bool) and usage_id > 0
    })
    return {
        "candidate_total": candidate_total,
        "model_budget": model_budget,
        "processed": len(items),
        "model_success": origins["model"],
        "rule_fallback": origins["rule_fallback"],
        "budget_fallback": origins["budget_limit"],
        "error_counts": dict(sorted(errors.items())),
        "model_usage_ids": usage_ids,
        "items": items,
    }
```

- [ ] **Step 5: Run repository, schema, audio-readiness, and integrity tests**

Run: `uv run --extra dev pytest tests/daily_reports/test_autopilot.py tests/daily_reports/test_repository.py tests/daily_reports/test_schema.py tests/daily_reports/test_text_integrity.py tests/daily_reports/test_audio_runtime.py -q`

Expected: PASS.

Run: `uv run --extra dev ruff check src/newsradar/daily_reports/autopilot.py src/newsradar/daily_reports/repository.py tests/daily_reports/test_autopilot.py tests/daily_reports/test_repository.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit the persistence milestone**

```powershell
git add src/newsradar/daily_reports/autopilot.py src/newsradar/daily_reports/repository.py tests/daily_reports/test_autopilot.py tests/daily_reports/test_repository.py
git commit -m "feat: persist daily Chinese review audit"
```

---

### Task 3: Integrate enrichment into the recoverable automatic-report Worker stage

**Files:**
- Modify: `src/newsradar/daily_reports/autopilot_runtime.py:20-410`
- Modify: `tests/daily_reports/test_autopilot_runtime.py`
- Modify: `tests/daily_reports/test_service.py:427-450`
- Modify: `tests/acceptance/test_daily_autopilot_content_wave.py`

**Interfaces:**
- Consumes: Task 1 adapter/results, Task 2 candidate/audit methods, Worker checkpoint, existing `WRITE_REVIEWS` continuation, and existing atomic archive/audio command.
- Produces: a bounded `DailyAutopilotHandler._write_reviews` implementation that enriches priority-ordered unique events in batches of two and resumes without repeating completed work.

- [ ] **Step 1: Write failing runtime tests for unique calls, partial fallback, budget fallback, and resume**

```python
from dataclasses import replace
from datetime import date

from newsradar.ai.minimax import ModelUsage
from newsradar.daily_reports.autopilot import build_decision_review, build_overview_review
from newsradar.daily_reports.chinese_enrichment import (
    DailyReportChineseCopy,
    DailyReportChineseEnricher,
    DailyReportChineseResult,
)
from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.schema import (
    DailyReportDraft,
    DailyReportItemDraft,
    DailyReportOverviewItemDraft,
    ReportSection,
)
from newsradar.db.models import DailyReportRecord, EventRecord


def seed_autopilot_report(factory, *, event_count: int = 2, completed_count: int = 0):
    with factory() as db:
        operation = OperationRunRecord(
            operation_type=OperationType.HIGH_VALUE_NEWS_WAVE.value,
            trigger="test",
            status=OperationStatus.SUCCEEDED.value,
            requested_scope={},
            result_summary={"event_manifest_complete": True},
        )
        db.add(operation)
        db.flush()
        items = []
        overview_items = []
        for position in range(1, event_count + 1):
            event_id = 100 + position
            db.add(EventRecord(
                id=event_id,
                canonical_key=f"autopilot-chinese-{event_id}",
                status="emerging",
                current_version_number=1,
                occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
            ))
            snapshot = {
                "status": "emerging",
                "independent_root_count": 0,
                "zh_title": f"English {event_id}",
                "zh_summary": f"English summary {event_id}",
            }
            items.append(DailyReportItemDraft(
                event_id=event_id,
                event_version_number=1,
                section=ReportSection.EMERGING,
                position=position,
                snapshot=snapshot,
            ))
            overview_items.append(DailyReportOverviewItemDraft(
                event_id=event_id,
                event_version_number=1,
                position=position,
                snapshot=snapshot,
                decision_event_id=event_id,
            ))
        db.flush()
        report = DailyReportRepository(db).create_draft(DailyReportDraft(
            report_date=date(2026, 7, 18),
            window_hours=24,
            window_start=datetime(2026, 7, 17, tzinfo=UTC),
            window_end=datetime(2026, 7, 18, tzinfo=UTC),
            source_operation_id=operation.id,
            generation_summary={"confirmed_count": 0, "emerging_count": event_count},
            items=tuple(items),
            overview_items=tuple(overview_items),
        ))
        run = DailyAutopilotRepository(db).create_run(
            window_hours=24,
            trigger="test",
            requested_scope={"wave_plan": serialize_wave_plan(_wave_plan())},
        )
        DailyAutopilotRepository(db).transition(
            run.id,
            stage=DailyAutopilotStage.WRITE_REVIEWS,
            daily_report_id=report.id,
            event_operation_id=operation.id,
        )
        report_id = report.id
        run_id = run.id
        db.commit()
        run_view = SimpleNamespace(id=run_id, daily_report_id=report_id)

    if completed_count:
        with factory() as db:
            repository = DailyReportRepository(db)
            for row in repository.chinese_enrichment_candidates(report_id)[:completed_count]:
                result = model_result_for(row)
                repository.save_automatic_chinese_reviews(
                    report_id,
                    result,
                    build_decision_review(row.snapshot, zh_title=result.copy.zh_title,
                                          zh_summary=result.copy.zh_summary),
                    build_overview_review(row.snapshot, zh_title=result.copy.zh_title,
                                          zh_summary=result.copy.zh_summary),
                    candidate_total=event_count,
                    model_budget=60,
                )
    return run_view


def load_enrichment_summary(factory, report_id: int) -> dict[str, object]:
    with factory() as db:
        report = db.get(DailyReportRecord, report_id)
        return dict(report.generation_summary["daily_chinese_enrichment"])


def model_result_for(candidate):
    return DailyReportChineseResult(
        candidate=candidate,
        copy=DailyReportChineseCopy("模型中文标题", "模型生成的中文文章概述。"),
        origin="model",
        error_code=None,
        model="MiniMax-M2.7-highspeed",
        usages=(ModelUsage(
            purpose="daily_report_chinese_enrichment",
            model="MiniMax-M2.7-highspeed",
            input_tokens=20,
            output_tokens=10,
            latency_ms=12.5,
            outcome="success",
        ),),
    )


def fallback_result_for(candidate, error_code: str):
    result = model_result_for(candidate)
    return replace(
        result,
        copy=DailyReportChineseCopy(
            zh_title=str(candidate.snapshot["zh_title"]),
            zh_summary=str(candidate.snapshot["zh_summary"]),
        ),
        origin="rule_fallback",
        error_code=error_code,
        usages=(replace(result.usages[0], outcome="fallback", error=error_code),),
    )


def test_write_reviews_enriches_each_unique_event_once_and_reuses_copy(monkeypatch) -> None:
    session_factory = _session_factory()
    run = seed_autopilot_report(session_factory)
    calls: list[str] = []

    async def enrich_batch(self, candidates, checkpoint=None):
        calls.extend(row.key for row in candidates)
        return tuple(model_result_for(row) for row in candidates)

    monkeypatch.setattr(DailyReportChineseEnricher, "enrich_batch", enrich_batch)
    result = DailyAutopilotHandler(session_factory)._write_reviews(run, lambda _phase: None)
    assert result.status.value == "succeeded"
    assert calls == ["101:1", "102:1"]
    assert result.result_summary["model_success"] == 2


def test_write_reviews_continues_after_one_model_fallback(monkeypatch) -> None:
    session_factory = _session_factory()
    run = seed_autopilot_report(session_factory)

    async def enrich_batch(self, candidates, checkpoint=None):
        return tuple(
            fallback_result_for(row, "http_429") if row.event_id == 101
            else model_result_for(row)
            for row in candidates
        )

    monkeypatch.setattr(DailyReportChineseEnricher, "enrich_batch", enrich_batch)
    result = DailyAutopilotHandler(session_factory)._write_reviews(run, lambda _phase: None)
    assert result.status.value == "succeeded"
    assert result.result_summary["model_success"] == 1
    assert result.result_summary["rule_fallback"] == 1
    assert result.result_summary["error_counts"] == {"http_429": 1}


def test_write_reviews_resume_skips_completed_event(monkeypatch) -> None:
    session_factory = _session_factory()
    run = seed_autopilot_report(session_factory, completed_count=1)
    calls: list[str] = []

    async def enrich_batch(self, candidates, checkpoint=None):
        calls.extend(row.key for row in candidates)
        return tuple(model_result_for(row) for row in candidates)

    monkeypatch.setattr(DailyReportChineseEnricher, "enrich_batch", enrich_batch)
    DailyAutopilotHandler(session_factory)._write_reviews(run, lambda _phase: None)
    assert calls == ["102:1"]


def test_write_reviews_marks_items_beyond_local_limit_without_calling_model(monkeypatch) -> None:
    session_factory = _session_factory()
    run = seed_autopilot_report(session_factory, event_count=3)
    settings = Settings(daily_report_model_max_items=2, minimax_api_key="secret")
    calls: list[str] = []

    async def enrich_batch(self, candidates, checkpoint=None):
        calls.extend(row.key for row in candidates)
        return tuple(model_result_for(row) for row in candidates)

    monkeypatch.setattr(DailyReportChineseEnricher, "enrich_batch", enrich_batch)
    handler = DailyAutopilotHandler(session_factory, settings=settings)
    handler._write_reviews(run, lambda _phase: None)
    assert calls == ["101:1", "102:1"]
    assert load_enrichment_summary(session_factory, run.daily_report_id)["budget_fallback"] == 1
```

Extend the existing `test_generate_sanitizes_evidence_and_never_calls_network_or_model` in `tests/daily_reports/test_service.py` with this guard before its current successful `DailyReportService.generate(...)` call:

```python
def forbidden_text_enricher(*_args, **_kwargs):
    raise AssertionError("manual report generation must remain read-only")

monkeypatch.setattr(
    "newsradar.daily_reports.chinese_enrichment.DailyReportChineseEnricher.__init__",
    forbidden_text_enricher,
)
```

Keep the test's existing snapshot and report assertions unchanged.

- [ ] **Step 2: Run the runtime tests and verify constructor/integration failures**

Run: `uv run --extra dev pytest tests/daily_reports/test_autopilot_runtime.py -q`

Expected: FAIL because `DailyAutopilotHandler` does not accept `settings` and still writes rule-only reviews directly.

- [ ] **Step 3: Add injectable settings and batch execution without open DB sessions**

Update the constructor:

```python
def __init__(
    self,
    create_session: Callable[[], AbstractContextManager[Session]],
    *,
    utcnow: Callable[[], datetime] | None = None,
    settings: Settings | None = None,
) -> None:
    self._create_session = create_session
    self._utcnow = utcnow or (lambda: datetime.now(UTC))
    self._settings = settings or get_settings()
```

Replace direct review loops with this sequence:

```python
with self._create_session() as session:
    repository = DailyReportRepository(session, utcnow=self._utcnow)
    candidates = repository.chinese_enrichment_candidates(run.daily_report_id)
    completed = repository.completed_chinese_enrichment_keys(run.daily_report_id)

pending = tuple(row for row in candidates if row.key not in completed)
budget = self._settings.daily_report_model_max_items
model_keys = {row.key for row in candidates[:budget]}

for offset in range(0, len(pending), 2):
    batch = pending[offset : offset + 2]
    callable_rows = tuple(row for row in batch if row.key in model_keys)
    results = list(self._run_chinese_enrichment(callable_rows, checkpoint))
    results.extend(budget_result_for(row, self._settings.minimax_fast_model)
                   for row in batch if row.key not in model_keys)
    for result in results:
        checkpoint("daily_autopilot:save_chinese_enrichment_item")
        decision = build_decision_review(
            result.candidate.snapshot,
            zh_title=result.copy.zh_title,
            zh_summary=result.copy.zh_summary,
        ) if result.candidate.decision_item_id is not None else None
        overview = build_overview_review(
            result.candidate.snapshot,
            zh_title=result.copy.zh_title,
            zh_summary=result.copy.zh_summary,
        ) if result.candidate.overview_item_id is not None else None
        with self._create_session() as session:
            DailyReportRepository(session, utcnow=self._utcnow).save_automatic_chinese_reviews(
                run.daily_report_id,
                result,
                decision,
                overview,
                candidate_total=len(candidates),
                model_budget=budget,
            )
```

`_run_chinese_enrichment` must create one `httpx.AsyncClient`, call `DailyReportChineseEnricher.enrich_batch` through `asyncio.run`, and close the client. No SQLAlchemy session may remain open across the HTTP call. `budget_result_for` must return the snapshot fallback with `origin="budget_limit"`, `error_code="budget_limit"`, and no usage rows.

```python
def _run_chinese_enrichment(
    self,
    candidates: tuple[DailyReportChineseCandidate, ...],
    checkpoint: Callable[[str], None],
) -> tuple[DailyReportChineseResult, ...]:
    if not candidates:
        return ()

    async def run() -> tuple[DailyReportChineseResult, ...]:
        import httpx

        async with httpx.AsyncClient() as http:
            return await DailyReportChineseEnricher(
                self._settings, http
            ).enrich_batch(candidates, checkpoint)

    return asyncio.run(run())


def budget_result_for(
    candidate: DailyReportChineseCandidate, model: str
) -> DailyReportChineseResult:
    return DailyReportChineseResult(
        candidate=candidate,
        copy=DailyReportChineseCopy(
            zh_title=_snapshot_text(candidate.snapshot, "zh_title", "未命名事件"),
            zh_summary=_snapshot_text(
                candidate.snapshot,
                "zh_summary",
                "当前公开材料不足以形成完整中文概述。",
            ),
        ),
        origin="budget_limit",
        error_code="budget_limit",
        model=model,
        usages=(),
    )
```

After processing, reload `daily_chinese_enrichment`, transition to `ARCHIVE_AND_ENQUEUE_AUDIO`, and return its counts/error summary. Keep existing archive and audio code unchanged.

- [ ] **Step 4: Extend the existing end-to-end automatic-report acceptance test**

Patch `MiniMaxClient.structured` in `test_daily_autopilot_turns_real_wave_items_into_reviewed_dual_audio_package` so each unique report event returns a Chinese copy and records its event key. Assert:

```python
assert len(model_event_keys) == len(set(model_event_keys))
assert summary["processed"] == summary["candidate_total"]
assert summary["model_success"] == summary["candidate_total"]
assert all(re.search(r"[\u3400-\u9fff]", review.zh_title) for review in decision_reviews)
assert all(repository.overview_editorial_reviews(item.id) for item in overview_items)
assert report.status == "archived"
assert decision_audio.status == "succeeded"
assert overview_audio.status == "succeeded"
```

- [ ] **Step 5: Run runtime and acceptance tests**

Run: `uv run --extra dev --extra research pytest tests/daily_reports/test_autopilot_runtime.py tests/daily_reports/test_service.py::test_generate_sanitizes_evidence_and_never_calls_network_or_model tests/acceptance/test_daily_autopilot_content_wave.py -q`

Expected: PASS.

Run: `uv run --extra dev ruff check src/newsradar/daily_reports/autopilot_runtime.py tests/daily_reports/test_autopilot_runtime.py tests/acceptance/test_daily_autopilot_content_wave.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit the Worker integration milestone**

```powershell
git add src/newsradar/daily_reports/autopilot_runtime.py tests/daily_reports/test_autopilot_runtime.py tests/daily_reports/test_service.py tests/acceptance/test_daily_autopilot_content_wave.py
git commit -m "feat: enrich automatic daily report reviews"
```

---

### Task 4: Show accurate global and per-item Chinese enrichment diagnostics

**Files:**
- Modify: `src/newsradar/web/daily_report_queries.py:44-175,193-325,396-646`
- Modify: `src/newsradar/web/daily_autopilot_queries.py:19-115`
- Modify: `src/newsradar/web/templates/daily_report_detail.html:1-180,326-337`
- Modify: `src/newsradar/web/templates/daily_autopilot_detail.html:17-75`
- Modify: `src/newsradar/web/static/styles.css`
- Modify: `tests/web/test_daily_report_pages.py`
- Modify: `tests/web/test_daily_autopilot_pages.py`

**Interfaces:**
- Consumes: `generation_summary.daily_chinese_enrichment` and item keys from Tasks 2-3.
- Produces: `DailyReportChineseEnrichmentView`, `DailyReportChineseOriginView`, accurate per-item labels, and automatic-task metrics.

- [ ] **Step 1: Write failing query and rendered-page tests**

```python
# tests/web/test_daily_report_pages.py uses its existing NOW, seed_daily_report,
# safe_client_with_token, and DailyReportRepository imports.
def test_detail_projects_daily_chinese_enrichment_per_item(db_session) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session)
    confirmed, emerging = repository.items(report.id)
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": {
            "candidate_total": 2,
            "processed": 2,
            "model_success": 1,
            "rule_fallback": 1,
            "budget_fallback": 0,
            "error_counts": {"http_429": 1},
            "items": {
                f"{confirmed.event_id}:1": {"origin": "model", "error_code": None},
                f"{emerging.event_id}:1": {
                    "origin": "rule_fallback",
                    "error_code": "http_429",
                },
            },
        },
    }
    db_session.commit()
    view = DailyReportQueryService(db_session).detail(report.id)
    assert view.chinese_enrichment.model_success == 1
    assert view.confirmed[0].chinese_origin.label_zh == "MiniMax"
    assert view.emerging[0].chinese_origin.label_zh == "规则回退（请求频率受限）"


def test_daily_report_page_replaces_legacy_model_degraded_copy(
    db_session, monkeypatch
) -> None:
    report = seed_daily_report(db_session)
    items = DailyReportRepository(db_session).items(report.id)
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": {
            "candidate_total": 2,
            "processed": 2,
            "model_success": 1,
            "rule_fallback": 1,
            "budget_fallback": 0,
            "error_counts": {"http_429": 1},
            "items": {
                f"{items[0].event_id}:1": {"origin": "model", "error_code": None},
                f"{items[1].event_id}:1": {
                    "origin": "rule_fallback",
                    "error_code": "http_429",
                },
            },
        },
    }
    db_session.commit()
    client, _token = safe_client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-reports/{report.id}")
    assert "中文增强：MiniMax" in response.text
    assert "中文增强：规则回退（请求频率受限）" in response.text
    assert "MiniMax：已降级，本版使用规则中文内容" not in response.text
```

```python
# tests/web/test_daily_autopilot_pages.py
from datetime import UTC, date, datetime

from newsradar.db.models import DailyReportRecord


def test_automatic_task_page_shows_linked_report_enrichment_metrics(
    db_session, monkeypatch
) -> None:
    operation = OperationRunRecord(
        operation_type=OperationType.HIGH_VALUE_NEWS_WAVE.value,
        trigger="test",
        status=OperationStatus.SUCCEEDED.value,
        requested_scope={},
        result_summary={},
    )
    db_session.add(operation)
    db_session.flush()
    report = DailyReportRecord(
        report_date=date(2026, 7, 18),
        timezone="Asia/Shanghai",
        window_hours=24,
        window_start=datetime(2026, 7, 17, tzinfo=UTC),
        window_end=datetime(2026, 7, 18, tzinfo=UTC),
        source_operation_id=operation.id,
        status="draft",
        revision=1,
        generation_summary={
        "daily_chinese_enrichment": {
            "candidate_total": 2,
            "processed": 2,
            "model_success": 1,
            "rule_fallback": 1,
            "budget_fallback": 0,
            "error_counts": {"http_429": 1},
            "items": {},
        },
        },
        generated_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    db_session.add(report)
    db_session.flush()
    run = DailyAutopilotRepository(db_session).create_run(
        window_hours=24,
        trigger="test",
        requested_scope={"wave_plan": serialize_wave_plan(_wave_plan(24))},
    )
    DailyAutopilotRepository(db_session).transition(
        run.id,
        stage=DailyAutopilotStage.WRITE_REVIEWS,
        event_operation_id=operation.id,
        daily_report_id=report.id,
    )
    db_session.commit()
    client, _token = _client_with_token(db_session, monkeypatch)
    response = client.get(f"/daily-autopilot/{run.id}")
    assert response.status_code == 200
    assert "中文增强候选 2" in response.text
    assert "MiniMax 成功 1" in response.text
    assert "规则回退 1" in response.text
```

- [ ] **Step 2: Run the page tests and verify missing view fields fail**

Run: `uv run --extra dev pytest tests/web/test_daily_report_pages.py tests/web/test_daily_autopilot_pages.py -q`

Expected: FAIL because Chinese enrichment view/origin fields do not exist and templates still render the legacy global `minimax_degraded` copy.

- [ ] **Step 3: Add safe summary projection and Chinese error labels**

```python
@dataclass(frozen=True, slots=True)
class DailyReportChineseOriginView:
    origin: str
    error_code: str | None
    label_zh: str


@dataclass(frozen=True, slots=True)
class DailyReportChineseEnrichmentView:
    candidate_total: int
    processed: int
    model_success: int
    rule_fallback: int
    budget_fallback: int
    error_counts: dict[str, int]
    recorded: bool
```

Add `chinese_origin` to decision and overview item views, and `chinese_enrichment` to `DailyReportDetailView`. Parse only non-negative integers, safe error-code keys, and dict item entries; malformed JSON returns `recorded=False` and the legacy display. Map safe codes to these exact labels:

```python
_CHINESE_ENRICHMENT_ERROR_LABELS = {
    "no_api_key": "未配置文本模型",
    "timeout": "请求超时",
    "http_401": "凭据无效",
    "http_403": "缺少文本模型权限",
    "http_429": "请求频率受限",
    "http_5xx": "模型服务异常",
    "transport_error": "网络连接异常",
    "schema_validation_failed": "返回结构无效",
    "non_chinese_output": "返回内容不是有效中文",
    "budget_limit": "本期安全上限",
    "unexpected_error": "内部异常",
}
```

The automatic-task query may load the linked `DailyReportRecord.generation_summary` read-only; it must never infer text-model status from the event operation's `model_degraded` flag.

Project the summary and each item with bounded helpers:

```python
def _non_negative_integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _chinese_enrichment_view(
    generation_summary: dict[str, object],
) -> tuple[DailyReportChineseEnrichmentView, dict[str, DailyReportChineseOriginView]]:
    raw = generation_summary.get("daily_chinese_enrichment")
    if not isinstance(raw, dict):
        return DailyReportChineseEnrichmentView(0, 0, 0, 0, 0, {}, False), {}
    raw_errors = raw.get("error_counts")
    errors = {
        key: _non_negative_integer(value)
        for key, value in raw_errors.items()
        if isinstance(key, str) and key in _CHINESE_ENRICHMENT_ERROR_LABELS
    } if isinstance(raw_errors, dict) else {}
    origins: dict[str, DailyReportChineseOriginView] = {}
    raw_items = raw.get("items")
    if isinstance(raw_items, dict):
        for key, value in raw_items.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            origin = value.get("origin")
            error = value.get("error_code")
            if origin == "model":
                origins[key] = DailyReportChineseOriginView("model", None, "MiniMax")
            elif origin in {"rule_fallback", "budget_limit"}:
                safe_error = error if isinstance(error, str) else "unexpected_error"
                label = _CHINESE_ENRICHMENT_ERROR_LABELS.get(safe_error, "安全规则回退")
                origins[key] = DailyReportChineseOriginView(origin, safe_error, f"规则回退（{label}）")
    return DailyReportChineseEnrichmentView(
        candidate_total=_non_negative_integer(raw.get("candidate_total")),
        processed=_non_negative_integer(raw.get("processed")),
        model_success=_non_negative_integer(raw.get("model_success")),
        rule_fallback=_non_negative_integer(raw.get("rule_fallback")),
        budget_fallback=_non_negative_integer(raw.get("budget_fallback")),
        error_counts=dict(sorted(errors.items())),
        recorded=True,
    ), origins
```

Use `candidate_key(row.event_id, row.event_version_number)` for both decision and overview projections. If an item has no matching audit entry, set `chinese_origin=None`; do not guess from whether its text looks Chinese.

- [ ] **Step 4: Update templates and minimal styling**

Add a compact label beside each decision and overview card heading:

```jinja2
{% if item.chinese_origin %}
<span class="chinese-origin chinese-origin-{{ item.chinese_origin.origin }}">
  中文增强：{{ item.chinese_origin.label_zh }}
</span>
{% endif %}
```

Replace the legacy report-level MiniMax paragraph when `recorded` is true:

```jinja2
<p><strong>自动日报中文增强：</strong>
候选 {{ daily_report.chinese_enrichment.candidate_total }} 条 ·
MiniMax 成功 {{ daily_report.chinese_enrichment.model_success }} 条 ·
规则回退 {{ daily_report.chinese_enrichment.rule_fallback }} 条
{% if daily_report.chinese_enrichment.budget_fallback %} · 安全上限回退 {{ daily_report.chinese_enrichment.budget_fallback }} 条{% endif %}。
模型只负责中文表达，不决定确认状态、证据或来源合法性。</p>
```

Retain the old `minimax_degraded` branch only for reports without the new audit summary. Add wrapping styles so long error labels do not overlap titles at desktop or 390px widths.

```css
.chinese-origin {
  display: inline-flex;
  max-width: 100%;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--muted);
  font-size: 0.78rem;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.chinese-origin-model { color: var(--healthy); }
.chinese-origin-rule_fallback,
.chinese-origin-budget_limit { color: var(--blocked); }
```

- [ ] **Step 5: Run web tests and Ruff**

Run: `uv run --extra dev pytest tests/web/test_daily_report_pages.py tests/web/test_daily_autopilot_pages.py -q`

Expected: PASS.

Run: `uv run --extra dev ruff check src/newsradar/web/daily_report_queries.py src/newsradar/web/daily_autopilot_queries.py tests/web/test_daily_report_pages.py tests/web/test_daily_autopilot_pages.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit the diagnostic UI milestone**

```powershell
git add src/newsradar/web/daily_report_queries.py src/newsradar/web/daily_autopilot_queries.py src/newsradar/web/templates/daily_report_detail.html src/newsradar/web/templates/daily_autopilot_detail.html src/newsradar/web/static/styles.css tests/web/test_daily_report_pages.py tests/web/test_daily_autopilot_pages.py
git commit -m "feat: show daily Chinese enrichment diagnostics"
```

---

### Task 5: Complete regression, documentation, and real-browser acceptance

**Files:**
- Modify: `README.md`
- Modify: `tests/acceptance/test_daily_autopilot_content_wave.py`
- Modify: implementation/test files from Tasks 1-4 only when a failing regression proves the change is necessary

**Interfaces:**
- Consumes: all previous task outputs.
- Produces: a fully verified feature branch and a new real automatic daily report proving Chinese content, audit labels, original links, and dual audio.

- [ ] **Step 1: Add the operator-facing workflow documentation**

Append this operator-facing paragraph to the automatic-report section of `README.md`:

```markdown
自动日报在精确事件快照生成后，会对最终进入决策简报或情报全览的唯一事件执行有界中文增强。同一事件在一份日报中最多调用一次文本模型，默认最多处理 60 个事件、并发不超过 2、单条总超时 45 秒；超额、未配置、超时、限流或返回无效时仅回退对应条目并显示中文原因。手动日报生成仍然只读，不会调用文本模型。MiniMax 只生成中文标题和中文文章概述，不能改变来源合法性、事件确认、证据根、收录范围或审核结论。
```

- [ ] **Step 2: Run the full daily-report, event, Worker, and web regression groups**

Run:

```powershell
uv run --extra dev --extra research pytest tests/daily_reports tests/events tests/operations tests/web/test_daily_report_pages.py tests/web/test_daily_autopilot_pages.py tests/acceptance/test_daily_autopilot_content_wave.py -q
```

Expected: PASS with only existing explicit skips/deprecation warnings.

- [ ] **Step 3: Run the complete repository test suite and Ruff**

Run: `uv run --extra dev --extra research pytest -q`

Expected: PASS at 100%, with no failures.

Run: `uv run --extra dev ruff check .`

Expected: `All checks passed!`

Run: `git diff --check HEAD -- src tests docs README.md`

Expected: no output.

- [ ] **Step 4: Commit final documentation or regression-only adjustments**

```powershell
git add README.md
git add tests/acceptance/test_daily_autopilot_content_wave.py
git commit -m "docs: document automatic report Chinese enrichment"
```

Before committing, verify `git diff --cached --name-only` contains no `.env`, `.local`, audio artifact, database file, or user report.

- [ ] **Step 5: Restart the isolated branch runtime and perform real browser acceptance**

Start the feature worktree on a port that does not replace the verified main runtime, for example:

```powershell
uv run newsradar serve --host 127.0.0.1 --port 8768 --worker-id newsradar-chinese-enrichment-acceptance
```

Using the in-app browser, create one new 24-hour automatic report. Verify from visible pages and persisted safe metrics:

- the content wave reaches 41/41 member completion without retrying old runs;
- the report is bound to that exact child Operation;
- every `model` item visibly has a simplified-Chinese title and summary;
- every fallback item shows its specific Chinese reason and later items still complete;
- no consecutive-question-mark corruption appears;
- decision brief, intelligence overview, complete evidence, and clickable public original links remain present;
- both decision and overview audio artifacts reach `succeeded` and expose playable sources;
- the task reaches `succeeded` even when individual model items use safe fallback.

- [ ] **Step 6: Record the acceptance evidence in the handoff without creating a report file**

Report the new autopilot ID, report ID, target success/block counts, event count, Chinese enrichment candidate/success/fallback counts, error-code counts, both audio Operation statuses, pytest result, Ruff result, branch name, and commit list. Do not write into the user-owned `reports/` directory.

Do not merge or push until the user explicitly confirms after reviewing the real webpage.
