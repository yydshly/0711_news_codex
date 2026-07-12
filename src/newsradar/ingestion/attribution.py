from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from newsradar.sources.schema import SourceDefinition, SourceNature, SourceRole


class OriginResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    TOO_MANY_REDIRECTS = "too_many_redirects"


@dataclass(frozen=True)
class Attribution:
    publisher_name: str | None
    publisher_url: str | None
    discovery_url: str | None
    resolution_status: OriginResolutionStatus


def resolve_evidence_role(
    source: SourceDefinition, attribution: Attribution
) -> tuple[str, ...]:
    """Return source roles applicable to an observed item without external resolution."""
    del attribution
    if source.nature in {
        SourceNature.AGGREGATOR,
        SourceNature.SOCIAL,
        SourceNature.COMMUNITY,
    }:
        return tuple(role.value for role in source.roles if role is not SourceRole.EVIDENCE)
    return tuple(role.value for role in source.roles)
