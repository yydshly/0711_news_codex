from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from newsradar.web.viewmodels import DashboardSummary, GapGroup, ProviderRow


@dataclass(frozen=True, slots=True)
class DiagnosticNarrative:
    current_capability: str
    blind_spots: str
    next_steps: str


def build_diagnostic_narrative(
    summary: DashboardSummary,
    providers: Sequence[ProviderRow],
    gaps: Sequence[GapGroup],
) -> DiagnosticNarrative:
    """Build a local, deterministic explanation of the registered source capability."""
    probed_provider_count = sum(provider.latest_outcome is not None for provider in providers)
    successful_provider_count = sum(
        provider.latest_outcome == "success" for provider in providers
    )
    social_registered = any(provider.category == "social_community" for provider in providers)

    catalog_sentence = (
        f"当前已登记 {summary.provider_count} 个供应商、{summary.target_count} 个目标；"
        f"其中 {summary.free_direct_count} 个是免费直接目标，"
        f"{summary.indirect_count} 个是间接发现目标，{summary.blocked_count} 个仍受阻。"
        "已登记只表示目录中存在经过审阅的目标，不代表已经抓取新闻。"
    )
    capability_sentence = (
        f"供应商能力探测已有 {probed_provider_count} 个结果，"
        f"其中 {successful_provider_count} 个最近一次成功；"
        f"内容探测中有 {summary.three_success_count} 个目标最近三次连续成功。"
        "能力探测只验证访问能力，内容探测验证能否取得预期内容，"
        "两者都不能自动等同于事实覆盖。"
    )
    if summary.latest_probe_at is None:
        history_sentence = "尚无内容探测历史，当前只能判断目录覆盖。"
    else:
        history_sentence = f"最近一条探测记录时间为 {summary.latest_probe_at.isoformat()}。"
    social_sentence = (
        "社交来源只用于发现线索和判断热度，不能单独作为事实依据。"
        if social_registered
        else "若后续登记社交来源，也只应用于发现线索和判断热度，不能作为事实依据。"
    )

    top_gaps = sorted(gaps, key=lambda group: (-group.target_count, group.label))[:3]
    if top_gaps:
        gap_items = "、".join(_gap_summary(group) for group in top_gaps)
        blind_spots = f"当前主要访问缺口为：{gap_items}。这些缺口仍是待解锁目标，不是内容缺失事实。"
    else:
        blind_spots = "当前没有已登记的访问缺口；这不代表目录之外不存在盲区。"

    next_steps = (
        "建议按以下顺序推进：1. 先核对并启用免费凭据；"
        "2. 再申请必要审批；3. 保留间接发现路径用于发现线索；"
        "4. 完成前三项后才评估付费来源。每次解锁后仍需分别进行能力探测和内容探测。"
    )
    return DiagnosticNarrative(
        current_capability="".join(
            (catalog_sentence, capability_sentence, history_sentence, social_sentence)
        ),
        blind_spots=blind_spots,
        next_steps=next_steps,
    )


def _gap_summary(group: GapGroup) -> str:
    provider_names = sorted({target.provider_name for target in group.targets})
    provider_suffix = f"，涉及 {'、'.join(provider_names)}" if provider_names else ""
    return f"{group.label}（{group.target_count} 个目标）{provider_suffix}"
