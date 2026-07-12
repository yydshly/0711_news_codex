from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from newsradar.sources.schema import SourceDefinition

from .probes import ProviderProbeResult
from .schema import Availability, CoverageMode, ProviderDefinition


def render_coverage_report(
    providers: list[ProviderDefinition],
    sources: list[SourceDefinition],
    results: dict[str, ProviderProbeResult] | None = None,
) -> str:
    availability = Counter(source.availability.value for source in sources)
    direct = sum(source.coverage_mode == CoverageMode.DIRECT for source in sources)
    indirect = sum(source.coverage_mode == CoverageMode.INDIRECT for source in sources)
    blocked = sum(source.availability != Availability.READY for source in sources)
    categories = Counter(provider.category.value for provider in providers)
    lines = [
        "# News Codex Source Coverage",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Providers | {len(providers)} |",
        f"| Catalog targets | {len(sources)} |",
        f"| Direct targets | {direct} |",
        f"| Indirect targets | {indirect} |",
        f"| Blocked targets | {blocked} |",
        "",
        "## Provider categories",
        "",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(categories.items()))
    lines.extend(["", "## Availability", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(availability.items()))
    lines.extend(
        [
            "",
            "## Providers",
            "",
            "| Provider | Category | Cost | Availability | Probe | Unlock requirements |",
            "|---|---|---|---|---|---|",
        ]
    )
    for provider in sorted(providers, key=lambda item: item.name.lower()):
        result = results.get(provider.id) if results else None
        probe = result.outcome if result else "not_run"
        unlock = "; ".join(provider.unlock_requirements) or "none"
        lines.append(
            f"| {provider.name} | {provider.category.value} | {provider.cost_tier.value} | "
            f"{provider.availability.value} | {probe} | {unlock} |"
        )
    lines.extend(
        [
            "",
            "> Catalog and capability coverage do not imply that content is being ingested.",
            "",
        ]
    )
    return "\n".join(lines)
