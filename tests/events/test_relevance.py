import json

import pytest

from newsradar.events.relevance import RELEVANCE_RULE_VERSION, evaluate_relevance
from newsradar.events.schema import RawItemText


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        (
            "Agent 64 is the GoldenEye successor arriving next month",
            "game_or_entertainment",
        ),
        ("Model railway exhibition opens this weekend", "ambiguous_term_only"),
        (
            "Subscribe now for weekly technology deals",
            "advertisement_or_subscription",
        ),
        ("Agent under fire", "ambiguous_term_only"),
    ],
)
def test_relevance_v2_rejects_ambiguous_non_ai_items(title: str, reason: str) -> None:
    result = evaluate_relevance(RawItemText(title=title, source_topics=("ai",)))

    assert result.is_relevant is False
    assert result.outcome == "excluded"
    assert reason in result.reasons


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("New smartphone browser features arrive", "generic_technology"),
        ("RT link only", "auto_repost_without_claim"),
        ("#", "insufficient_text"),
    ],
)
def test_relevance_v2_uses_stable_non_ai_exclusion_reasons(
    title: str, reason: str
) -> None:
    result = evaluate_relevance(RawItemText(title=title))

    assert result.outcome == "excluded"
    assert reason in result.reasons


@pytest.mark.parametrize(
    "title",
    [
        "OpenAI launches a new multimodal model API",
        "Anthropic releases an AI coding agent SDK",
        "Benchmark evaluates inference efficiency for LLMs",
    ],
)
def test_relevance_v2_keeps_explicit_ai_events(title: str) -> None:
    result = evaluate_relevance(RawItemText(title=title))

    assert result.is_relevant is True
    assert result.outcome == "included"
    assert result.score >= 60


def test_source_topic_cannot_make_an_ambiguous_term_relevant_by_itself() -> None:
    result = evaluate_relevance(
        RawItemText(title="Agent overview", source_topics=("ai",))
    )

    assert result.outcome == "excluded"
    assert result.score < 60
    assert "ambiguous_term_only" in result.reasons


def test_ambiguous_term_and_ai_entity_still_need_an_event_action() -> None:
    result = evaluate_relevance(RawItemText(title="OpenAI model roadmap"))

    assert result.outcome == "excluded"
    assert result.score < 60


@pytest.mark.parametrize(
    "title",
    [
        "Google launches Gemini 3",
        "Anthropic releases Claude SDK",
        "OpenAI publishes benchmark",
    ],
)
def test_ai_entity_and_event_action_form_a_qualifying_signal(title: str) -> None:
    result = evaluate_relevance(RawItemText(title=title))

    assert result.outcome == "included"
    assert result.score >= 60
    assert "no_ai_signal" not in result.reasons


def test_ai_entity_without_event_action_is_not_automatically_included() -> None:
    result = evaluate_relevance(RawItemText(title="Anthropic Claude overview"))

    assert result.outcome == "excluded"
    assert result.score < 60


def test_entertainment_word_does_not_override_explicit_ai_event_subject() -> None:
    result = evaluate_relevance(
        RawItemText(title="OpenAI launches GPT-5 API for game developers")
    )

    assert result.outcome == "included"
    assert "game_or_entertainment" not in result.reasons


def test_entertainment_title_remains_subject_despite_ai_terms_in_summary() -> None:
    result = evaluate_relevance(
        RawItemText(
            title="Agent 64 is the GoldenEye successor arriving next month",
            summary="OpenAI launches an AI API for game developers",
        )
    )

    assert result.outcome == "excluded"
    assert "game_or_entertainment" in result.reasons


@pytest.mark.parametrize(
    "title",
    [
        "Transformer fire disrupts city power grid",
        "Employee training schedule updated",
    ],
)
def test_ambiguous_technical_terms_need_ai_event_context(title: str) -> None:
    result = evaluate_relevance(RawItemText(title=title))

    assert result.outcome == "excluded"
    assert result.score < 60


@pytest.mark.parametrize(
    "title",
    [
        "Anthropic publishes transformer research",
        "Researchers release diffusion benchmark",
    ],
)
def test_ambiguous_technical_terms_keep_explicit_ai_research_events(title: str) -> None:
    result = evaluate_relevance(RawItemText(title=title))

    assert result.outcome == "included"
    assert result.score >= 60


def test_ai_relevance_rejects_generic_business_news() -> None:
    result = evaluate_relevance(
        RawItemText(title="Company reports quarterly revenue", summary="", content="")
    )

    assert result.is_relevant is False
    assert result.outcome == "excluded"
    assert result.score == 0
    assert result.topics == ()
    assert result.reasons == ("no_ai_signal",)


def test_relevance_uses_explainable_signals_and_rule_topics() -> None:
    result = evaluate_relevance(
        RawItemText(title="OpenAI launches multimodal model API benchmark")
    )

    assert result.score == 100
    assert result.topics == ("product", "research")
    assert result.reasons == (
        "strong_ai_signal",
        "recognized_ai_entity",
        "event_action",
    )
    assert RELEVANCE_RULE_VERSION == "relevance-v2"


def test_relevance_decision_is_byte_equivalent_on_replay() -> None:
    item = RawItemText(
        title="OpenAI launches new multimodal API",
        summary="SDK preview",
        content="",
    )

    first = json.dumps(evaluate_relevance(item).model_dump(), separators=(",", ":"))
    second = json.dumps(evaluate_relevance(item).model_dump(), separators=(",", ":"))

    assert first == second


@pytest.mark.parametrize(
    "item",
    [
        RawItemText(summary="OpenAI releases a multimodal system"),
        RawItemText(content="Anthropic publishes research on inference"),
        RawItemText(item_kind="artificial intelligence release"),
        RawItemText(publisher_name="OpenAI multimodal research"),
        RawItemText(
            title="Agent launches a safety benchmark",
            source_topics=("artificial intelligence",),
        ),
    ],
)
def test_relevance_uses_each_bounded_input_field(item: RawItemText) -> None:
    assert evaluate_relevance(item).outcome == "included"


def test_relevance_matches_terms_at_word_boundaries_only() -> None:
    result = evaluate_relevance(RawItemText(title="Models improve deployment"))

    assert result.is_relevant is False
    assert result.reasons == ("no_ai_signal",)


def test_relevance_normalizes_case_punctuation_and_whitespace() -> None:
    result = evaluate_relevance(RawItemText(title="  OPENAI—MULTIMODAL API\n"))

    assert result.reasons == ("strong_ai_signal", "recognized_ai_entity")


def test_relevance_truncates_content_before_normalization() -> None:
    result = evaluate_relevance(
        RawItemText(
            title="Company publishes a general update",
            content="x" * 100_000 + " inference LLM",
        )
    )

    assert result.outcome == "excluded"
    assert result.score < 60
