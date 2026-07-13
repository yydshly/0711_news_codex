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

