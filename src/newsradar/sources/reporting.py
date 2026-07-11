from __future__ import annotations

from datetime import UTC, datetime

from newsradar.sources.probes.base import ProbeResult
from newsradar.sources.risk import assess_risk
from newsradar.sources.schema import SourceDefinition


def render_source_report(
    sources: list[SourceDefinition],
    latest_results: dict[str, ProbeResult] | None = None,
) -> str:
    results = latest_results or {}
    lines = [
        "# News Codex Source Intelligence Report",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "| Source | Nature | Roles | Primary method | Risk | Status | Probe | "
        "Completeness | Reason |",
        "|---|---|---|---|---:|---|---|---:|---|",
    ]
    for source in sorted(sources, key=lambda item: item.name.lower()):
        decision = assess_risk(source)
        result = results.get(source.id)
        probe = result.outcome.value if result else "not_run"
        completeness = f"{result.field_completeness:.0%}" if result else "-"
        reason = result.reason if result else decision.reason
        roles = ", ".join(role.value for role in source.roles)
        lines.append(
            f"| {source.name} | {source.nature.value} | {roles} | "
            f"{source.access_methods[0].kind.value} | {decision.score} ({decision.band.value}) | "
            f"{source.status.value} | {probe} | {completeness} | {reason.replace('|', '/')} |"
        )
    lines.extend(["", "## Source details", ""])
    for source in sorted(sources, key=lambda item: item.name.lower()):
        decision = assess_risk(source)
        result = results.get(source.id)
        expected = {field.value for field in source.expected_fields}
        observed = set(expected)
        if result and result.samples:
            for sample in result.samples:
                observed.intersection_update(sample.fields_present())
        else:
            observed.clear()
        missing = sorted(expected - observed) if result else sorted(expected)
        primary = source.access_methods[0]
        fallbacks = source.access_methods[1:]
        lines.extend(
            [
                f"### {source.name} (`{source.id}`)",
                "",
                f"- Nature: `{source.nature.value}`",
                f"- Roles: {', '.join(f'`{role.value}`' for role in source.roles)}",
                f"- Primary access: `{primary.kind.value}` - {primary.url}",
                "- Fallback access: "
                + (
                    ", ".join(f"`{method.kind.value}` - {method.url}" for method in fallbacks)
                    if fallbacks
                    else "none documented"
                ),
                f"- Expected fields: {', '.join(sorted(expected))}",
                "- Observed missing fields: " + (", ".join(missing) if missing else "none"),
                (
                    "- Probe: not run"
                    if result is None
                    else f"- Probe: `{result.outcome.value}`; {result.reason}"
                ),
                (
                    "- Risk breakdown: "
                    f"terms={source.risk.terms}, authentication={source.risk.authentication}, "
                    f"stability={source.risk.stability}, data_quality={source.risk.data_quality}, "
                    f"operating_cost={source.risk.operating_cost}; total={decision.score} "
                    f"(`{decision.band.value}`)"
                ),
                f"- Recommendation: {decision.reason}",
                f"- Notes: {source.notes or 'No additional notes.'}",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "YAML remains the audited source of truth; probe results never edit it.",
        ]
    )
    return "\n".join(lines) + "\n"
