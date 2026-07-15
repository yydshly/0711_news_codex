from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from newsradar.sources.probes.base import ProbeResult
from newsradar.sources.schema import AccessKind, SourceDefinition


@dataclass(frozen=True, slots=True)
class HealthProbeState:
    outcome: str
    access_kind: str


@dataclass(frozen=True, slots=True)
class HealthWaveCandidate:
    source: SourceDefinition
    reason: str


@dataclass(frozen=True, slots=True)
class HealthWavePlan:
    candidates: tuple[HealthWaveCandidate, ...]
    excluded_reasons: dict[str, int]


def select_health_wave(
    sources: list[SourceDefinition],
    latest: Mapping[str, HealthProbeState],
    configured_credentials: set[str],
) -> HealthWavePlan:
    candidates: list[HealthWaveCandidate] = []
    excluded: Counter[str] = Counter()
    for source in sources:
        method = source.access_methods[0]
        if source.coverage_mode.value == "catalog_only":
            excluded["catalog_only"] += 1
            continue
        if method.kind == AccessKind.HTML or method.requires_manual_approval:
            excluded["html_policy_blocked"] += 1
            continue
        if source.provider_id == "reddit" or any(
            name not in configured_credentials for name in method.auth_envs
        ) or source.availability.value in {
            "requires_credentials",
            "requires_approval",
            "requires_payment",
            "manual_only",
            "unavailable",
        }:
            excluded["credential_or_permission_required"] += 1
            continue
        state = latest.get(source.id)
        if state is None:
            candidates.append(HealthWaveCandidate(source, "unprobed"))
        elif state.outcome == "failed" and state.access_kind in {"rss", "atom"}:
            candidates.append(HealthWaveCandidate(source, "latest_feed_probe_failed"))
        else:
            excluded["not_in_recovery_scope"] += 1
    candidates.sort(key=lambda item: item.source.id)
    return HealthWavePlan(tuple(candidates), dict(sorted(excluded.items())))


def render_health_wave_report(
    plan: HealthWavePlan, results: Mapping[str, ProbeResult] | None = None
) -> str:
    lines = [
        "# 来源健康波次 v1.2",
        "",
        f"候选来源：{len(plan.candidates)}",
        "",
        "## 候选清单",
        "",
    ]
    for candidate in plan.candidates:
        result = results.get(candidate.source.id) if results else None
        outcome = result.outcome.value if result else "计划中"
        lines.append(f"- `{candidate.source.id}`：{candidate.reason}；结果：{outcome}")
    lines.extend(["", "## 排除原因", ""])
    for reason, count in plan.excluded_reasons.items():
        lines.append(f"- `{reason}`：{count}")
    lines.append("")
    return "\n".join(lines)
