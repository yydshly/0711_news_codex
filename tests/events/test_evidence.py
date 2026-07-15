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
        canonical_url="https://news.google.test/item",
        original_url="https://publisher.test/story",
        source_nature="aggregator",
        source_roles=("discovery",),
    )

    assessments = assess_evidence((original, aggregate))

    assert len({row.root_evidence_key for row in assessments}) == 1


def test_aggregator_redirect_uses_the_upstream_url_as_its_root() -> None:
    assessment = assess_evidence(
        (
            evidence_item(
                canonical_url="https://aggregator.test/redirect?id=123",
                original_url="https://publisher.test/story",
                source_nature="aggregator",
                source_roles=("discovery",),
            ),
        )
    )[0]

    assert assessment.root_evidence_key == "https://publisher.test/story"
    assert assessment.independent is False


def test_professional_media_citations_of_one_upstream_report_are_not_independent() -> None:
    items = (
        ClusterItem(
            raw_item_id=1,
            title="Report",
            canonical_url="https://media-a.test/report",
            source_nature="professional_media",
            source_roles=("evidence",),
            publisher_name="Media A",
            original_url="https://upstream.test/report",
        ),
        ClusterItem(
            raw_item_id=2,
            title="Report",
            canonical_url="https://media-b.test/report",
            source_nature="professional_media",
            source_roles=("evidence",),
            publisher_name="Media B",
            original_url="https://upstream.test/report",
        ),
    )

    assessments = assess_evidence(items)

    assert {row.root_evidence_key for row in assessments} == {"https://upstream.test/report"}
    assert not any(row.independent for row in assessments)


def test_official_source_only_confirms_its_own_publication() -> None:
    assessment = assess_evidence(
        (
            evidence_item(
                source_nature="first_party",
                canonical_url="https://official.test/news/roundup",
                original_url="https://publisher.test/story",
            ),
        )
    )[0]

    assert assessment.role is EvidenceRole.OFFICIAL
    assert assessment.independent is False
    assert "upstream_attribution_not_independent" in assessment.limitations


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
