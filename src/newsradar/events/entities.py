"""Versioned, deterministic extraction of known AI-news entities."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

from newsradar.events.schema import EntityType, ExtractedEntity, RawItemText

ENTITY_RULE_VERSION = "entities-v1"

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


def canonical_entity_key(name: str, entity_type: EntityType) -> str:
    """Return a stable identity key, folding known organization aliases."""
    normalized_name = _normalized_name(name)
    if entity_type is EntityType.ORGANIZATION:
        normalized_name = _normalized_name(_ORGANIZATION_ALIASES.get(normalized_name, name))
    return f"{entity_type.value}:{normalized_name.replace(' ', '')}"


def extract_entities(item: RawItemText) -> tuple[ExtractedEntity, ...]:
    """Extract known organizations in mention order without network or model calls."""
    text = " ".join(filter(None, (item.title, item.summary, item.content)))
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
    return tuple(entities)


def _organization_mentions(text: str) -> Iterator[tuple[str, str]]:
    matches: list[tuple[int, int, str, str]] = []
    for alias, canonical_name in _ORGANIZATION_ALIASES.items():
        pattern = re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(text):
            matches.append((match.start(), -len(match.group()), match.group(), canonical_name))
    for _, _, mention, canonical_name in sorted(matches):
        yield mention, canonical_name


def _normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
