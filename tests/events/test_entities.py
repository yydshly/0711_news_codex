import json

import pytest

from newsradar.events.entities import (
    ENTITY_RULE_VERSION,
    canonical_entity_key,
    extract_entities,
)
from newsradar.events.schema import EntityType, RawItemText


def test_entity_aliases_share_a_canonical_key() -> None:
    assert canonical_entity_key("Hugging Face", EntityType.ORGANIZATION) == canonical_entity_key(
        "huggingface", EntityType.ORGANIZATION
    )


def test_extract_entities_preserves_original_mention_and_normalizes_alias() -> None:
    entities = extract_entities(RawItemText(title="HuggingFace launches a new model"))

    assert entities[0].name == "HuggingFace"
    assert entities[0].entity_type is EntityType.ORGANIZATION
    assert entities[0].canonical_key == "organization:huggingface"
    assert entities[0].aliases == ("Hugging Face",)
    assert ENTITY_RULE_VERSION == "entities-v2"


def test_extract_entities_identifies_named_core_object_for_cluster_v2() -> None:
    entities = extract_entities(RawItemText(title="OpenAI launches Orion model"))

    assert [(entity.entity_type, entity.canonical_key) for entity in entities] == [
        (EntityType.ORGANIZATION, "organization:openai"),
        (EntityType.MODEL, "model:orion"),
    ]


def test_model_object_identity_ignores_generic_ai_descriptor() -> None:
    explicit_ai = extract_entities(
        RawItemText(title="OpenAI launches Orion AI model")
    )[-1]
    plain = extract_entities(RawItemText(title="Orion model released by OpenAI"))[-1]

    assert explicit_ai.canonical_key == plain.canonical_key == "model:orion"


def test_extract_entities_does_not_treat_generic_ai_terms_as_organizations() -> None:
    entities = extract_entities(
        RawItemText(title="An AI model agent benchmark improves inference and API tooling")
    )

    assert entities == ()


def test_extract_entities_returns_stable_order_and_deduplicates_aliases() -> None:
    item = RawItemText(title="OpenAI and huggingface partner with Hugging Face")

    assert extract_entities(item) == (
        extract_entities(item)[0],
        extract_entities(item)[1],
    )
    assert [(entity.name, entity.canonical_key) for entity in extract_entities(item)] == [
        ("OpenAI", "organization:openai"),
        ("huggingface", "organization:huggingface"),
    ]


@pytest.mark.parametrize(
    "item",
    [
        RawItemText(summary="OpenAI"),
        RawItemText(content="OpenAI"),
        RawItemText(item_kind="OpenAI"),
        RawItemText(publisher_name="OpenAI"),
        RawItemText(source_topics=("OpenAI",)),
    ],
)
def test_entities_use_each_entity_bearing_pure_input_field(item: RawItemText) -> None:
    assert extract_entities(item)[0].canonical_key == "organization:openai"


def test_entity_extraction_is_byte_equivalent_on_replay() -> None:
    item = RawItemText(title="OpenAI and huggingface", source_topics=("Hugging Face",))

    first = json.dumps(
        [entity.model_dump(mode="json") for entity in extract_entities(item)], separators=(",", ":")
    )
    second = json.dumps(
        [entity.model_dump(mode="json") for entity in extract_entities(item)], separators=(",", ":")
    )

    assert first == second
