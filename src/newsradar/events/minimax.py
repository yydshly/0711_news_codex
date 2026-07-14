"""Optional, advisory MiniMax enrichment for already-rule-processed event candidates."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel

from newsradar.ai.minimax import UNTRUSTED_PREAMBLE, MiniMaxClient, ModelUsage
from newsradar.events.schema import (
    CandidateCluster,
    ConflictExplanation,
    EntitySuggestions,
    EventEnrichment,
    PairSemanticDecision,
)
from newsradar.settings import Settings


@dataclass(frozen=True)
class EventModelRun:
    """Bounded metadata for a durable event_model_runs sink."""

    stage: str
    usage: ModelUsage


@dataclass(frozen=True)
class EventEnrichmentResult:
    """One candidate's isolated editorial result and safe model-attempt audit."""

    enrichment: EventEnrichment
    model_runs: tuple[EventModelRun, ...] = ()


EventModelRunSink = Callable[[EventModelRun], None]
EventEnrichmentCallable = Callable[
    [CandidateCluster, EventEnrichment],
    Awaitable[EventEnrichmentResult | EventEnrichment],
]
T = TypeVar("T", bound=BaseModel)


class EventEnrichmentBatch:
    """Run candidate-only editorial enrichment with bounded, isolated concurrency."""

    def __init__(
        self,
        adapter: EventEnrichmentCallable,
        max_concurrency: int = 2,
        *,
        fallback_model: str = "MiniMax-M2.7-highspeed",
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self._adapter = adapter
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._fallback_model = fallback_model

    async def enrich(
        self, candidates: tuple[CandidateCluster, ...]
    ) -> dict[str, EventEnrichmentResult]:
        from newsradar.events.publishing import rule_enrichment

        async def enrich_one(
            candidate: CandidateCluster,
        ) -> tuple[str, EventEnrichmentResult]:
            fallback = rule_enrichment(candidate)
            async with self._semaphore:
                try:
                    result = await self._adapter(candidate, fallback)
                    if isinstance(result, EventEnrichment):
                        result = EventEnrichmentResult(enrichment=result)
                    if not isinstance(result, EventEnrichmentResult):
                        raise TypeError(
                            "event enrichment adapter returned an invalid result"
                        )
                except Exception:
                    usage = ModelUsage(
                        purpose="event_enrichment",
                        model=self._fallback_model,
                        input_tokens=0,
                        output_tokens=0,
                        latency_ms=0,
                        outcome="fallback",
                        error="unexpected_error",
                    )
                    result = EventEnrichmentResult(
                        enrichment=fallback,
                        model_runs=(
                            EventModelRun(stage=usage.purpose, usage=usage),
                        ),
                    )
                return candidate.candidate_key, result

        rows = await asyncio.gather(*(enrich_one(candidate) for candidate in candidates))
        return dict(rows)


class EventMiniMaxAdapter:
    """Optional model helper that cannot decide event evidence or publication policy."""

    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient,
        event_run_sink: EventModelRunSink | None = None,
    ) -> None:
        if settings.event_model_max_concurrency <= 0:
            raise ValueError("event_model_max_concurrency must be positive")
        self.settings = settings
        self.event_run_sink = event_run_sink
        self._semaphore = asyncio.Semaphore(settings.event_model_max_concurrency)
        self.client = MiniMaxClient(settings, http, self._record_usage)

    async def enrich_event(
        self, candidate: CandidateCluster, rule_fallback: EventEnrichment
    ) -> EventEnrichment:
        prompt = self._prompt(
            "Enrich this already-selected event candidate. This is editorial assistance only; "
            "do not decide source compliance, confirmation, or publication.\n",
            candidate,
            EventEnrichment,
        )
        result = await self._structured_call(
            "event_enrichment",
            self.settings.minimax_fast_model,
            prompt,
            EventEnrichment,
            rule_fallback,
            self.settings.event_model_timeout_seconds,
        )
        return (
            result.model_copy(update={"origin": "model"})
            if result is not rule_fallback
            else result
        )

    async def compare_candidate_pair(
        self, left: CandidateCluster, right: CandidateCluster
    ) -> PairSemanticDecision:
        fallback = PairSemanticDecision(
            same_event=False,
            confidence=0,
            rationale="Rule fallback: semantic comparison unavailable",
        )
        prompt = (
            f"{UNTRUSTED_PREAMBLE}\nCompare the candidate pair as advisory context only. "
            "Do not merge candidates or decide evidence compliance.\n"
            f"Candidate A:\n{self._context(left)}\nCandidate B:\n{self._context(right)}\n"
            f"JSON schema: {json.dumps(PairSemanticDecision.model_json_schema())}"
        )
        result = await self._structured_call(
            "event_pair_comparison",
            self.settings.minimax_fast_model,
            prompt,
            PairSemanticDecision,
            fallback,
            self.settings.event_model_timeout_seconds,
        )
        return result.model_copy(update={"origin": "model"}) if result is not fallback else result

    async def suggest_entities(self, candidate: CandidateCluster) -> EntitySuggestions:
        fallback = EntitySuggestions()
        prompt = self._prompt(
            "Suggest possible named entities for deterministic validation. "
            "Do not decide relevance, confirmation, or publication.\n",
            candidate,
            EntitySuggestions,
        )
        result = await self._structured_call(
            "event_entity_suggestions",
            self.settings.minimax_fast_model,
            prompt,
            EntitySuggestions,
            fallback,
            self.settings.event_model_timeout_seconds,
        )
        return result.model_copy(update={"origin": "model"}) if result is not fallback else result

    async def explain_conflict(self, candidate: CandidateCluster) -> ConflictExplanation:
        if not bool(candidate.metadata.get("disputed")) and not any(
            "conflict" in reason.casefold() for reason in candidate.reasons
        ):
            raise ValueError("M3 conflict explanation requires a rule-disputed candidate")
        fallback = ConflictExplanation(
            summary="Rule fallback: conflicting evidence requires human review",
            limitations=("Model explanation unavailable",),
        )
        prompt = self._prompt(
            "Explain the reported conflict for a human reviewer. This explanation cannot "
            "decide source compliance, confirmation, or publication.\n",
            candidate,
            ConflictExplanation,
        )
        result = await self._structured_call(
            "event_conflict_explanation",
            self.settings.minimax_deep_model,
            prompt,
            ConflictExplanation,
            fallback,
            self.settings.event_model_timeout_seconds,
        )
        return result.model_copy(update={"origin": "model"}) if result is not fallback else result

    def _record_usage(self, usage: ModelUsage) -> None:
        if self.event_run_sink:
            try:
                self.event_run_sink(EventModelRun(stage=usage.purpose, usage=usage))
            except Exception:
                return

    async def _structured_call(
        self,
        purpose: str,
        model: str,
        prompt: str,
        response_type: type[T],
        fallback: T,
        timeout_seconds: float,
    ) -> T:
        async with self._semaphore:
            return await self.client.structured(
                purpose,
                model,
                prompt,
                response_type,
                fallback,
                timeout_seconds,
            )

    @staticmethod
    def _prompt(instruction: str, candidate: CandidateCluster, response_type: type) -> str:
        return (
            f"{UNTRUSTED_PREAMBLE}\n{instruction}Candidate facts:\n"
            f"{EventMiniMaxAdapter._context(candidate)}\n"
            f"JSON schema: {json.dumps(response_type.model_json_schema())}"
        )

    @staticmethod
    def _context(candidate: CandidateCluster) -> str:
        """Bound prompt input; no metadata, payloads, environment, or full raw content."""
        lines = [
            "untrusted_candidate_title: "
            f"{EventMiniMaxAdapter._bounded_title(candidate.title)}"
        ]
        for item in candidate.items[:5]:
            lines.append(
                "untrusted_evidence_title: "
                f"id={item.raw_item_id}; "
                f"title={EventMiniMaxAdapter._bounded_title(item.title)}"
            )
        return "\n".join(lines)

    @staticmethod
    def _bounded_title(value: str) -> str:
        without_url_queries = re.sub(
            r"(https?://[^\s?#]+)[?#][^\s]*",
            r"\1",
            value,
            flags=re.IGNORECASE,
        )
        return without_url_queries[:500]
