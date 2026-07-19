from __future__ import annotations

from copy import deepcopy

from newsradar.daily_reports.accumulation import (
    DailyOverviewBaseline,
    accumulate_daily_overview,
    accumulate_daily_overview_baselines,
)
from newsradar.daily_reports.schema import (
    DailyReportOverviewItemDraft,
    EditorialDecision,
)


def _draft(
    event_id: int,
    *,
    version: int = 1,
    evidence: list[dict[str, object]] | None = None,
    degraded: bool = False,
) -> DailyReportOverviewItemDraft:
    snapshot: dict[str, object] = {
        "label": f"event-{event_id}-v{version}",
        "evidence": evidence or [],
    }
    if degraded:
        snapshot["display_degradation_reason"] = "event_detail_unavailable"
    return DailyReportOverviewItemDraft(
        event_id=event_id,
        event_version_number=version,
        position=event_id,
        snapshot=snapshot,
    )


def test_accumulate_adds_three_unique_events_from_four_current_candidates() -> None:
    previous = tuple(_draft(event_id) for event_id in range(1, 9))
    current = tuple(_draft(event_id) for event_id in (8, 9, 10, 11))

    result = accumulate_daily_overview(
        previous,
        current,
        canonical_event_ids={8: 8, 9: 9, 10: 10, 11: 11},
        previous_decisions={},
    )

    assert [item.event_id for item in result.items] == list(range(1, 12))
    assert result.stats.inherited_count == 8
    assert result.stats.new_count == 3
    assert result.stats.updated_count == 1


def test_accumulate_baselines_folds_disconnected_heads_before_current() -> None:
    result = accumulate_daily_overview_baselines(
        (
            DailyOverviewBaseline(tuple(_draft(event_id) for event_id in (1, 2, 3, 4)), {}),
            DailyOverviewBaseline(tuple(_draft(event_id) for event_id in (4, 5)), {}),
        ),
        tuple(_draft(event_id) for event_id in (5, 6, 7, 8, 9, 10)),
        canonical_event_ids={event_id: event_id for event_id in range(1, 11)},
    )

    assert [item.event_id for item in result.items] == list(range(1, 11))
    assert result.stats.inherited_count == 4
    assert result.stats.new_count == 5
    assert result.stats.deduplicated_count == 2


def test_accumulate_baselines_prefers_newer_explicit_review() -> None:
    result = accumulate_daily_overview_baselines(
        (
            DailyOverviewBaseline(
                (_draft(7),),
                {(7, 1): EditorialDecision.EXCLUDE},
            ),
            DailyOverviewBaseline(
                (_draft(7),),
                {(7, 1): EditorialDecision.KEEP},
            ),
        ),
        (),
        canonical_event_ids={7: 7},
    )

    assert "daily_disposition" not in result.items[0].snapshot


def test_accumulate_does_not_add_a_new_applied_duplicate() -> None:
    previous = (_draft(1),)
    current = (_draft(1), _draft(12))

    result = accumulate_daily_overview(
        previous,
        current,
        canonical_event_ids={1: 1, 12: 1},
        previous_decisions={},
    )

    assert [item.event_id for item in result.items] == [1]
    assert result.stats.deduplicated_count == 1


def test_accumulate_prefers_later_canonical_survivor_over_higher_ranked_legacy() -> None:
    legacy = _draft(
        12,
        evidence=[
            {
                "url": "https://example.com/legacy",
                "title": "Legacy evidence",
                "published_at": "2026-07-19T00:00:00+00:00",
            }
        ],
    )
    survivor = _draft(
        1,
        evidence=[
            {
                "url": "https://example.com/survivor",
                "title": "Survivor evidence",
                "published_at": "2026-07-19T01:00:00+00:00",
            }
        ],
    )

    result = accumulate_daily_overview(
        (),
        (legacy, survivor),
        canonical_event_ids={12: 1, 1: 1},
        previous_decisions={},
    )

    assert [item.event_id for item in result.items] == [1]
    assert result.items[0].snapshot["label"] == "event-1-v1"
    assert [
        evidence["url"] for evidence in result.items[0].snapshot["evidence"]
    ] == [
        "https://example.com/survivor",
        "https://example.com/legacy",
    ]
    assert result.stats.new_count == 1
    assert result.stats.deduplicated_count == 1


def test_accumulate_preserves_previously_visible_duplicate_as_audit_record() -> None:
    previous = (_draft(1), _draft(12))

    result = accumulate_daily_overview(
        previous,
        (_draft(1, version=2),),
        canonical_event_ids={1: 1, 12: 1},
        previous_decisions={(12, 1): EditorialDecision.DUPLICATE},
    )

    assert len(result.items) == 2
    duplicate = next(item for item in result.items if item.event_id == 12)
    assert duplicate.snapshot["daily_disposition"] == {
        "status": "excluded",
        "reason_code": "duplicate_confirmed",
        "reason_zh": "该条目已确认与另一事件重复，保留用于审计，不进入决策版或语音。",
        "canonical_event_id": 1,
    }


def test_accumulate_invalidates_prior_exclude_without_mutating_archived_snapshot() -> None:
    previous = (_draft(7),)
    archived_snapshot = deepcopy(previous[0].snapshot)

    result = accumulate_daily_overview(
        previous,
        (),
        canonical_event_ids={7: 7},
        previous_decisions={(7, 1): EditorialDecision.EXCLUDE},
    )

    assert result.items[0].snapshot["daily_disposition"]["reason_code"] == (
        "invalidated_by_new_evidence"
    )
    assert result.stats.invalidated_count == 1
    assert previous[0].snapshot == archived_snapshot


def test_accumulate_keeps_same_version_exclude_disposition_when_current_reappears() -> None:
    previous = (_draft(7),)

    result = accumulate_daily_overview(
        previous,
        (_draft(7),),
        canonical_event_ids={7: 7},
        previous_decisions={(7, 1): EditorialDecision.EXCLUDE},
    )

    assert result.items[0].snapshot["daily_disposition"]["reason_code"] == (
        "invalidated_by_new_evidence"
    )


def test_accumulate_resets_prior_disposition_for_strictly_newer_complete_version() -> None:
    previous = (_draft(7),)

    result = accumulate_daily_overview(
        previous,
        (_draft(7, version=2),),
        canonical_event_ids={7: 7},
        previous_decisions={(7, 1): EditorialDecision.EXCLUDE},
    )

    assert result.items[0].event_version_number == 2
    assert "daily_disposition" not in result.items[0].snapshot


def test_accumulate_retains_complete_item_and_records_newer_degraded_attempt() -> None:
    result = accumulate_daily_overview(
        (_draft(7, version=1),),
        (_draft(7, version=2, degraded=True),),
        canonical_event_ids={7: 7},
        previous_decisions={},
    )

    retained = result.items[0]
    assert retained.event_version_number == 1
    assert retained.snapshot["retained_complete_display"] == {
        "attempted_event_version_number": 2,
        "reason_code": "event_detail_unavailable",
        "reason_zh": "新版本展示数据不完整，已保留上一完整版本。",
        "next_action_zh": "等待事件详情补齐后再生成修订版。",
    }


def test_accumulate_keeps_visible_duplicate_for_strictly_newer_complete_version() -> None:
    previous = (_draft(1), _draft(12))

    result = accumulate_daily_overview(
        previous,
        (_draft(12, version=2),),
        canonical_event_ids={1: 1, 12: 1},
        previous_decisions={(12, 1): EditorialDecision.DUPLICATE},
    )

    duplicate = next(item for item in result.items if item.event_id == 12)
    assert duplicate.event_version_number == 2
    assert duplicate.snapshot["daily_disposition"]["reason_code"] == (
        "duplicate_confirmed"
    )


def test_accumulate_keeps_historical_legacy_item_when_current_survivor_arrives() -> None:
    legacy = _draft(
        12,
        evidence=[
            {
                "url": "https://example.com/legacy",
                "title": "Legacy evidence",
                "published_at": "2026-07-19T00:00:00+00:00",
            }
        ],
    )
    survivor = _draft(
        1,
        evidence=[
            {
                "url": "https://example.com/survivor",
                "title": "Survivor evidence",
                "published_at": "2026-07-19T01:00:00+00:00",
            }
        ],
    )

    result = accumulate_daily_overview(
        (legacy,),
        (survivor,),
        canonical_event_ids={12: 1, 1: 1},
        previous_decisions={},
    )

    assert [item.event_id for item in result.items] == [12, 1]
    archived_legacy = result.items[0]
    assert archived_legacy.snapshot["daily_disposition"]["reason_code"] == (
        "duplicate_confirmed"
    )
    assert [evidence["url"] for evidence in result.items[1].snapshot["evidence"]] == [
        "https://example.com/survivor",
        "https://example.com/legacy",
    ]


def test_accumulate_merges_only_new_duplicate_evidence_into_canonical_survivor() -> None:
    survivor = _draft(
        1,
        evidence=[
            {
                "url": "https://example.com/one",
                "title": "One",
                "published_at": "2026-07-19T00:00:00+00:00",
            }
        ],
    )
    duplicate = _draft(
        12,
        evidence=[
            {
                "url": "https://example.com/one",
                "title": "One",
                "published_at": "2026-07-19T00:00:00+00:00",
            },
            {
                "url": "https://example.com/two",
                "title": "Two",
                "published_at": "2026-07-19T01:00:00+00:00",
            },
        ],
    )

    result = accumulate_daily_overview(
        (survivor,),
        (duplicate,),
        canonical_event_ids={1: 1, 12: 1},
        previous_decisions={},
    )

    assert result.items[0].event_id == 1
    assert [evidence["url"] for evidence in result.items[0].snapshot["evidence"]] == [
        "https://example.com/one",
        "https://example.com/two",
    ]
