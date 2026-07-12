import json

import pytest

from newsradar.events.relevance import RELEVANCE_RULE_VERSION, evaluate_relevance
from newsradar.events.schema import RawItemText


@pytest.mark.parametrize(
    "title",
    [
        "New multimodal model API released",
        "Agent framework adds tool calling",
        "Benchmark evaluates long-context reasoning",
    ],
)
def test_ai_relevance_positive_samples(title: str) -> None:
    assert evaluate_relevance(RawItemText(title=title)).is_relevant


def test_ai_relevance_rejects_generic_business_news() -> None:
    result = evaluate_relevance(
        RawItemText(title="Company reports quarterly revenue", summary="", content="")
    )

    assert result.is_relevant is False
    assert result.score == 0
    assert result.topics == ()
    assert result.reasons == ("no_ai_signal",)


def test_relevance_uses_sorted_matches_and_rule_topics() -> None:
    result = evaluate_relevance(
        RawItemText(title="Benchmark model API release", summary="", content="")
    )

    assert result.score == 75
    assert result.topics == ("product", "research")
    assert result.reasons == ("matched:api", "matched:benchmark", "matched:model")
    assert RELEVANCE_RULE_VERSION == "relevance-v1"


def test_relevance_decision_is_byte_equivalent_on_replay() -> None:
    item = RawItemText(title="New model API release", summary="SDK preview", content="")

    first = json.dumps(evaluate_relevance(item).model_dump(), separators=(",", ":"))
    second = json.dumps(evaluate_relevance(item).model_dump(), separators=(",", ":"))

    assert first == second


@pytest.mark.parametrize(
    "item",
    [
        RawItemText(summary="model"),
        RawItemText(content="model"),
        RawItemText(item_kind="model"),
        RawItemText(publisher_name="OpenAI model updates"),
        RawItemText(source_topics=("model",)),
    ],
)
def test_relevance_uses_each_pure_input_field(item: RawItemText) -> None:
    assert evaluate_relevance(item).is_relevant


def test_relevance_matches_terms_at_word_boundaries_only() -> None:
    result = evaluate_relevance(RawItemText(title="Models improve deployment"))

    assert result.is_relevant is False
    assert result.reasons == ("no_ai_signal",)


def test_relevance_normalizes_case_punctuation_and_whitespace() -> None:
    result = evaluate_relevance(RawItemText(title="  MODEL—API\n"))

    assert result.reasons == ("matched:api", "matched:model")
