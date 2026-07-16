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
    assert ENTITY_RULE_VERSION == "entities-v3"


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


def test_model_object_identity_ignores_lowercase_reasoning_descriptor() -> None:
    launched = extract_entities(
        RawItemText(title="OpenAI launches Orion reasoning model")
    )
    reported = extract_entities(
        RawItemText(title="Orion reasoning model released by OpenAI")
    )

    assert "model:orion" in {entity.canonical_key for entity in launched}
    assert "model:orion" in {entity.canonical_key for entity in reported}


@pytest.mark.parametrize(
    ("title", "expected_key"),
    [
        ("OpenAI releases GPT-5 for developers", "model:gpt-5"),
        ("Anthropic launches Claude 5", "model:claude5"),
        ("Google unveils Gemini 2.5", "model:gemini2.5"),
        ("Alibaba releases Qwen3", "model:qwen3"),
        ("DeepSeek-R1 released with stronger reasoning", "model:deepseek-r1"),
    ],
)
def test_extract_entities_recognizes_common_versioned_models(
    title: str, expected_key: str
) -> None:
    assert expected_key in {
        entity.canonical_key for entity in extract_entities(RawItemText(title=title))
    }


@pytest.mark.parametrize(
    ("title", "expected_key"),
    [
        (
            'Researchers release "Attention Is All You Need for Vision and Language" paper',
            "paper:attentionisallyouneedforvisionandlanguage",
        ),
        (
            'Paper "Scaling Monosemanticity: Extracting Interpretable Features '
            'from Claude 3 Sonnet" released',
            "paper:scalingmonosemanticity:extractinginterpretablefeaturesfromclaude3sonnet",
        ),
        ("openai/codex repository released", "project:openai/codex"),
        ("GitHub project huggingface/transformers launches v5", "project:huggingface/transformers"),
    ],
)
def test_extract_entities_recognizes_papers_and_owner_repositories(
    title: str, expected_key: str
) -> None:
    assert expected_key in {
        entity.canonical_key for entity in extract_entities(RawItemText(title=title))
    }


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
        RawItemText(item_kind="OpenAI"),
        RawItemText(publisher_name="OpenAI"),
        RawItemText(source_topics=("OpenAI",)),
    ],
)
def test_event_entities_ignore_channel_and_source_metadata(item: RawItemText) -> None:
    assert extract_entities(item) == ()


@pytest.mark.parametrize(
    "item",
    [
        RawItemText(title="Google launches Gemini 3"),
        RawItemText(summary="Google launched Gemini 3"),
        RawItemText(content="Google launched Gemini 3"),
    ],
)
def test_event_entities_still_read_news_claim_text(item: RawItemText) -> None:
    assert "organization:google" in {
        entity.canonical_key for entity in extract_entities(item)
    }


def test_google_news_metadata_does_not_make_google_the_event_subject() -> None:
    item = RawItemText(
        title="Thinking Machines releases first model",
        publisher_name="Reuters",
        source_topics=("google", "artificial_intelligence"),
    )
    assert "organization:google" not in {
        entity.canonical_key for entity in extract_entities(item)
    }


def test_entity_extraction_is_byte_equivalent_on_replay() -> None:
    item = RawItemText(title="OpenAI and huggingface", source_topics=("Hugging Face",))

    first = json.dumps(
        [entity.model_dump(mode="json") for entity in extract_entities(item)], separators=(",", ":")
    )
    second = json.dumps(
        [entity.model_dump(mode="json") for entity in extract_entities(item)], separators=(",", ":")
    )

    assert first == second
