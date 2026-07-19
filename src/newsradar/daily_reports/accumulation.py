from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from newsradar.daily_reports.schema import (
    DailyReportOverviewItemDraft,
    EditorialDecision,
)

_DUPLICATE_REASON_ZH = "该条目已确认与另一事件重复，保留用于审计，不进入决策版或语音。"
_INVALIDATED_REASON_ZH = "该条目已被后续审核排除，保留用于审计，不进入决策版或语音。"


@dataclass(frozen=True, slots=True)
class DailyOverviewAccumulationStats:
    inherited_count: int
    new_count: int
    updated_count: int
    deduplicated_count: int
    invalidated_count: int


@dataclass(frozen=True, slots=True)
class DailyOverviewAccumulation:
    items: tuple[DailyReportOverviewItemDraft, ...]
    stats: DailyOverviewAccumulationStats


def accumulate_daily_overview(
    previous: tuple[DailyReportOverviewItemDraft, ...],
    current: tuple[DailyReportOverviewItemDraft, ...],
    *,
    canonical_event_ids: Mapping[int, int],
    previous_decisions: Mapping[tuple[int, int], EditorialDecision],
) -> DailyOverviewAccumulation:
    rows = [replace(item, snapshot=deepcopy(item.snapshot)) for item in previous]
    index_by_event = {item.event_id: index for index, item in enumerate(rows)}
    index_by_canonical = _canonical_indexes(rows, canonical_event_ids)
    updated_count = 0
    new_count = 0
    deduplicated_count = 0
    invalidated_count = 0
    reset_disposition_event_ids: set[int] = set()

    for index, item in enumerate(tuple(rows)):
        decision = previous_decisions.get((item.event_id, item.event_version_number))
        canonical_id = canonical_event_ids.get(item.event_id, item.event_id)
        if decision is EditorialDecision.EXCLUDE:
            rows[index] = _with_disposition(
                item,
                status="invalidated",
                reason_code="invalidated_by_new_evidence",
                reason_zh=_INVALIDATED_REASON_ZH,
                canonical_event_id=canonical_id,
            )
            invalidated_count += 1
        elif decision is EditorialDecision.DUPLICATE:
            rows[index] = _with_disposition(
                item,
                status="excluded",
                reason_code="duplicate_confirmed",
                reason_zh=_DUPLICATE_REASON_ZH,
                canonical_event_id=canonical_id,
            )

    for item in current:
        canonical_id = canonical_event_ids.get(item.event_id, item.event_id)
        exact_index = index_by_event.get(item.event_id)
        if exact_index is not None:
            previous_item = rows[exact_index]
            decision = previous_decisions.get(
                (previous_item.event_id, previous_item.event_version_number)
            )
            is_prior_editorial_disposition = decision in {
                EditorialDecision.EXCLUDE,
                EditorialDecision.DUPLICATE,
            }
            current_is_degraded = "display_degradation_reason" in item.snapshot
            previous_is_degraded = (
                "display_degradation_reason" in previous_item.snapshot
            )
            can_replace = item.event_version_number >= previous_item.event_version_number
            can_replace = can_replace and (
                not current_is_degraded or previous_is_degraded
            )
            if is_prior_editorial_disposition:
                can_replace = (
                    can_replace
                    and item.event_version_number > previous_item.event_version_number
                    and not current_is_degraded
                )
            if can_replace:
                rows[exact_index] = replace(item, snapshot=deepcopy(item.snapshot))
                if is_prior_editorial_disposition:
                    reset_disposition_event_ids.add(item.event_id)
            updated_count += 1
            continue

        canonical_index = index_by_canonical.get(canonical_id)
        if canonical_index is not None:
            representative = rows[canonical_index]
            if (
                item.event_id == canonical_id
                and representative.event_id != canonical_id
            ):
                rows[canonical_index] = _merge_item_evidence(item, representative)
                index_by_event.pop(representative.event_id, None)
                index_by_event[item.event_id] = canonical_index
            else:
                rows[canonical_index] = _merge_item_evidence(representative, item)
            deduplicated_count += 1
            continue

        rows.append(replace(item, snapshot=deepcopy(item.snapshot)))
        index_by_event[item.event_id] = len(rows) - 1
        index_by_canonical[canonical_id] = len(rows) - 1
        new_count += 1

    represented = set(index_by_canonical)
    for index, item in enumerate(tuple(rows)):
        canonical_id = canonical_event_ids.get(item.event_id, item.event_id)
        if (
            canonical_id != item.event_id
            and canonical_id in represented
            and item.event_id not in reset_disposition_event_ids
        ):
            rows[index] = _with_disposition(
                item,
                status="excluded",
                reason_code="duplicate_confirmed",
                reason_zh=_DUPLICATE_REASON_ZH,
                canonical_event_id=canonical_id,
            )

    positioned = tuple(
        replace(item, position=position) for position, item in enumerate(rows, start=1)
    )
    return DailyOverviewAccumulation(
        items=positioned,
        stats=DailyOverviewAccumulationStats(
            inherited_count=len(previous),
            new_count=new_count,
            updated_count=updated_count,
            deduplicated_count=deduplicated_count,
            invalidated_count=invalidated_count,
        ),
    )


def _canonical_indexes(
    rows: list[DailyReportOverviewItemDraft],
    canonical_event_ids: Mapping[int, int],
) -> dict[int, int]:
    indexes: dict[int, int] = {}
    for index, item in enumerate(rows):
        canonical_id = canonical_event_ids.get(item.event_id, item.event_id)
        existing_index = indexes.get(canonical_id)
        if existing_index is None or (
            item.event_id == canonical_id
            and rows[existing_index].event_id != canonical_id
        ):
            indexes[canonical_id] = index
    return indexes


def _with_disposition(
    item: DailyReportOverviewItemDraft,
    *,
    status: str,
    reason_code: str,
    reason_zh: str,
    canonical_event_id: int,
) -> DailyReportOverviewItemDraft:
    snapshot = deepcopy(item.snapshot)
    snapshot["daily_disposition"] = {
        "status": status,
        "reason_code": reason_code,
        "reason_zh": reason_zh,
        "canonical_event_id": canonical_event_id,
    }
    return replace(item, snapshot=snapshot)


def _merge_item_evidence(
    survivor: DailyReportOverviewItemDraft,
    duplicate: DailyReportOverviewItemDraft,
) -> DailyReportOverviewItemDraft:
    snapshot = deepcopy(survivor.snapshot)
    existing_evidence = snapshot.get("evidence")
    merged_evidence = (
        deepcopy(existing_evidence) if isinstance(existing_evidence, list) else []
    )
    evidence_keys = {
        _evidence_key(evidence)
        for evidence in merged_evidence
        if isinstance(evidence, dict)
    }
    duplicate_evidence = duplicate.snapshot.get("evidence")
    if isinstance(duplicate_evidence, list):
        for evidence in duplicate_evidence:
            if not isinstance(evidence, dict):
                continue
            key = _evidence_key(evidence)
            if key in evidence_keys:
                continue
            merged_evidence.append(deepcopy(evidence))
            evidence_keys.add(key)
    snapshot["evidence"] = merged_evidence
    return replace(survivor, snapshot=snapshot)


def _evidence_key(evidence: dict[str, Any]) -> tuple[object, object, object]:
    return (
        evidence.get("url"),
        evidence.get("title"),
        evidence.get("published_at"),
    )
