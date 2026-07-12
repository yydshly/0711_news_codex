from __future__ import annotations

from datetime import UTC, date, datetime

from newsradar.web.diagnostics import build_diagnostic_narrative
from newsradar.web.viewmodels import DashboardSummary, GapGroup, GapTarget, ProviderRow


def _summary(*, latest_probe_at: datetime | None = None) -> DashboardSummary:
    return DashboardSummary(
        provider_count=6,
        target_count=14,
        free_direct_count=4,
        indirect_count=3,
        blocked_count=7,
        three_success_count=2,
        category_counts=(("official", 4), ("social_community", 2)),
        latest_probe_at=latest_probe_at,
    )


def _provider(
    provider_id: str,
    *,
    availability: str = "ready",
    latest_outcome: str | None = None,
) -> ProviderRow:
    return ProviderRow(
        provider_id=provider_id,
        name=provider_id.upper(),
        category="social_community" if provider_id == "x" else "official",
        category_label="社交与社区" if provider_id == "x" else "官方来源",
        cost_tier="paid" if provider_id == "x" else "free",
        cost_label="付费" if provider_id == "x" else "免费",
        availability=availability,
        availability_label=availability,
        target_count=2,
        direct_count=1,
        indirect_count=1,
        latest_outcome=latest_outcome,
        latest_outcome_label=latest_outcome or "尚未探测",
        reviewed_at=date(2026, 7, 11),
    )


def _gap(
    availability: str,
    label: str,
    target_count: int,
    *,
    provider_name: str | None = None,
) -> GapGroup:
    targets = (
        GapTarget(
            source_id="source-id",
            name="OpenAI on X",
            provider_id="provider-id",
            provider_name=provider_name,
            impact="private impact detail",
            alternative="private alternative detail",
            cost_label="付费",
            unlock_requirements=("SECRET_API_KEY",),
            evidence=("private evidence",),
        ),
    ) if provider_name else ()
    return GapGroup(
        availability=availability,
        label=label,
        target_count=target_count,
        targets=targets,
    )


def test_diagnostic_distinguishes_catalog_capability_content_and_fact_coverage():
    providers = [
        _provider("github", latest_outcome="success"),
        _provider("x", availability="requires_payment", latest_outcome="blocked"),
    ]
    gaps = (
        _gap("requires_payment", "需要付费", 4, provider_name="X"),
        _gap("requires_credentials", "需要凭据", 2),
    )

    result = build_diagnostic_narrative(
        _summary(latest_probe_at=datetime(2026, 7, 11, 12, tzinfo=UTC)), providers, gaps
    )

    assert "已登记 6 个供应商、14 个目标" in result.current_capability
    assert "不代表已经抓取新闻" in result.current_capability
    assert "能力探测" in result.current_capability
    assert "内容探测" in result.current_capability
    assert "事实覆盖" in result.current_capability
    assert "社交来源只用于发现线索和判断热度" in result.current_capability
    assert "需要付费（4 个目标）" in result.blind_spots
    assert "X" in result.blind_spots
    assert "免费凭据" in result.next_steps
    assert "审批" in result.next_steps
    assert result.next_steps.index("间接发现") < result.next_steps.index("付费来源")


def test_diagnostic_handles_no_probe_history():
    result = build_diagnostic_narrative(_summary(), [_provider("github")], ())

    assert "尚无内容探测历史，当前只能判断目录覆盖" in result.current_capability
    assert "当前没有已登记的访问缺口" in result.blind_spots


def test_diagnostic_sorts_gaps_by_count_then_label_and_limits_to_three():
    gaps = (
        _gap("manual_only", "仅限手动", 2),
        _gap("requires_payment", "需要付费", 5),
        _gap("unavailable", "暂不可用", 1),
        _gap("requires_approval", "需要审批", 2),
    )

    result = build_diagnostic_narrative(_summary(), [], gaps)

    assert result.blind_spots.index("需要付费") < result.blind_spots.index("仅限手动")
    assert result.blind_spots.index("仅限手动") < result.blind_spots.index("需要审批")
    assert "暂不可用" not in result.blind_spots


def test_diagnostic_is_deterministic_and_does_not_expose_sensitive_gap_details():
    providers = [_provider("secret-provider", latest_outcome="success")]
    gaps = (
        _gap("requires_credentials", "需要凭据", 2, provider_name="PUBLIC PROVIDER"),
    )

    first = build_diagnostic_narrative(_summary(), providers, gaps)
    second = build_diagnostic_narrative(_summary(), providers, gaps)

    assert first == second
    assert "PUBLIC PROVIDER" in first.blind_spots
    assert "SECRET_API_KEY" not in repr(first)
    assert "private evidence" not in repr(first)
