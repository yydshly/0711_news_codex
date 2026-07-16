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


def test_indirect_conclusion_distinguishes_no_sample_and_unresolved_origin() -> None:
    from newsradar.web.source_conclusions import SourceConclusionInput, conclude_source

    empty = conclude_source(
        SourceConclusionInput("indirect", "ready", False, None, indirect_item_count=0)
    )
    unresolved = conclude_source(
        SourceConclusionInput(
            "indirect",
            "ready",
            False,
            "success",
            indirect_item_count=5,
            indirect_published_count=5,
            indirect_origin_resolved_count=0,
            indirect_duplicate_count=1,
        )
    )

    assert empty.reason == "尚无间接发现样本，不能验收原媒体和发布时间字段。"
    assert "5 条样本" in unresolved.reason
    assert "0 条解析出原媒体文章 URL" in unresolved.reason
    assert "1 条重复候选" in unresolved.next_action


def test_manual_source_with_public_candidate_is_fixable_not_user_action() -> None:
    from newsradar.web.source_conclusions import SourceConclusionInput, conclude_source

    conclusion = conclude_source(
        SourceConclusionInput(
            "catalog_only", "manual_only", False, None, has_public_candidate=True
        )
    )

    assert conclusion.code == "public_candidate_pending_acceptance"
    assert conclusion.bucket == "fixable"
    assert conclusion.label == "已有公开路径待验收"
