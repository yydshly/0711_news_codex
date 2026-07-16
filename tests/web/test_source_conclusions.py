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


def test_manual_source_uses_reviewed_target_specific_diagnosis() -> None:
    from newsradar.web.source_conclusions import SourceConclusionInput, conclude_source

    conclusion = conclude_source(
        SourceConclusionInput(
            "catalog_only",
            "manual_only",
            False,
            None,
            manual_reason="公司博客不等于社区内容，当前没有具体服务器或频道授权。",
            manual_next_action="指定服务器和频道，并取得管理员对官方 Bot 的授权。",
        )
    )

    assert conclusion.code == "manual_only"
    assert "公司博客不等于社区内容" in conclusion.reason
    assert "管理员" in conclusion.next_action


def test_placeholder_covered_by_successful_target_does_not_inflate_actual_success() -> None:
    from newsradar.web.source_conclusions import SourceConclusionInput, conclude_source

    conclusion = conclude_source(
        SourceConclusionInput(
            "catalog_only",
            "manual_only",
            False,
            None,
            covered_by_successful_target_id="no-priors-youtube",
        )
    )

    assert conclusion.code == "covered_by_successful_target"
    assert conclusion.bucket == "deferred"
    assert conclusion.label == "已由同一官方目标覆盖"
    assert "no-priors-youtube" in conclusion.reason


def test_duplicate_catalog_target_is_deferred_not_success() -> None:
    from newsradar.web.source_conclusions import SourceConclusionInput, conclude_source

    conclusion = conclude_source(
        SourceConclusionInput(
            "catalog_only",
            "manual_only",
            False,
            None,
            managed_by_target_id="universe-axios-1",
        )
    )

    assert conclusion.code == "duplicate_catalog_target"
    assert conclusion.bucket == "deferred"
    assert conclusion.label == "重复目录项"
    assert "universe-axios-1" in conclusion.reason


@pytest.mark.parametrize(
    ("availability", "covered_by", "expected"),
    [
        ("requires_payment", None, "payment_required"),
        ("unavailable", None, "unavailable"),
        ("requires_approval", None, "needs_approval"),
        ("manual_only", "verified-target", "covered_by_successful_target"),
    ],
)
def test_duplicate_manager_does_not_hide_stronger_conclusion(
    availability: str, covered_by: str | None, expected: str
) -> None:
    from newsradar.web.source_conclusions import SourceConclusionInput, conclude_source

    conclusion = conclude_source(
        SourceConclusionInput(
            "catalog_only",
            availability,
            False,
            None,
            covered_by_successful_target_id=covered_by,
            managed_by_target_id="manager",
        )
    )

    assert conclusion.code == expected
