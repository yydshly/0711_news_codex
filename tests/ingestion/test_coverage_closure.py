from __future__ import annotations

from datetime import UTC, datetime

from newsradar.ingestion.coverage_closure import (
    CoverageClosureState,
    build_coverage_closure_plan,
)
from newsradar.ingestion.trial import ProbeSnapshot
from newsradar.sources.schema import SourceDefinition
from tests.test_source_schema import valid_source


def _source(source_id: str, **changes: object) -> SourceDefinition:
    values = valid_source()
    values.update(
        {
            "id": source_id,
            "name": source_id,
            "availability": "ready",
            "coverage_mode": "direct",
            **changes,
        }
    )
    return SourceDefinition.model_validate(values)


def _probe(outcome: str = "success", samples: int = 1) -> ProbeSnapshot:
    return ProbeSnapshot(
        probe_run_id=1,
        outcome=outcome,
        sample_count=samples,
        field_completeness=1.0 if samples else 0.0,
        sample_fields=frozenset({"title", "canonical_url"}) if samples else frozenset(),
        finished_at=datetime(2026, 7, 14, tzinfo=UTC),
    )


def test_plan_classifies_covered_queueable_blocked_and_skips_out_of_scope() -> None:
    sources = [
        _source("covered"),
        _source("queueable"),
        _source("active"),
        _source("failed-probe"),
        _source("catalog", coverage_mode="catalog_only"),
        _source("unavailable", availability="unavailable"),
    ]
    snapshots = {
        item.id: _probe("failed" if item.id == "failed-probe" else "success")
        for item in sources
    }

    plan = build_coverage_closure_plan(
        sources,
        snapshots,
        covered_source_ids={"covered"},
        active_source_ids={"active"},
    )

    assert [(entry.source_id, entry.state) for entry in plan.entries] == [
        ("active", CoverageClosureState.BLOCKED),
        ("covered", CoverageClosureState.COVERED),
        ("failed-probe", CoverageClosureState.BLOCKED),
        ("queueable", CoverageClosureState.QUEUEABLE),
    ]
    assert plan.by_source_id("active").code == "operation_in_progress"
    assert plan.by_source_id("failed-probe").code == "probe_not_successful"
    assert [entry.source_id for entry in plan.queueable] == ["queueable"]


def test_plan_is_sorted_and_marks_missing_probe_as_blocked() -> None:
    sources = [_source("zeta"), _source("alpha")]

    plan = build_coverage_closure_plan(
        sources,
        {"zeta": _probe()},
        covered_source_ids=(),
    )

    assert [entry.source_id for entry in plan.entries] == ["alpha", "zeta"]
    assert plan.by_source_id("alpha").state is CoverageClosureState.BLOCKED
    assert plan.by_source_id("alpha").code == "no_probe"


def test_plan_does_not_mutate_its_inputs() -> None:
    sources = [_source("one")]
    snapshots = {"one": _probe()}
    covered_source_ids = {"covered"}
    active_source_ids = {"active"}

    build_coverage_closure_plan(sources, snapshots, covered_source_ids, active_source_ids)

    assert [source.id for source in sources] == ["one"]
    assert set(snapshots) == {"one"}
    assert covered_source_ids == {"covered"}
    assert active_source_ids == {"active"}
