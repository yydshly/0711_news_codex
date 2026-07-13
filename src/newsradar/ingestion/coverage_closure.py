from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from newsradar.ingestion.trial import ProbeSnapshot, evaluate_trial_eligibility
from newsradar.providers.schema import Availability, CoverageMode
from newsradar.sources.schema import SourceDefinition


class CoverageClosureState(StrEnum):
    COVERED = "covered"
    QUEUEABLE = "queueable"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class CoverageClosureEntry:
    source_id: str
    name: str
    state: CoverageClosureState
    code: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class CoverageClosurePlan:
    entries: tuple[CoverageClosureEntry, ...]

    @property
    def covered(self) -> tuple[CoverageClosureEntry, ...]:
        return tuple(item for item in self.entries if item.state is CoverageClosureState.COVERED)

    @property
    def queueable(self) -> tuple[CoverageClosureEntry, ...]:
        return tuple(item for item in self.entries if item.state is CoverageClosureState.QUEUEABLE)

    @property
    def blocked(self) -> tuple[CoverageClosureEntry, ...]:
        return tuple(item for item in self.entries if item.state is CoverageClosureState.BLOCKED)

    def by_source_id(self, source_id: str) -> CoverageClosureEntry:
        return next(item for item in self.entries if item.source_id == source_id)


def build_coverage_closure_plan(
    sources: Sequence[SourceDefinition],
    snapshots: Mapping[str, ProbeSnapshot],
    covered_source_ids: Collection[str],
    active_source_ids: Collection[str] = (),
) -> CoverageClosurePlan:
    covered = frozenset(covered_source_ids)
    active = frozenset(active_source_ids)
    entries: list[CoverageClosureEntry] = []

    for source in sorted(sources, key=lambda item: item.id):
        if source.availability is not Availability.READY:
            continue
        if source.coverage_mode is not CoverageMode.DIRECT:
            continue
        if source.id in covered:
            entries.append(
                CoverageClosureEntry(
                    source.id,
                    source.name,
                    CoverageClosureState.COVERED,
                    None,
                    "已有成功抓取证据。",
                )
            )
            continue
        if source.id in active:
            entries.append(
                CoverageClosureEntry(
                    source.id,
                    source.name,
                    CoverageClosureState.BLOCKED,
                    "operation_in_progress",
                    "已有抓取任务正在排队或执行，本次不重复入队。",
                )
            )
            continue

        decision = evaluate_trial_eligibility(source, snapshots.get(source.id))
        entries.append(
            CoverageClosureEntry(
                source.id,
                source.name,
                CoverageClosureState.QUEUEABLE
                if decision.eligible
                else CoverageClosureState.BLOCKED,
                decision.code,
                decision.reason,
            )
        )

    return CoverageClosurePlan(tuple(entries))
