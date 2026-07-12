from __future__ import annotations

from newsradar.events.evidence import assess_evidence
from newsradar.events.schema import ClusterItem, EvidenceRole


def evidence_item(**changes: object) -> ClusterItem:
    data: dict[str, object] = {
        "raw_item_id": 1,
        "canonical_url": "https://publisher.test/story",
        "title_fingerprint": "story",
        "source_nature": "professional_media",
        "source_roles": ("evidence",),
    }
    data.update(changes)
    return ClusterItem(**data)


def test_aggregator_and_original_share_one_root_evidence() -> None:
    original = evidence_item(canonical_url="https://publisher.test/story", original_url=None)
    aggregate = evidence_item(
        raw_item_id=2,
        canonical_url="https://publisher.test/story",
        original_url="https://news.google.test/item",
        source_nature="aggregator",
        source_roles=("discovery",),
    )

    assessments = assess_evidence((original, aggregate))

    assert len({row.root_evidence_key for row in assessments}) == 1
    assert assessments[0].independent is True
    assert assessments[1].independent is False
    assert assessments[1].role is EvidenceRole.AGGREGATOR


def test_source_claimed_official_role_cannot_override_aggregator_metadata() -> None:
    assessment = assess_evidence(
        (
            evidence_item(
                evidence_role=EvidenceRole.OFFICIAL,
                source_nature="aggregator",
                source_roles=("evidence",),
            ),
        )
    )[0]

    assert assessment.independent is False
    assert assessment.role is EvidenceRole.AGGREGATOR
    assert "source_role_conflict" in assessment.limitations


def test_non_evidence_source_cannot_be_independent() -> None:
    assessment = assess_evidence((evidence_item(source_roles=("discovery",)),))[0]

    assert assessment.independent is False
    assert "source_not_evidence" in assessment.limitations


def test_missing_audited_source_roles_cannot_be_independent() -> None:
    assessment = assess_evidence((evidence_item(source_roles=()),))[0]

    assert assessment.independent is False
    assert "source_not_evidence" in assessment.limitations


def test_arxiv_preprints_are_labeled_without_model_inference() -> None:
    assessment = assess_evidence(
        (evidence_item(source_nature="research", provider_category="arxiv"),)
    )[0]

    assert assessment.role is EvidenceRole.RESEARCH
    assert "not_peer_reviewed" in assessment.limitations


def test_root_falls_back_to_publisher_and_title_fingerprint() -> None:
    assessment = assess_evidence(
        (evidence_item(canonical_url=None, publisher_name="Publisher", title_fingerprint="abc"),)
    )[0]

    assert assessment.root_evidence_key == "publisher:publisher:abc"
