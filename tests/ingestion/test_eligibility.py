from __future__ import annotations

import pytest

from newsradar.ingestion.eligibility import evaluate_fetch_eligibility
from newsradar.sources.schema import SourceDefinition
from tests.test_source_schema import valid_source


def make_source(**changes: object) -> SourceDefinition:
    data = valid_source()
    data.update(changes)
    return SourceDefinition.model_validate(data)


@pytest.mark.parametrize(
    ("changes", "approved_only", "configured_env", "hard_block_reason", "allowed", "code"),
    [
        ({"ingestion": {"enabled": True}}, True, set(), None, True, None),
        ({}, False, set(), None, True, None),
        ({"status": "paused"}, False, set(), None, False, "source_paused"),
        ({"status": "disabled"}, False, set(), None, False, "source_disabled"),
        ({"availability": "requires_payment"}, False, set(), None, False, "requires_payment"),
        ({"availability": "requires_approval"}, False, set(), None, False, "requires_approval"),
        ({"coverage_mode": "catalog_only"}, False, set(), None, False, "catalog_only"),
        (
            {
                "access_methods": [
                    {
                        "kind": "html",
                        "url": "https://www.anthropic.com/news",
                        "priority": 1,
                        "requires_manual_approval": True,
                    }
                ]
            },
            False,
            set(),
            None,
            False,
            "html_only",
        ),
        (
            {
                "access_methods": [
                    {
                        "kind": "rest_api",
                        "url": "https://www.anthropic.com/api/news",
                        "priority": 1,
                        "auth_env": "NEWS_API_TOKEN",
                    }
                ]
            },
            False,
            set(),
            None,
            False,
            "missing_credentials",
        ),
        ({}, False, set(), "Terms prohibit automated access", False, "hard_blocked"),
        ({}, True, set(), None, False, "not_approved"),
    ],
)
def test_evaluate_fetch_eligibility_returns_stable_policy_decision(
    changes: dict[str, object],
    approved_only: bool,
    configured_env: set[str],
    hard_block_reason: str | None,
    allowed: bool,
    code: str | None,
) -> None:
    decision = evaluate_fetch_eligibility(
        make_source(**changes),
        approved_only=approved_only,
        configured_env=configured_env,
        hard_block_reason=hard_block_reason,
    )

    assert decision.allowed is allowed
    assert decision.error_code == code
    assert decision.reason
    if allowed:
        assert decision.access_method is not None
        assert decision.access_method.kind.value == "rss"
        assert decision.reason == "允许抓取：已选择已审核的 rss 访问方式。"
    else:
        assert decision.access_method is None
        assert any("" <= char <= "\U0010ffff" for char in decision.reason)


def test_evaluate_fetch_eligibility_skips_unconfigured_method_for_configured_fallback() -> None:
    source = make_source(
        access_methods=[
            {
                "kind": "rest_api",
                "url": "https://www.anthropic.com/api/news",
                "priority": 1,
                "auth_env": "NEWS_API_TOKEN",
            },
            {
                "kind": "rss",
                "url": "https://www.anthropic.com/news/rss.xml",
                "priority": 2,
            },
        ]
    )

    decision = evaluate_fetch_eligibility(
        source,
        approved_only=False,
        configured_env=set(),
        hard_block_reason=None,
    )

    assert decision.allowed is True
    assert decision.access_method is not None
    assert decision.access_method.kind.value == "rss"
