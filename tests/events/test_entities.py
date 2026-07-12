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
    assert ENTITY_RULE_VERSION == "entities-v1"


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
