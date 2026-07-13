from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from newsradar.providers.schema import ProviderDefinition
from newsradar.sources.schema import ResearchStatus, SourceDefinition


@dataclass(frozen=True)
class AuditFinding:
    code: str
    severity: Literal["error", "warning", "info"]
    source_id: str | None
    provider_id: str | None
    message_zh: str


@dataclass(frozen=True)
class ResearchCandidateSnapshot:
    decision: str
    kind: str
    fields: tuple[str, ...]
    sample_status: str
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ResearchTargetSnapshot:
    id: str
    name: str
    status: str
    purpose: str | None
    wanted_information: tuple[str, ...]
    risk_conclusion: str | None
    candidates: tuple[ResearchCandidateSnapshot, ...]


@dataclass(frozen=True)
class ResearchAuditReport:
    provider_count: int
    target_count: int
    status_counts: Mapping[str, int]
    method_counts: Mapping[str, int]
    findings: tuple[AuditFinding, ...]
    targets: tuple[ResearchTargetSnapshot, ...] = ()


_NON_COVERAGE_STATUSES = {
    ResearchStatus.PLACEHOLDER,
    ResearchStatus.DUPLICATE,
    ResearchStatus.RETIRED,
}


def _normalized_url(value: object) -> str:
    parsed = urlsplit(str(value))
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def _snapshot(source: SourceDefinition) -> ResearchTargetSnapshot:
    return ResearchTargetSnapshot(
        id=source.id,
        name=source.name,
        status=source.research.status.value,
        purpose=source.research.purpose,
        wanted_information=tuple(source.research.wanted_information),
        risk_conclusion=source.research.risk_conclusion,
        candidates=tuple(
            ResearchCandidateSnapshot(
                decision=candidate.decision.value,
                kind=candidate.kind.value,
                fields=tuple(candidate.fields),
                sample_status=candidate.sample_status.value,
                limitations=tuple(candidate.limitations),
            )
            for candidate in source.research.candidates
        ),
    )


def audit_source_catalog(
    providers: tuple[ProviderDefinition, ...],
    sources: tuple[SourceDefinition, ...],
) -> ResearchAuditReport:
    """审计已载入的 YAML 定义；不执行网络、数据库或配置写入。"""
    provider_by_id = {provider.id: provider for provider in providers}
    status_counts = Counter(source.research.status.value for source in sources)
    method_counts = Counter(
        candidate.kind.value for source in sources for candidate in source.research.candidates
    )
    findings: list[AuditFinding] = []

    identities: dict[tuple[str, str], list[SourceDefinition]] = defaultdict(list)
    for source in sources:
        if source.id.startswith("universe-") and source.id.rsplit("-", 1)[-1] in {"1", "2"}:
            findings.append(
                AuditFinding(
                    code="placeholder_target",
                    severity="warning",
                    source_id=source.id,
                    provider_id=source.provider_id,
                    message_zh="universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。",
                )
            )
        provider = provider_by_id.get(source.provider_id)
        if (
            provider
            and source.official_identity_url
            and _normalized_url(source.official_identity_url) == _normalized_url(provider.homepage)
        ):
            findings.append(
                AuditFinding(
                    code="generic_platform_target",
                    severity="warning",
                    source_id=source.id,
                    provider_id=source.provider_id,
                    message_zh="Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。",
                )
            )
        if source.official_identity_url:
            identities[(source.provider_id, _normalized_url(source.official_identity_url))].append(
                source
            )

    for (provider_id, _), duplicates in identities.items():
        if len(duplicates) > 1:
            for source in duplicates:
                findings.append(
                    AuditFinding(
                        code="duplicate_candidate",
                        severity="warning",
                        source_id=source.id,
                        provider_id=provider_id,
                        message_zh=(
                            "同一 Provider 下存在相同 official_identity_url 的重复候选 Target。"
                        ),
                    )
                )

    for source in sources:
        research = source.research
        if research.status == ResearchStatus.VERIFIED:
            requirements = (
                (
                    "verified_missing_purpose",
                    bool(research.purpose and research.purpose.strip()),
                    "已验证研究缺少用途说明。",
                ),
                (
                    "verified_missing_wanted_information",
                    bool(research.wanted_information),
                    "已验证研究缺少所需信息。",
                ),
                (
                    "verified_missing_risk_conclusion",
                    bool(research.risk_conclusion and research.risk_conclusion.strip()),
                    "已验证研究缺少风险结论。",
                ),
            )
            for code, present, message in requirements:
                if not present:
                    findings.append(
                        AuditFinding(code, "error", source.id, source.provider_id, message)
                    )
            primary = [
                candidate
                for candidate in research.candidates
                if candidate.decision.value == "primary"
            ]
            if not primary:
                findings.append(
                    AuditFinding(
                        "verified_missing_primary",
                        "error",
                        source.id,
                        source.provider_id,
                        "已验证研究缺少首选候选方案。",
                    )
                )
            elif any(
                candidate.sample_status.value not in {"succeeded", "partial"}
                or not candidate.evidence
                for candidate in primary
            ):
                findings.append(
                    AuditFinding(
                        "verified_primary_sample_incomplete",
                        "error",
                        source.id,
                        source.provider_id,
                        "首选候选方案缺少成功样本或证据。",
                    )
                )
            if not any(
                candidate.decision.value == "fallback" for candidate in research.candidates
            ) and not (research.no_fallback_reason and research.no_fallback_reason.strip()):
                findings.append(
                    AuditFinding(
                        "verified_missing_fallback_reason",
                        "error",
                        source.id,
                        source.provider_id,
                        "缺少备选方案时必须说明原因。",
                    )
                )
        if source.research.status == ResearchStatus.NEEDS_RESEARCH:
            findings.append(
                AuditFinding(
                    code="research_incomplete",
                    severity="info",
                    source_id=source.id,
                    provider_id=source.provider_id,
                    message_zh="该 Target 尚待完成研究，不计入已验证覆盖。",
                )
            )

    return ResearchAuditReport(
        provider_count=len(providers),
        target_count=sum(
            source.research.status not in _NON_COVERAGE_STATUSES for source in sources
        ),
        status_counts=MappingProxyType(dict(sorted(status_counts.items()))),
        method_counts=MappingProxyType(dict(sorted(method_counts.items()))),
        findings=tuple(findings),
        targets=tuple(_snapshot(source) for source in sources),
    )
