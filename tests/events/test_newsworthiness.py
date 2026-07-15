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
