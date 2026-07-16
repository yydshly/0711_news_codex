"""Versioned, deterministic extraction of known AI-news entities."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

from newsradar.events.schema import EntityType, ExtractedEntity, RawItemText

ENTITY_RULE_VERSION = "entities-v3"

_ORGANIZATION_ALIASES = {
    "anthropic": "Anthropic",
    "deepmind": "DeepMind",
    "google": "Google",
    "hugging face": "Hugging Face",
    "huggingface": "Hugging Face",
    "meta": "Meta",
    "microsoft": "Microsoft",
    "mistral ai": "Mistral AI",
    "nvidia": "NVIDIA",
    "openai": "OpenAI",
    "xai": "xAI",
}
_GENERIC_AI_TERMS = frozenset(
    {"agent", "ai", "api", "benchmark", "inference", "llm", "model", "multimodal"}
)
_GENERIC_OBJECT_NAME_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "new",
        "ai",
        "artificial",
        "generative",
        "github",
        "intelligence",
    }
)
_GENERIC_OBJECT_SUFFIXES = frozenset({"ai", "generative", "llm", "reasoning"})


def canonical_entity_key(name: str, entity_type: EntityType) -> str:
    """Return a stable identity key, folding known organization aliases."""
    normalized_name = _normalized_name(name)
    if entity_type is EntityType.ORGANIZATION:
        normalized_name = _normalized_name(_ORGANIZATION_ALIASES.get(normalized_name, name))
    return f"{entity_type.value}:{normalized_name.replace(' ', '')}"


def extract_entities(item: RawItemText) -> tuple[ExtractedEntity, ...]:
    """Extract audited organizations and explicit named core objects deterministically."""
    text = " ".join(_item_text_parts(item))
    entities: list[ExtractedEntity] = []
    seen_keys: set[str] = set()
    for mention, canonical_name in _organization_mentions(text):
        if _normalized_name(mention) in _GENERIC_AI_TERMS:
            continue
        key = canonical_entity_key(canonical_name, EntityType.ORGANIZATION)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        aliases = () if mention == canonical_name else (canonical_name,)
        entities.append(
            ExtractedEntity(
                canonical_key=key,
                name=mention,
                entity_type=EntityType.ORGANIZATION,
                aliases=aliases,
                confidence=1.0,
            )
        )
    for mention, entity_type in _typed_object_mentions(text):
        key = canonical_entity_key(mention, entity_type)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        entities.append(
            ExtractedEntity(
                canonical_key=key,
                name=mention,
                entity_type=entity_type,
                confidence=0.9,
            )
        )
    for mention, entity_type in (
        *_known_model_mentions(text),
        *_paper_mentions(text),
        *_repository_mentions(text),
    ):
        key = canonical_entity_key(mention, entity_type)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        entities.append(
            ExtractedEntity(
                canonical_key=key,
                name=mention,
                entity_type=entity_type,
                confidence=1.0,
            )
        )
    return tuple(entities)


def _organization_mentions(text: str) -> Iterator[tuple[str, str]]:
    matches: list[tuple[int, int, str, str]] = []
    for alias, canonical_name in _ORGANIZATION_ALIASES.items():
        pattern = re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(text):
            matches.append((match.start(), -len(match.group()), match.group(), canonical_name))
    for _, _, mention, canonical_name in sorted(matches):
        yield mention, canonical_name


def _typed_object_mentions(text: str) -> Iterator[tuple[str, EntityType]]:
    entity_types = {
        "product": EntityType.PRODUCT,
        "model": EntityType.MODEL,
        "paper": EntityType.PAPER,
        "dataset": EntityType.DATASET,
        "project": EntityType.PROJECT,
    }
    pattern = re.compile(
        r"(?<!\w)(?P<name>[A-Z][A-Za-z0-9.-]*(?:\s+[A-Z0-9][A-Za-z0-9.-]*){0,3})"
        r"(?:\s+(?P<descriptor>reasoning))?"
        r"\s+(?P<kind>product|model|paper|dataset|project)\b"
    )
    for match in pattern.finditer(text):
        mention_words = match.group("name").strip(" .-").split()
        if match.group("descriptor"):
            mention_words.append(match.group("descriptor"))
        while len(mention_words) > 1 and mention_words[-1].casefold() in _GENERIC_OBJECT_SUFFIXES:
            mention_words.pop()
        mention = " ".join(mention_words)
        normalized = _normalized_name(mention)
        if normalized in _GENERIC_AI_TERMS or set(normalized.split()) <= _GENERIC_OBJECT_NAME_WORDS:
            continue
        yield mention, entity_types[match.group("kind").casefold()]


def _known_model_mentions(text: str) -> tuple[tuple[str, EntityType], ...]:
    patterns = (
        r"\bGPT-\d+(?:\.\d+)?(?:-[A-Za-z0-9]+)?\b",
        r"\bClaude\s+\d+(?:\.\d+)?(?:\s+(?:Sonnet|Opus|Haiku))?\b",
        r"\bGemini\s+\d+(?:\.\d+)?(?:\s+(?:Pro|Flash|Ultra))?\b",
        r"\bQwen-?\d+(?:\.\d+)?(?:-[A-Za-z0-9]+)?\b",
        r"\bDeepSeek-?(?:R\d+|V\d+(?:\.\d+)?)\b",
    )
    matches: list[tuple[int, str]] = []
    for pattern in patterns:
        matches.extend(
            (match.start(), match.group())
            for match in re.finditer(pattern, text, re.IGNORECASE)
        )
    return tuple(
        (mention, EntityType.MODEL) for _, mention in sorted(set(matches))
    )


def _paper_mentions(text: str) -> tuple[tuple[str, EntityType], ...]:
    patterns = (
        re.compile(r"[\"“](?P<title>[^\"”\n]{10,240})[\"”]\s+paper\b", re.IGNORECASE),
        re.compile(r"\bpaper\s+[\"“](?P<title>[^\"”\n]{10,240})[\"”]", re.IGNORECASE),
    )
    matches = {
        (match.start("title"), match.group("title").strip())
        for pattern in patterns
        for match in pattern.finditer(text)
    }
    return tuple((title, EntityType.PAPER) for _, title in sorted(matches))


def _repository_mentions(text: str) -> tuple[tuple[str, EntityType], ...]:
    matches = re.finditer(
        r"(?<![\w/])(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?![\w/])",
        text,
    )
    return tuple((match.group("repo"), EntityType.PROJECT) for match in matches)


def _normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _item_text_parts(item: RawItemText) -> tuple[str, ...]:
    return tuple(filter(None, (item.title, item.summary, item.content)))
