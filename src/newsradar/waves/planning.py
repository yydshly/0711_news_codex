from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass

from newsradar.providers.schema import Availability, CoverageMode
from newsradar.sources.repository import canonical_definition
from newsradar.sources.schema import SourceDefinition

from .schema import WaveProfile


@dataclass(frozen=True, slots=True)
class WaveMemberSnapshot:
    source_id: str
    provider_id: str
    definition_hash: str
    roles: tuple[str, ...]
    availability: str
    access_kind: str
    fetchable: bool
    blocked_reason: str | None


@dataclass(frozen=True, slots=True)
class WavePlan:
    profile_id: str
    members: tuple[WaveMemberSnapshot, ...]
    digest: str
    window_hours: int
    trend_days: int

    @property
    def fetchable(self) -> tuple[WaveMemberSnapshot, ...]:
        return tuple(member for member in self.members if member.fetchable)

    @property
    def blocked(self) -> tuple[WaveMemberSnapshot, ...]:
        return tuple(member for member in self.members if not member.fetchable)

    @property
    def fetchable_ids(self) -> frozenset[str]:
        return frozenset(member.source_id for member in self.fetchable)


def _pick_method(source: SourceDefinition, probe: object | None):
    probe_kind = getattr(probe, "access_kind", None)
    if probe_kind is None:
        return None, "no_probe"
    if getattr(probe, "outcome", None) != "success":
        return None, "probe_not_successful"
    method = next((item for item in source.access_methods if item.kind.value == probe_kind), None)
    if method is None:
        return None, "probe_method_mismatch"
    return method, None


def _member(
    source: SourceDefinition, probe: object | None, credentials: Set[str]
) -> WaveMemberSnapshot:
    _, definition_hash = canonical_definition(source)
    method, reason = _pick_method(source, probe)
    if source.availability is not Availability.READY:
        reason = (
            "missing_credentials"
            if source.availability is Availability.REQUIRES_CREDENTIALS
            else (
                "requires_approval"
                if source.availability is Availability.REQUIRES_APPROVAL
                else (
                    "requires_payment"
                    if source.availability is Availability.REQUIRES_PAYMENT
                    else f"availability_{source.availability.value}"
                )
            )
        )
    elif source.coverage_mode is not CoverageMode.DIRECT:
        reason = reason or "indirect_access"
    elif method is not None and method.requires_manual_approval:
        reason = "requires_approval"
    elif method is not None and not set(method.auth_envs) <= credentials:
        reason = "missing_credentials"
    return WaveMemberSnapshot(
        source_id=source.id,
        provider_id=source.provider_id,
        definition_hash=definition_hash,
        roles=tuple(sorted(role.value for role in source.roles)),
        availability=source.availability.value,
        access_kind=(
            method.kind.value if method is not None else str(getattr(probe, "access_kind", ""))
        ),
        fetchable=reason is None,
        blocked_reason=reason,
    )


def build_wave_plan(
    profile: WaveProfile,
    sources: Iterable[SourceDefinition],
    latest_probes: Mapping[str, object],
    configured_credentials: Set[str],
) -> WavePlan:
    catalog = {source.id: source for source in sources}
    missing_ids = sorted(set(profile.source_ids) - set(catalog))
    if missing_ids:
        raise ValueError(f"Unknown source id: {', '.join(missing_ids)}")
    members = tuple(
        _member(catalog[source_id], latest_probes.get(source_id), configured_credentials)
        for source_id in sorted(profile.source_ids)
    )
    payload = {
        "profile_id": profile.id,
        "window_hours": profile.window_hours,
        "trend_days": profile.trend_days,
        "members": [
            {
                "source_id": member.source_id,
                "definition_hash": member.definition_hash,
                "access_kind": member.access_kind,
                "fetchable": member.fetchable,
                "blocked_reason": member.blocked_reason,
            }
            for member in members
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return WavePlan(profile.id, members, digest, profile.window_hours, profile.trend_days)
