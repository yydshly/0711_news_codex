"""纯函数式的来源目录刷新规划与目录校验。"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType

from newsradar.providers.schema import Availability, CoverageMode, ProviderDefinition
from newsradar.sources.schema import AccessKind, SourceDefinition


class CatalogRefreshLane(StrEnum):
    CONTENT = "content"
    CAPABILITY = "capability"
    CATALOG = "catalog"


class CatalogMemberState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CatalogResultCode(StrEnum):
    STALE_RESULT = "stale_result"
    NO_CONTENT = "no_content"
    INCOMPLETE_FIELDS = "incomplete_fields"
    MISSING_CREDENTIALS = "missing_credentials"
    REQUIRES_APPROVAL = "requires_approval"
    REQUIRES_PAYMENT = "requires_payment"
    MANUAL_ONLY = "manual_only"
    CATALOG_VERIFIED = "catalog_verified"
    CATALOG_INCOMPLETE = "catalog_incomplete"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    RATE_LIMITED = "rate_limited"
    UNSUPPORTED_ACCESS_KIND = "unsupported_access_kind"
    CANCELLED = "cancelled"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class CatalogRefreshMemberSnapshot:
    source_id: str
    provider_id: str
    definition_hash: str
    availability: str
    coverage_mode: str
    access_kind: str
    lane: CatalogRefreshLane
    initial_result_code: CatalogResultCode | None = None


@dataclass(frozen=True, slots=True)
class CatalogRefreshPlan:
    members: tuple[CatalogRefreshMemberSnapshot, ...]
    catalog_digest: str
    lane_counts: Mapping[CatalogRefreshLane, int]

    @property
    def digest(self) -> str:
        """兼容早期调用方的计划摘要名称。"""
        return self.catalog_digest

    @classmethod
    def from_members(cls, members: Iterable[CatalogRefreshMemberSnapshot]) -> CatalogRefreshPlan:
        ordered = tuple(sorted(members, key=lambda member: member.source_id))
        payload = [
            {
                "source_id": member.source_id,
                "provider_id": member.provider_id,
                "definition_hash": member.definition_hash,
                "availability": member.availability,
                "coverage_mode": member.coverage_mode,
                "access_kind": member.access_kind,
                "lane": member.lane.value,
                "initial_result_code": (
                    member.initial_result_code.value if member.initial_result_code else None
                ),
            }
            for member in ordered
        ]
        digest = sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        counts = Counter(member.lane for member in ordered)
        lane_counts = MappingProxyType(
            {lane: counts[lane] for lane in CatalogRefreshLane if counts[lane]}
        )
        return cls(members=ordered, catalog_digest=digest, lane_counts=lane_counts)


@dataclass(frozen=True, slots=True)
class CatalogValidationResult:
    code: CatalogResultCode
    missing: tuple[str, ...]
    conclusion: str

    @property
    def missing_fields(self) -> tuple[str, ...]:
        """兼容早期调用方的缺失字段名称。"""
        return self.missing


_MISSING_CATALOG_FIELDS = (
    "official_identity_url",
    "risk_evidence",
    "reviewed_at",
    "readable_conclusion",
)


def build_catalog_refresh_plan(
    sources: Iterable[SourceDefinition],
    providers: Iterable[ProviderDefinition],
    latest: Mapping[str, object],
    configured_credentials: Iterable[str],
) -> CatalogRefreshPlan:
    """从传入的已审核定义创建可复现计划，不读取环境或外部状态。"""
    provider_ids = {provider.id for provider in providers}
    credentials = frozenset(configured_credentials)
    members: list[CatalogRefreshMemberSnapshot] = []
    for source in sources:
        if _is_archived(source):
            continue
        method = source.access_methods[0]
        lane, initial_code = _route(source, method.auth_envs, credentials)
        current_kind = method.kind.value
        latest_kind = _access_kind_of(latest.get(source.id))
        if latest_kind is not None and latest_kind != current_kind:
            initial_code = CatalogResultCode.STALE_RESULT
        members.append(
            CatalogRefreshMemberSnapshot(
                source_id=source.id,
                provider_id=source.provider_id,
                definition_hash=catalog_definition_hash(source, provider_ids),
                availability=source.availability.value,
                coverage_mode=source.coverage_mode.value,
                access_kind=current_kind,
                lane=lane,
                initial_result_code=initial_code,
            )
        )
    return CatalogRefreshPlan.from_members(members)


def validate_catalog_entry(
    source: SourceDefinition, provider: ProviderDefinition | None
) -> CatalogValidationResult:
    """校验目录所需的人工审核字段；不执行网络或环境读取。"""
    del provider
    conclusion = source.research.conclusion
    missing = tuple(
        field
        for field, present in (
            ("official_identity_url", source.official_identity_url is not None),
            ("risk_evidence", bool(source.risk.evidence)),
            ("reviewed_at", source.reviewed_at is not None),
            (
                "readable_conclusion",
                bool(conclusion and re.search(r"[\u3400-\u9fff]", conclusion)),
            ),
        )
        if not present
    )
    if missing:
        return CatalogValidationResult(
            code=CatalogResultCode.CATALOG_INCOMPLETE,
            missing=missing,
            conclusion="目录信息不完整，需补齐官方身份、风险证据、审核日期和中文结论。",
        )
    return CatalogValidationResult(
        code=CatalogResultCode.CATALOG_VERIFIED,
        missing=(),
        conclusion=conclusion or "目录审核已完成。",
    )


def _route(
    source: SourceDefinition, required_credentials: tuple[str, ...], credentials: frozenset[str]
) -> tuple[CatalogRefreshLane, CatalogResultCode | None]:
    if (
        source.coverage_mode == CoverageMode.CATALOG_ONLY
        or source.availability == Availability.MANUAL_ONLY
        or source.access_methods[0].kind == AccessKind.HTML
    ):
        return CatalogRefreshLane.CATALOG, CatalogResultCode.MANUAL_ONLY
    if source.availability in {
        Availability.REQUIRES_CREDENTIALS,
        Availability.REQUIRES_APPROVAL,
        Availability.REQUIRES_PAYMENT,
        Availability.UNAVAILABLE,
    }:
        return CatalogRefreshLane.CAPABILITY, None
    if not set(required_credentials).issubset(credentials):
        return CatalogRefreshLane.CAPABILITY, CatalogResultCode.MISSING_CREDENTIALS
    return CatalogRefreshLane.CONTENT, None


def _is_archived(source: SourceDefinition) -> bool:
    return (
        getattr(source, "catalog_state", None) == "archived"
        or getattr(source.status, "value", source.status) == "archived"
    )


def _access_kind_of(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = value.get("access_kind")
    else:
        value = getattr(value, "access_kind", None)
    return getattr(value, "value", value) if value is not None else None


def _definition_hash(source: SourceDefinition, provider_is_known: bool) -> str:
    payload = source.model_dump(mode="json")
    payload["provider_is_known"] = provider_is_known
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def catalog_definition_hash(
    source: SourceDefinition, providers: Iterable[ProviderDefinition] | set[str]
) -> str:
    """Fingerprint one definition without applying planner eligibility filters."""
    provider_ids = (
        providers if isinstance(providers, set) else {provider.id for provider in providers}
    )
    return _definition_hash(source, source.provider_id in provider_ids)
