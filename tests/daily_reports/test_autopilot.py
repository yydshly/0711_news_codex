from newsradar.daily_reports.autopilot import (
    build_decision_review,
    build_overview_review,
    deserialize_catalog_plan,
    serialize_catalog_plan,
)
from newsradar.sources.catalog_refresh import (
    CatalogRefreshLane,
    CatalogRefreshMemberSnapshot,
    CatalogRefreshPlan,
)


def test_rule_review_marks_single_root_signal_as_needing_evidence() -> None:
    review = build_overview_review(
        {
            "zh_title": "新信号",
            "zh_summary": "公开材料尚不足以确认。",
            "independent_root_count": 1,
            "status": "emerging",
        }
    )

    assert review.decision == "needs_evidence"
    assert "仍需" in review.evidence_assessment
    assert review.zh_title == "新信号"


def test_rule_decision_review_preserves_confirmed_snapshot_without_claiming_new_fact() -> None:
    review = build_decision_review(
        {
            "zh_title": "已确认事件",
            "zh_summary": "已有公开证据。",
            "independent_root_count": 2,
            "status": "confirmed",
        }
    )

    assert review.decision == "keep"
    assert review.zh_summary == "已有公开证据。"


def test_catalog_plan_round_trip_is_secret_free_and_tamper_evident() -> None:
    plan = CatalogRefreshPlan.from_members(
        [
            CatalogRefreshMemberSnapshot(
                source_id="source-a",
                provider_id="provider-a",
                definition_hash="source-hash",
                provider_definition_hash="provider-hash",
                availability="ready",
                coverage_mode="direct",
                access_kind="rss",
                lane=CatalogRefreshLane.CONTENT,
            )
        ]
    )

    stored = serialize_catalog_plan(plan)

    assert deserialize_catalog_plan(stored) == plan
    assert "token" not in str(stored).lower()
    stored["catalog_digest"] = "tampered"
    try:
        deserialize_catalog_plan(stored)
    except ValueError as exc:
        assert str(exc) == "invalid_daily_autopilot_catalog_plan"
    else:
        raise AssertionError("tampered catalog plan must be rejected")
