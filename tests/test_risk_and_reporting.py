from datetime import UTC, datetime, timedelta

from newsradar.sources.probes.base import ProbeOutcome, ProbeResult, ProbeSample
from newsradar.sources.reporting import render_source_report
from newsradar.sources.risk import RiskBand, assess_risk, recommend_status
from newsradar.sources.schema import SourceDefinition, SourceStatus

from .test_source_schema import valid_source


def source_with_risk(total_parts: tuple[int, int, int, int, int], *, methods: int = 1):
    data = valid_source()
    keys = ["terms", "authentication", "stability", "data_quality", "operating_cost"]
    data["risk"] = dict(zip(keys, total_parts, strict=True))
    if methods == 2:
        data["access_methods"].append(
            {
                "kind": "html",
                "url": "https://www.anthropic.com/news",
                "priority": 2,
                "requires_manual_approval": True,
            }
        )
    return SourceDefinition.model_validate(data)


def success_result(source_id: str, *, completeness: float = 1.0, days_old: int = 1):
    now = datetime.now(UTC)
    return ProbeResult(
        source_id=source_id,
        access_kind="rss",
        access_url="https://www.anthropic.com/news/rss.xml",
        outcome=ProbeOutcome.SUCCESS,
        started_at=now,
        finished_at=now,
        field_completeness=completeness,
        latest_published_at=now - timedelta(days=days_old),
        suggested_status=SourceStatus.CANDIDATE,
        reason="ok",
    )


def test_risk_bands_follow_plan_thresholds() -> None:
    assert assess_risk(source_with_risk((1, 1, 1, 1, 1))).band == RiskBand.LOW
    assert assess_risk(source_with_risk((2, 2, 2, 2, 2))).band == RiskBand.MEDIUM
    assert assess_risk(source_with_risk((4, 3, 3, 3, 3))).band == RiskBand.HIGH
    assert assess_risk(source_with_risk((4, 4, 4, 4, 4))).band == RiskBand.DISABLED


def test_hard_block_always_disables_source() -> None:
    data = valid_source()
    data["risk"]["hard_block_reason"] = "Requires login cookie"
    source = SourceDefinition.model_validate(data)
    assert assess_risk(source).band == RiskBand.DISABLED


def test_low_risk_source_requires_three_good_probes_to_activate() -> None:
    source = source_with_risk((1, 1, 1, 1, 1))
    assert recommend_status(source, [success_result(source.id)] * 2) == SourceStatus.CANDIDATE
    assert recommend_status(source, [success_result(source.id)] * 3) == SourceStatus.ACTIVE


def test_medium_risk_source_requires_fallback_method() -> None:
    no_fallback = source_with_risk((2, 2, 2, 2, 2))
    with_fallback = source_with_risk((2, 2, 2, 2, 2), methods=2)
    assert (
        recommend_status(no_fallback, [success_result(no_fallback.id)] * 3)
        == SourceStatus.CANDIDATE
    )
    assert (
        recommend_status(with_fallback, [success_result(with_fallback.id)] * 3)
        == SourceStatus.ACTIVE
    )


def test_incomplete_or_stale_probe_cannot_activate() -> None:
    source = source_with_risk((1, 1, 1, 1, 1))
    incomplete = [success_result(source.id, completeness=0.8)] * 3
    stale = [success_result(source.id, days_old=90)] * 3
    assert recommend_status(source, incomplete) == SourceStatus.DEGRADED
    assert recommend_status(source, stale) == SourceStatus.DEGRADED


def test_report_includes_nature_method_risk_and_recommendation() -> None:
    source = source_with_risk((1, 1, 1, 1, 1))
    result = success_result(source.id)
    report = render_source_report([source], {source.id: result})
    assert "Anthropic News" in report
    assert "first_party" in report
    assert "rss" in report
    assert "5 (low)" in report
    assert "candidate" in report
    assert "Risk breakdown" in report
    assert "Observed missing fields" in report
    assert "Primary access" in report


def test_report_lists_fields_missing_from_any_sample() -> None:
    source = source_with_risk((1, 1, 1, 1, 1))
    result = success_result(source.id)
    result.samples = [
        ProbeSample(
            title="Complete",
            canonical_url="https://www.anthropic.com/news/1",
            published_at=datetime.now(UTC),
            summary="Summary",
        ),
        ProbeSample(
            title="Missing summary",
            canonical_url="https://www.anthropic.com/news/2",
            published_at=datetime.now(UTC),
        ),
    ]
    report = render_source_report([source], {source.id: result})
    detail = report.split("Observed missing fields:", 1)[1].splitlines()[0]
    assert "summary" in detail
