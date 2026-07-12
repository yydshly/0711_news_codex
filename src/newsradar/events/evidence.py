"""Local evidence attribution from audited source metadata."""

from __future__ import annotations

from newsradar.events.schema import ClusterItem, EvidenceAssessment, EvidenceRole

_ROLE_BY_NATURE = {
    "first_party": EvidenceRole.OFFICIAL,
    "professional_media": EvidenceRole.PROFESSIONAL_MEDIA,
    "research": EvidenceRole.RESEARCH,
    "community": EvidenceRole.COMMUNITY,
    "social": EvidenceRole.SOCIAL,
    "aggregator": EvidenceRole.AGGREGATOR,
}


def assess_evidence(items: tuple[ClusterItem, ...]) -> tuple[EvidenceAssessment, ...]:
    """Assign evidence roots and independence without fetching or model calls."""
    return tuple(_assess(item) for item in items)


def _assess(item: ClusterItem) -> EvidenceAssessment:
    role = _ROLE_BY_NATURE.get(item.source_nature or "", EvidenceRole.COMMUNITY)
    source_allows_evidence = "evidence" in item.source_roles
    independent = (
        role
        in {
            EvidenceRole.OFFICIAL,
            EvidenceRole.PROFESSIONAL_MEDIA,
            EvidenceRole.RESEARCH,
        }
        and source_allows_evidence
    )
    limitations: list[str] = []
    # `original_url` is an audited upstream-attribution signal.  A distinct
    # publisher URL that cites the same report is not an independent confirmation.
    if (
        role is EvidenceRole.PROFESSIONAL_MEDIA
        and item.original_url
        and item.canonical_url
        and item.original_url != item.canonical_url
    ):
        independent = False
        limitations.append("upstream_attribution_not_independent")
    if item.evidence_role is not None and item.evidence_role is not role:
        limitations.append("source_role_conflict")
    if role in {EvidenceRole.AGGREGATOR, EvidenceRole.SOCIAL, EvidenceRole.COMMUNITY}:
        limitations.append("source_nature_not_independent")
    if not source_allows_evidence:
        limitations.append("source_not_evidence")
    if _is_preprint(item):
        limitations.append("not_peer_reviewed")
    return EvidenceAssessment(
        raw_item_id=item.raw_item_id,
        role=role,
        root_evidence_key=_root_evidence_key(item),
        independent=independent,
        limitations=tuple(limitations),
        rationale=("audited_source_metadata",),
    )


def _root_evidence_key(item: ClusterItem) -> str:
    if (
        item.source_nature == "professional_media"
        and item.original_url
        and item.canonical_url
        and item.original_url != item.canonical_url
    ):
        return item.original_url
    if item.canonical_url:
        return item.canonical_url
    if item.original_url:
        return item.original_url
    return f"publisher:{(item.publisher_name or '').casefold()}:{item.title_fingerprint or ''}"


def _is_preprint(item: ClusterItem) -> bool:
    values = (item.provider_category or "", item.source_nature or "", item.canonical_url or "")
    return any("arxiv" in value.casefold() or "preprint" in value.casefold() for value in values)
