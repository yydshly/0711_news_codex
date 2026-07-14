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
CONTEXTUAL_AI_TECH_TERMS = frozenset(
    {
        "diffusion",
        "embedding",
        "embeddings",
        "fine tuning",
        "finetuning",
        "inference",
        "training",
        "transformer",
        "transformers",
    }
)
AI_NATIVE_ENTITY_TERMS = frozenset(
    {
        "anthropic",
        "chatgpt",
        "claude",
        "deepseek",
        "gemini",
        "gpt",
        "hugging face",
        "llama",
        "mistral",
        "openai",
        "qwen",
    }
)
CROSS_INDUSTRY_TECH_ENTITY_TERMS = frozenset({"nvidia"})
CROSS_INDUSTRY_AI_CONTEXT_TERMS = frozenset({"gpu", "model"})
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
ADVERTISEMENT_CTA_TERMS = frozenset(
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
    subject_text = title or text

    strong_matches = _matching_terms(text, STRONG_AI_TERMS)
    contextual_tech_matches = _matching_terms(text, CONTEXTUAL_AI_TECH_TERMS)
    native_ai_entities = _matching_terms(text, AI_NATIVE_ENTITY_TERMS)
    cross_industry_entities = _matching_terms(text, CROSS_INDUSTRY_TECH_ENTITY_TERMS)
    recognized_entities = native_ai_entities + cross_industry_entities
    ambiguous_matches = _matching_terms(text, AMBIGUOUS_TERMS)
    event_actions = _matching_terms(text, EVENT_ACTION_TERMS)
    contextual_source_signal = bool(
        ambiguous_matches
        and _matching_terms(title, AMBIGUOUS_TERMS)
        and _matching_terms(title, EVENT_ACTION_TERMS)
        and _has_ai_source_context(source_topics)
    )

    entity_action_signal = bool(
        not strong_matches and native_ai_entities and event_actions
    )
    cross_industry_ai_signal = bool(
        not strong_matches
        and cross_industry_entities
        and event_actions
        and (
            contextual_tech_matches
            or _matching_terms(text, CROSS_INDUSTRY_AI_CONTEXT_TERMS)
        )
    )
    contextual_tech_signal = bool(
        not strong_matches
        and contextual_tech_matches
        and (recognized_entities or _matching_terms(text, RESEARCH_TERMS))
    )
    qualified_ambiguous_signal = bool(
        not strong_matches and ambiguous_matches and contextual_source_signal
    )
    has_qualifying_signal = bool(
        strong_matches
        or entity_action_signal
        or cross_industry_ai_signal
        or contextual_tech_signal
        or qualified_ambiguous_signal
    )
    score = min(
        100,
        60 * has_qualifying_signal
        + 20 * bool(recognized_entities)
        + 20 * bool(event_actions),
    )
    exclusion_reasons = _exclusion_reasons(
        text=text,
        has_qualifying_signal=has_qualifying_signal,
        has_native_ai_entity=bool(native_ai_entities),
        has_cross_industry_entity=bool(cross_industry_entities),
        has_explicit_ai_event_subject=_has_explicit_ai_event_subject(subject_text),
        ambiguous_matches=ambiguous_matches,
        subject_text=subject_text,
    )
    is_relevant = not exclusion_reasons and score >= 60
    if is_relevant:
        reasons = tuple(
            reason
            for present, reason in (
                (bool(strong_matches), "strong_ai_signal"),
                (entity_action_signal, "qualified_ai_entity_action"),
                (cross_industry_ai_signal, "qualified_cross_industry_ai_context"),
                (contextual_tech_signal, "qualified_ai_technical_signal"),
                (qualified_ambiguous_signal, "qualified_ambiguous_signal"),
                (bool(recognized_entities), "recognized_ai_entity"),
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
    has_native_ai_entity: bool,
    has_cross_industry_entity: bool,
    has_explicit_ai_event_subject: bool,
    ambiguous_matches: tuple[str, ...],
    subject_text: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if len(text) < 4:
        reasons.append("insufficient_text")
    if (
        _matching_terms(subject_text, ENTERTAINMENT_TERMS)
        and not has_explicit_ai_event_subject
    ):
        reasons.append("game_or_entertainment")
    if _is_advertisement_or_subscription(
        text, subject_text, has_explicit_ai_event_subject
    ):
        reasons.append("advertisement_or_subscription")
    if _is_auto_repost_without_claim(text):
        reasons.append("auto_repost_without_claim")
    has_recognized_entity = has_native_ai_entity or has_cross_industry_entity
    if ambiguous_matches and not has_qualifying_signal and not has_recognized_entity:
        reasons.append("ambiguous_term_only")
    elif (
        _matching_terms(text, GENERIC_TECHNOLOGY_TERMS)
        and not has_qualifying_signal
        and not has_recognized_entity
    ):
        reasons.append("generic_technology")
    elif not has_qualifying_signal and has_native_ai_entity:
        reasons.append("ai_entity_without_event_context")
    elif not has_qualifying_signal and has_cross_industry_entity:
        reasons.append("technology_entity_without_ai_context")
    elif not has_qualifying_signal:
        reasons.append("no_ai_signal")
    return tuple(reasons)


def _has_explicit_ai_event_subject(subject_text: str) -> bool:
    actions = _matching_terms(subject_text, EVENT_ACTION_TERMS)
    if not actions:
        return False
    if _matching_terms(subject_text, STRONG_AI_TERMS):
        return True
    if _matching_terms(subject_text, AI_NATIVE_ENTITY_TERMS):
        return True
    return bool(
        _matching_terms(subject_text, CROSS_INDUSTRY_TECH_ENTITY_TERMS)
        and (
            _matching_terms(subject_text, CONTEXTUAL_AI_TECH_TERMS)
            or _matching_terms(subject_text, CROSS_INDUSTRY_AI_CONTEXT_TERMS)
        )
    )


def _is_advertisement_or_subscription(
    text: str, subject_text: str, has_explicit_ai_event_subject: bool
) -> bool:
    subject_cta = _matching_terms(subject_text, ADVERTISEMENT_CTA_TERMS)
    if subject_cta:
        return True
    return bool(
        _matching_terms(text, ADVERTISEMENT_CTA_TERMS)
        and not has_explicit_ai_event_subject
    )


def _is_auto_repost_without_claim(text: str) -> bool:
    tokens = text.split()
    return bool(tokens and tokens[0] in {"repost", "rt"} and len(tokens) <= 8)


def _has_ai_source_context(source_topics: str) -> bool:
    return bool(
        _matching_terms(source_topics, STRONG_AI_TERMS)
        or _matching_terms(source_topics, AI_NATIVE_ENTITY_TERMS)
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
