from sqlalchemy import select

from newsradar.db.models import SourceAcquisitionCandidateRecord, SourceDefinitionRecord
from newsradar.web.queries import DashboardQueryService, ResearchQueryService


def test_research_query_service_exposes_catalog_and_unknown_safe_labels(db_session):
    service = DashboardQueryService(db_session)
    rows = service.research_targets()
    assert rows
    assert isinstance(service, ResearchQueryService)
    detail = service.research_target(rows[0].source_id)
    assert detail is not None
    assert detail.target_type_label
    assert detail.coverage_label
    assert detail.availability_label


def test_research_detail_strips_query_and_fragment_from_evidence_links(db_session):
    source = db_session.scalar(select(SourceDefinitionRecord))
    candidate = SourceAcquisitionCandidateRecord(
        source_id=source.id,
        candidate_key="official-feed",
        kind="rss",
        implementation="feedparser",
        officiality="official",
        authentication="none",
        roles=["discovery"],
        fields=["title", "canonical_url"],
        limitations=[],
        evidence=["https://example.test/feed?query=ai#fragment"],
        sample_status="succeeded",
        decision="primary",
        reviewed_at=source.reviewed_at,
        is_current=True,
    )
    db_session.add(candidate)
    db_session.commit()

    detail = DashboardQueryService(db_session).research_target(candidate.source_id)

    assert detail is not None
    assert detail.candidates[0].evidence == ("https://example.test/feed",)

