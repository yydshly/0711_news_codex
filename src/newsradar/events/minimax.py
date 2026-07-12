"""Optional, advisory MiniMax enrichment for already-rule-processed event candidates."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
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


EventModelRunSink = Callable[[EventModelRun], None]
T = TypeVar("T", bound=BaseModel)


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
            f"candidate_key: {candidate.candidate_key[:255]}",
            f"title: {candidate.title[:500]}",
            f"reasons: {', '.join(candidate.reasons[:5])[:500]}",
        ]
        for item in candidate.items[:5]:
            lines.append(
                "item: "
                f"id={item.raw_item_id}; title={item.title[:500]}; "
                f"publisher={(item.publisher_name or '')[:200]}; "
                f"entities={', '.join(item.entities[:10])[:300]}"
            )
        return "\n".join(lines)
