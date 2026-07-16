from dataclasses import replace

import pytest


@pytest.mark.parametrize(
    ("changes", "code", "bucket"),
    [
        ({"successful_fetch": True}, "fetched_successfully", "actual_success"),
        ({"coverage_mode": "indirect"}, "indirect_discovery", "fixable"),
        ({"availability": "requires_credentials"}, "needs_credentials", "user_action"),
        ({"availability": "requires_approval"}, "needs_approval", "user_action"),
        ({"availability": "manual_only"}, "manual_only", "user_action"),
        ({"availability": "requires_payment"}, "payment_required", "deferred"),
        ({"availability": "unavailable"}, "unavailable", "deferred"),
        ({"latest_probe_outcome": "success"}, "capable_pending_acceptance", "fixable"),
        ({}, "needs_technical_validation", "fixable"),
    ],
)
def test_source_conclusion_is_unique_and_actionable(changes, code, bucket) -> None:
    from newsradar.web.source_conclusions import SourceConclusionInput, conclude_source

    value = SourceConclusionInput(
        coverage_mode="direct",
        availability="ready",
        successful_fetch=False,
        latest_probe_outcome=None,
    )

    conclusion = conclude_source(replace(value, **changes))

    assert conclusion.code == code
    assert conclusion.bucket == bucket
    assert conclusion.label
    assert conclusion.reason
    assert conclusion.next_action


def test_successful_fetch_does_not_override_external_prohibition() -> None:
    from newsradar.web.source_conclusions import SourceConclusionInput, conclude_source

    conclusion = conclude_source(
        SourceConclusionInput(
            coverage_mode="direct",
            availability="requires_payment",
            successful_fetch=True,
            latest_probe_outcome="success",
        )
    )

    assert conclusion.code == "payment_required"
    assert conclusion.bucket == "deferred"
