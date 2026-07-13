from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    provider_count: int
    target_count: int
    free_direct_count: int
    indirect_count: int
    blocked_count: int
    three_success_count: int
    category_counts: tuple[tuple[str, int], ...]
    latest_probe_at: datetime | None
    explored_count: int = 0
    trial_eligible_count: int = 0
    discovery_only_count: int = 0
    restricted_count: int = 0


@dataclass(frozen=True, slots=True)
class ProviderRow:
    provider_id: str
    name: str
    category: str
    category_label: str
    cost_tier: str
    cost_label: str
    availability: str
    availability_label: str
    target_count: int
    direct_count: int
    indirect_count: int
    latest_outcome: str | None
    latest_outcome_label: str
    reviewed_at: date
    auth_mode: str = ""
    auth_label: str = "未记录"
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TargetRow:
    source_id: str
    name: str
    provider_id: str
    provider_name: str
    target_type: str
    target_type_label: str
    coverage_mode: str
    coverage_label: str
    availability: str
    availability_label: str
    access_kind: str | None
    access_label: str
    risk_total: int | None
    latest_content_at: datetime | None
    latest_outcome: str | None
    latest_outcome_label: str
    roles: tuple[str, ...] = ()
    role_labels: tuple[str, ...] = ()
    trial_label: str = "尚未评估"
    trial_reason: str = "尚未评估试用资格"


@dataclass(frozen=True, slots=True)
class ProbeRow:
    probe_id: str
    object_id: str
    object_name: str
    probe_type: str
    probe_type_label: str
    outcome: str
    outcome_label: str
    checked_at: datetime
    http_status: int | None
    latency_ms: float | None
    completeness: float | None
    reason_zh: str
    reason_raw: str
    suggested_status: str | None = None
    suggested_status_label: str = "未记录"


@dataclass(frozen=True, slots=True)
class AccessMethodView:
    kind: str
    kind_label: str
    url: str
    priority: int
    requires_manual_approval: bool
    auth_envs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RiskView:
    terms: int
    authentication: int
    stability: int
    data_quality: int
    operating_cost: int
    total: int
    evidence: tuple[str, ...]
    hard_block_reason: str | None
    assessed_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderDetail:
    row: ProviderRow
    homepage: str
    docs_url: str
    terms_url: str
    auth_mode: str
    auth_label: str
    capabilities: tuple[str, ...]
    required_env: tuple[str, ...]
    evidence: tuple[str, ...]
    unlock_requirements: tuple[str, ...]
    notes: str | None
    targets: tuple[TargetRow, ...]
    probes: tuple[ProbeRow, ...]


@dataclass(frozen=True, slots=True)
class TargetDetail:
    row: TargetRow
    official_identity_url: str | None
    reviewed_at: date | None
    status: str
    status_label: str
    nature: str
    nature_label: str
    language: str
    roles: tuple[tuple[str, str], ...]
    topics: tuple[str, ...]
    expected_fields: tuple[str, ...]
    unlock_requirements: tuple[str, ...]
    notes: str | None
    access_methods: tuple[AccessMethodView, ...]
    risk: RiskView | None
    recent_probes: tuple[ProbeRow, ...]


@dataclass(frozen=True, slots=True)
class GapTarget:
    source_id: str
    name: str
    provider_id: str
    provider_name: str
    impact: str
    alternative: str
    cost_label: str
    unlock_requirements: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GapGroup:
    availability: str
    label: str
    target_count: int
    targets: tuple[GapTarget, ...]

@dataclass(frozen=True, slots=True)
class ResearchCandidateView:
    key: str
    kind: str
    implementation: str
    officiality: str
    officiality_label: str
    authentication: str
    authentication_label: str
    roles: tuple[str, ...]
    fields: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence: tuple[str, ...]
    sample_status: str
    decision: str
    decision_label: str
    latest_probe_outcome: str | None = None
    latest_probe_label: str = "尚未探测"
    sample_count: int | None = None
    latest_probe_at: datetime | None = None
    field_completeness: float | None = None

@dataclass(frozen=True, slots=True)
class ResearchTargetView:
    source_id: str
    name: str
    provider_name: str
    provider_availability_label: str
    target_status_label: str
    nature_label: str
    target_type_label: str
    coverage_label: str
    availability_label: str
    research_status: str
    research_status_label: str
    wanted_information: tuple[str, ...]
    conclusion: str | None
    no_fallback_reason: str | None
    candidates: tuple[ResearchCandidateView, ...]
