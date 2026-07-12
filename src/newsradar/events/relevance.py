"""Versioned, deterministic AI-news relevance rules."""

from __future__ import annotations

import re
import unicodedata
from html import unescape

from newsradar.events.schema import RawItemText, RelevanceDecision

RELEVANCE_RULE_VERSION = "relevance-v1"
AI_TERMS = frozenset({"llm", "model", "inference", "agent", "multimodal", "benchmark", "api"})
RESEARCH_TERMS = frozenset({"paper", "arxiv", "dataset", "evaluation", "benchmark"})
PRODUCT_TERMS = frozenset({"release", "launch", "available", "api", "sdk", "preview"})


def normalize_text(value: str) -> str:
    """Return case-normalized text with punctuation treated as token boundaries."""
    normalized = unicodedata.normalize("NFKC", unescape(value)).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).split())


def evaluate_relevance(item: RawItemText) -> RelevanceDecision:
    """Classify a normalized item using local, explainable relevance rules."""
    text = normalize_text(" ".join(filter(None, (item.title, item.summary, item.content))))
    matched = tuple(sorted(term for term in AI_TERMS if _contains_term(text, term)))
    score = min(100, len(matched) * 25)
    return RelevanceDecision(
        is_relevant=score >= 25,
        score=score,
        topics=infer_rule_topics(text),
        reasons=tuple(f"matched:{term}" for term in matched) or ("no_ai_signal",),
    )


def infer_rule_topics(text: str) -> tuple[str, ...]:
    """Return sorted topic labels for the rule groups present in *text*."""
    topics = set()
    if any(_contains_term(text, term) for term in PRODUCT_TERMS):
        topics.add("product")
    if any(_contains_term(text, term) for term in RESEARCH_TERMS):
        topics.add("research")
    return tuple(sorted(topics))


def _contains_term(text: str, term: str) -> bool:
    return f" {term} " in f" {text} "
