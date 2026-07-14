"""Versioned, deterministic AI-news relevance rules."""

from __future__ import annotations

import re
import unicodedata
from html import unescape

from newsradar.events.schema import RawItemText, RelevanceDecision

RELEVANCE_RULE_VERSION = "relevance-v2"

TITLE_MAX_CHARS = 500
SUMMARY_MAX_CHARS = 2_000
CONTENT_MAX_CHARS = 10_000
ITEM_KIND_MAX_CHARS = 120
PUBLISHER_MAX_CHARS = 255
SOURCE_TOPIC_MAX_CHARS = 120

STRONG_AI_TERMS = frozenset(
    {
        "ai",
        "artificial intelligence",
        "machine learning",
        "generative ai",
        "large language model",
        "large language models",
        "llm",
        "llms",
        "inference",
        "training",
        "fine tuning",
        "finetuning",
        "embedding",
        "embeddings",
        "transformer",
        "transformers",
        "diffusion",
        "multimodal",
        "rag",
        "ai benchmark",
        "neural network",
        "neural networks",
        "foundation model",
        "foundation models",
        "agentic",
    }
)
AI_ENTITY_TERMS = frozenset(
    {
        "anthropic",
        "chatgpt",
        "claude",
        "deepseek",
        "gemini",
        "hugging face",
        "llama",
        "mistral",
        "openai",
        "qwen",
    }
)
AMBIGUOUS_TERMS = frozenset(
    {"agent", "agents", "api", "apis", "assistant", "automation", "chip", "gpu", "model"}
)
RESEARCH_TERMS = frozenset(
    {"paper", "arxiv", "dataset", "evaluation", "evaluates", "benchmark", "research"}
)
PRODUCT_TERMS = frozenset(
    {
        "release",
        "released",
        "releases",
        "launch",
        "launched",
        "launches",
        "available",
        "api",
        "sdk",
        "preview",
        "unveil",
        "unveiled",
        "unveils",
    }
)
EVENT_ACTION_TERMS = frozenset(
    {
        "announce",
        "announced",
        "announces",
        "benchmark",
        "evaluates",
        "evaluation",
        "funding",
        "funded",
        "publishes",
        "published",
        "release",
        "released",
        "releases",
        "raises",
        "research",
        "safety",
        "launch",
        "launched",
        "launches",
        "unveil",
        "unveiled",
        "unveils",
    }
)
ENTERTAINMENT_TERMS = frozenset(
    {
        "actor",
        "actress",
        "episode",
        "film",
        "game",
        "gaming",
        "goldeneye",
        "movie",
        "netflix",
        "nintendo",
        "playstation",
        "sequel",
        "steam",
        "television",
        "trailer",
        "xbox",
    }
)
ADVERTISEMENT_TERMS = frozenset(
    {
        "buy now",
        "coupon",
        "deal",
        "deals",
        "discount",
        "limited time",
        "offer",
        "sale",
        "sponsored",
        "subscribe",
        "subscription",
    }
)
GENERIC_TECHNOLOGY_TERMS = frozenset(
    {"browser", "gadget", "laptop", "phone", "smartphone", "technology", "telecom"}
)


def normalize_text(value: str) -> str:
    """Return case-normalized text with punctuation treated as token boundaries."""
    normalized = unicodedata.normalize("NFKC", unescape(value)).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).split())


def evaluate_relevance(item: RawItemText) -> RelevanceDecision:
    """Classify bounded item text using local, explainable relevance rules."""
    text = normalize_text(" ".join(_bounded_item_text_parts(item)))
    title = normalize_text(item.title[:TITLE_MAX_CHARS])
    source_topics = normalize_text(
        " ".join(topic[:SOURCE_TOPIC_MAX_CHARS] for topic in item.source_topics)
    )

    strong_matches = _matching_terms(text, STRONG_AI_TERMS)
    ai_entities = _matching_terms(text, AI_ENTITY_TERMS)
    ambiguous_matches = _matching_terms(text, AMBIGUOUS_TERMS)
    event_actions = _matching_terms(text, EVENT_ACTION_TERMS)
    contextual_source_signal = bool(
        ambiguous_matches
        and _matching_terms(title, AMBIGUOUS_TERMS)
        and _matching_terms(title, EVENT_ACTION_TERMS)
        and _has_ai_source_context(source_topics)
    )

    qualified_ambiguous_signal = bool(
        not strong_matches
        and ambiguous_matches
        and (ai_entities or contextual_source_signal)
    )
    has_qualifying_signal = bool(strong_matches) or qualified_ambiguous_signal
    score = min(
        100,
        60 * has_qualifying_signal
        + 20 * bool(ai_entities)
        + 20 * bool(event_actions),
    )
    exclusion_reasons = _exclusion_reasons(
        text=text,
        has_qualifying_signal=has_qualifying_signal,
        has_ai_entity=bool(ai_entities),
        ambiguous_matches=ambiguous_matches,
    )
    is_relevant = not exclusion_reasons and score >= 60
    if is_relevant:
        reasons = tuple(
            reason
            for present, reason in (
                (bool(strong_matches), "strong_ai_signal"),
                (qualified_ambiguous_signal, "qualified_ambiguous_signal"),
                (bool(ai_entities), "recognized_ai_entity"),
                (bool(event_actions), "event_action"),
            )
            if present
        )
    else:
        reasons = exclusion_reasons or ("no_ai_signal",)
    return RelevanceDecision(
        is_relevant=is_relevant,
        outcome="included" if is_relevant else "excluded",
        score=score,
        topics=infer_rule_topics(text),
        reasons=reasons,
    )


def infer_rule_topics(text: str) -> tuple[str, ...]:
    """Return sorted topic labels for the rule groups present in *text*."""
    topics = set()
    if _matching_terms(text, PRODUCT_TERMS):
        topics.add("product")
    if _matching_terms(text, RESEARCH_TERMS):
        topics.add("research")
    return tuple(sorted(topics))


def _exclusion_reasons(
    *,
    text: str,
    has_qualifying_signal: bool,
    has_ai_entity: bool,
    ambiguous_matches: tuple[str, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if len(text) < 4:
        reasons.append("insufficient_text")
    if _matching_terms(text, ENTERTAINMENT_TERMS):
        reasons.append("game_or_entertainment")
    if _matching_terms(text, ADVERTISEMENT_TERMS):
        reasons.append("advertisement_or_subscription")
    if _is_auto_repost_without_claim(text):
        reasons.append("auto_repost_without_claim")
    if ambiguous_matches and not has_qualifying_signal and not has_ai_entity:
        reasons.append("ambiguous_term_only")
    elif (
        _matching_terms(text, GENERIC_TECHNOLOGY_TERMS)
        and not has_qualifying_signal
        and not has_ai_entity
    ):
        reasons.append("generic_technology")
    elif not has_qualifying_signal and not has_ai_entity:
        reasons.append("no_ai_signal")
    return tuple(reasons)


def _is_auto_repost_without_claim(text: str) -> bool:
    tokens = text.split()
    return bool(tokens and tokens[0] in {"repost", "rt"} and len(tokens) <= 8)


def _has_ai_source_context(source_topics: str) -> bool:
    return bool(
        _matching_terms(source_topics, STRONG_AI_TERMS)
        or _matching_terms(source_topics, AI_ENTITY_TERMS)
    )


def _matching_terms(text: str, terms: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(term for term in terms if _contains_term(text, term)))


def _contains_term(text: str, term: str) -> bool:
    return f" {term} " in f" {text} "


def _bounded_item_text_parts(item: RawItemText) -> tuple[str, ...]:
    return tuple(
        filter(
            None,
            (
                item.title[:TITLE_MAX_CHARS],
                item.summary[:SUMMARY_MAX_CHARS],
                item.content[:CONTENT_MAX_CHARS],
                (item.item_kind or "")[:ITEM_KIND_MAX_CHARS],
                (item.publisher_name or "")[:PUBLISHER_MAX_CHARS],
            ),
        )
    )
