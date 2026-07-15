import pytest

from newsradar.events.newsworthiness import evaluate_newsworthiness
from newsradar.events.schema import RawItemText


@pytest.mark.parametrize(
    "title",
    (
        "OpenAI releases GPT-6 API",
        "Anthropic raises $5B in new funding",
        "New benchmark finds reasoning gains in small language models",
        "Critical vulnerability disclosed in an AI inference server",
    ),
)
def test_explicit_ai_events_are_newsworthy(title: str) -> None:
    result = evaluate_newsworthiness(RawItemText(title=title))

    assert result.outcome == "included"
    assert result.action is not None
    assert "event_action" in result.reason_codes


@pytest.mark.parametrize(
    "title",
    (
        "Subscribe for the best AI deals",
        "#AI #LLM https://example.com",
        "SpaceX stock sinks for a second day",
        "Agent 64 game patch notes",
    ),
)
def test_non_events_and_off_topic_items_are_excluded(title: str) -> None:
    result = evaluate_newsworthiness(RawItemText(title=title))

    assert result.outcome == "excluded"
    assert result.reason_codes


def test_link_only_repost_is_excluded_even_when_it_mentions_an_ai_topic() -> None:
    result = evaluate_newsworthiness(
        RawItemText(title="OpenAI GPT https://example.com/article")
    )

    assert result.outcome == "excluded"
    assert result.reason_codes == ("auto_repost_without_claim",)


@pytest.mark.parametrize(
    ("title", "summary"),
    (
        (
            "SpaceX stock sinks for a second-straight day, nearing $135 IPO price",
            "Elon Musk's space and AI company joined the Nasdaq-100 last week.",
        ),
        (
            "How technology reporting moved into the physical world",
            "The reporting team published a feature about datacentres powering AI.",
        ),
    ),
)
def test_summary_ai_mentions_do_not_turn_off_topic_titles_into_ai_events(
    title: str, summary: str
) -> None:
    result = evaluate_newsworthiness(RawItemText(title=title, summary=summary))

    assert result.outcome == "excluded"
    assert "event_action_not_ai_focused" in result.reason_codes


def test_research_source_can_establish_ai_focus_with_title_and_abstract() -> None:
    result = evaluate_newsworthiness(
        RawItemText(
            title="Metacognition: Foundations, Progress, and Opportunities",
            summary="This paper studies metacognition in large language models.",
            source_topics=("research", "artificial_intelligence"),
        )
    )

    assert result.outcome == "included"
    assert result.action == "research_result"


def test_ai_native_company_pricing_title_is_newsworthy() -> None:
    result = evaluate_newsworthiness(
        RawItemText(title="DeepSeek cut prices 75%. The 100x problem remains")
    )

    assert result.outcome == "included"
    assert result.action == "pricing"
