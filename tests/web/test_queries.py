from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime

import pytest

from newsradar.web.viewmodels import DashboardSummary


@pytest.fixture
def restricted_gap_query_service(db_session):
    from newsradar.db.models import ProviderDefinitionRecord, SourceDefinitionRecord
    from newsradar.web.queries import DashboardQueryService

    platform_specs = (
        ("facebook", "Facebook", "requires_credentials"),
        ("instagram", "Instagram", "requires_approval"),
        ("tiktok", "TikTok", "manual_only"),
        ("linkedin", "LinkedIn", "unavailable"),
    )
    for provider_id, name, availability in platform_specs:
        db_session.add(
            ProviderDefinitionRecord(
                id=provider_id,
                name=name,
                category="social_community",
                homepage=f"https://{provider_id}.example/",
                docs_url=f"https://{provider_id}.example/docs",
                terms_url=f"https://{provider_id}.example/terms",
                auth_mode="api_key",
                cost_tier="unknown",
                availability=availability,
                capabilities=["catalog"],
                required_env=[f"{provider_id.upper()}_API_KEY"],
                reviewed_at=date(2026, 7, 10),
                evidence=[f"https://{provider_id}.example/evidence"],
                unlock_requirements=["完成官方审批"],
                notes=f"{name} restricted provider",
                definition_hash=f"{provider_id}-restricted-hash",
            )
        )
        db_session.add(
            SourceDefinitionRecord(
                id=f"{provider_id}-official",
                name=f"{name} Official",
                provider_id=provider_id,
                target_type="account",
                availability=availability,
                coverage_mode="catalog_only",
                official_identity_url=f"https://{provider_id}.example/official",
                reviewed_at=date(2026, 7, 10),
                unlock_requirements=["完成官方审批"],
                status="candidate",
                nature="social",
                language="en",
                roles=["discovery"],
                topics=["ai"],
                authority_score=80,
                poll_interval_minutes=60,
                expected_fields=["title", "canonical_url"],
                notes=f"{name} restricted target",
                definition_hash=f"{provider_id}-target-hash",
            )
        )
    db_session.commit()
    return DashboardQueryService(db_session)


def test_summary_uses_strict_coverage_definitions(query_service):
    result = query_service.summary()
    assert result.provider_count == 2
    assert result.target_count == 3
    assert result.free_direct_count == 1
    assert result.indirect_count == 1
    assert result.blocked_count == 1
    assert result.three_success_count == 1
    assert result.latest_probe_at is not None


def test_probes_keep_capability_and_content_distinct(query_service):
    rows = query_service.probes()
    assert {row.probe_type for row in rows} == {"capability", "content"}
    capability = next(row for row in rows if row.probe_type == "capability")
    assert capability.completeness is None
    assert capability.object_id == "x"
    assert capability.probe_type_label == "能力探测"
    assert capability.suggested_status == "requires_payment"
    assert capability.suggested_status_label == "需要付费"
    content = next(row for row in rows if row.probe_type == "content")
    assert content.probe_type_label == "内容探测"
    assert content.suggested_status == "active"
    assert content.suggested_status_label == "启用"


def test_missing_probe_history_is_not_success(query_service):
    row = next(item for item in query_service.targets() if item.source_id == "search-ai")
    assert row.latest_outcome is None
    assert row.latest_outcome_label == "尚未探测"


def test_viewmodels_are_immutable_and_slotted(query_service):
    summary = query_service.summary()
    assert isinstance(summary, DashboardSummary)
    assert not hasattr(summary, "__dict__")
    with pytest.raises(FrozenInstanceError):
        summary.provider_count = 99


def test_filters_and_unknown_details(query_service):
    providers = query_service.providers({"availability": "ready", "cost_tier": "free", "q": "git"})
    assert [row.provider_id for row in providers] == ["github"]
    targets = query_service.targets(
        {"provider_id": "github", "coverage_mode": "indirect", "q": "search"}
    )
    assert [row.source_id for row in targets] == ["search-ai"]
    assert query_service.provider_detail("missing") is None
    assert query_service.target_detail("missing") is None


def test_target_metric_filters_match_summary_counts(query_service):
    summary = query_service.summary()

    free_direct = query_service.targets({"free_direct": True})
    three_success = query_service.targets({"three_success": True})

    assert len(free_direct) == summary.free_direct_count
    assert [row.source_id for row in free_direct] == ["github-openai-python"]
    assert len(three_success) == summary.three_success_count
    assert [row.source_id for row in three_success] == ["github-openai-python"]


def test_catalog_rows_include_list_metadata_without_detail_queries(query_service):
    provider = next(row for row in query_service.providers() if row.provider_id == "github")
    assert provider.auth_mode == "none"
    assert provider.auth_label == "无需认证"
    assert provider.capabilities == ("search",)

    target = next(row for row in query_service.targets() if row.source_id == "github-openai-python")
    assert target.roles == ("discovery",)
    assert target.role_labels == ("发现",)


def test_details_contain_audited_fields_but_no_secret_values(query_service):
    provider = query_service.provider_detail("x")
    assert provider is not None
    assert provider.required_env == ("X_API_KEY",)
    assert provider.targets[0].source_id == "x-openai"

    target = query_service.target_detail("x-openai")
    assert target is not None
    assert target.access_methods[0].auth_envs == ("X_API_KEY",)
    assert "headers" not in target.access_methods[0].__dataclass_fields__
    assert "secret-token-value" not in repr(target)
    assert target.risk is not None


def test_provider_detail_loads_only_latest_three_capability_probes(query_service, db_session):
    from newsradar.db.models import ProviderProbeRunRecord

    for hour in range(13, 17):
        db_session.add(
            ProviderProbeRunRecord(
                provider_id="x",
                probe_type="capability",
                outcome="success",
                availability="ready",
                reason=f"ok-{hour}",
                checked_at=datetime(2026, 7, 11, hour),
                latency_ms=10.0,
                http_status=200,
                evidence_url=f"https://x.example/evidence/{hour}",
            )
        )
    db_session.commit()

    detail = query_service.provider_detail("x")

    assert detail is not None
    assert len(detail.probes) == 3
    assert [probe.checked_at.hour for probe in detail.probes] == [16, 15, 14]


def test_only_priority_one_and_latest_related_records_are_loaded(query_service, db_session):
    from datetime import UTC, datetime

    from sqlalchemy import event

    from newsradar.db.models import SourceAccessMethodRecord, SourceRiskAssessmentRecord

    db_session.add(
        SourceAccessMethodRecord(
            source_id="github-openai-python",
            kind="html",
            url="https://fallback.example/",
            priority=2,
            requires_manual_approval=False,
            auth_env=None,
            headers={},
            params={},
        )
    )
    db_session.add(
        SourceRiskAssessmentRecord(
            source_id="github-openai-python",
            terms=9,
            authentication=9,
            stability=9,
            data_quality=9,
            operating_cost=9,
            total=45,
            evidence=[],
            hard_block_reason=None,
            assessed_at=datetime(2026, 7, 11, 13, 0, tzinfo=UTC),
        )
    )
    db_session.commit()

    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.lower().split()))

    event.listen(db_session.get_bind(), "before_cursor_execute", capture_statement)
    try:
        row = next(
            item for item in query_service.targets() if item.source_id == "github-openai-python"
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture_statement)

    assert row.access_kind == "rss"
    assert row.risk_total == 45
    assert row.latest_content_at is not None
    assert row.latest_content_at.replace(tzinfo=UTC) == datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    probe_query = next(sql for sql in statements if "source_probe_runs" in sql)
    risk_query = next(sql for sql in statements if "source_risk_assessments" in sql)
    for history_query in (probe_query, risk_query):
        assert "row_number() over" in history_query
        assert "partition by" in history_query
        assert "history_rank =" in history_query


def test_probe_filters_order_and_failure_explanation(query_service):
    rows = query_service.probes({"probe_type": "capability", "provider_id": "x"})
    assert len(rows) == 1
    assert rows[0].reason_zh == "当前权限未获批准或被远端拒绝"
    all_rows = query_service.probes()
    assert [row.checked_at for row in all_rows] == sorted(
        (row.checked_at for row in all_rows), reverse=True
    )


def test_probe_date_and_outcome_filters_are_inclusive(query_service):
    rows = query_service.probes(
        {
            "outcome": "blocked",
            "from_date": date(2026, 7, 11),
            "to_date": date(2026, 7, 11),
        }
    )

    assert [row.probe_id for row in rows] == ["capability-1"]


def test_degraded_probe_filter_uses_domain_outcome(query_service, db_session):
    from datetime import UTC, datetime

    from newsradar.db.models import SourceProbeRunRecord

    db_session.add(
        SourceProbeRunRecord(
            source_id="search-ai",
            access_kind="rss",
            access_url="https://feeds.example/search-ai",
            outcome="degraded",
            started_at=datetime(2026, 7, 11, 10, 59, tzinfo=UTC),
            finished_at=datetime(2026, 7, 11, 11, 0, tzinfo=UTC),
            latency_ms=10.0,
            http_status=200,
            final_url="https://feeds.example/search-ai",
            response_headers={},
            metrics={"field_completeness": 0.5},
            schema_fingerprint="degraded",
            suggested_status="degraded",
            reason="partial fields",
            error_code=None,
        )
    )
    db_session.commit()

    rows = query_service.probes({"outcome": "degraded", "page": 1, "page_size": 100})

    assert [row.object_id for row in rows] == ["search-ai"]
    assert rows[0].outcome_label == "降级"


def test_probe_pagination_has_database_limit_offset_and_row_bound(query_service, db_session):
    from sqlalchemy import event

    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.lower().split()))

    event.listen(db_session.get_bind(), "before_cursor_execute", capture_statement)
    try:
        rows = query_service.probes({"page": 2, "page_size": 2})
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture_statement)

    assert len(rows) <= 2
    history_sql = next(sql for sql in statements if "union all" in sql)
    assert " limit " in history_sql
    assert " offset " in history_sql


def test_summary_and_provider_latest_queries_rank_history_in_sql(query_service, db_session):
    from sqlalchemy import event

    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.lower().split()))

    event.listen(db_session.get_bind(), "before_cursor_execute", capture_statement)
    try:
        query_service.summary()
        query_service.providers()
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture_statement)

    content_sql = next(
        sql for sql in statements if "source_probe_runs" in sql and "history_rank <=" in sql
    )
    provider_sql = next(
        sql for sql in statements if "provider_probe_runs" in sql and "history_rank =" in sql
    )
    assert "row_number() over" in content_sql
    assert "row_number() over" in provider_sql


def test_gap_groups_use_fixed_order_and_keep_blocked_targets_visible(query_service):
    groups = query_service.gap_groups()
    assert [group.availability for group in groups] == ["requires_payment"]
    assert groups[0].target_count == 1
    assert groups[0].targets[0].provider_name == "X"
    assert groups[0].targets[0].alternative == "无已审核替代路径"


def test_gap_groups_keep_all_restricted_platform_records_visible(
    restricted_gap_query_service,
):
    groups = restricted_gap_query_service.gap_groups()
    platform_group = {
        target.provider_name: group.availability for group in groups for target in group.targets
    }

    assert {
        "X": "requires_payment",
        "Facebook": "requires_credentials",
        "Instagram": "requires_approval",
        "TikTok": "manual_only",
        "LinkedIn": "unavailable",
    }.items() <= platform_group.items()


def test_browser_evidence_url_fails_closed_for_non_public_schemes() -> None:
    from newsradar.web.queries import _public_evidence_url

    assert _public_evidence_url("postgresql://user:secret@localhost/database") is None
    assert _public_evidence_url("file:///local/private/path") is None
    assert _public_evidence_url("https://user:secret@example.test/feed") is None
    assert (
        _public_evidence_url("https://example.test/feed?token=secret#fragment")
        == "https://example.test/feed"
    )
def test_target_rows_have_one_conclusion_and_complete_operational_summary(
    query_service,
) -> None:
    rows = query_service.targets()
    summary = query_service.target_conclusion_summary()
    by_id = {row.source_id: row for row in rows}

    assert by_id["github-openai-python"].conclusion_code == "capable_pending_acceptance"
    assert by_id["search-ai"].conclusion_code == "indirect_discovery"
    assert by_id["x-openai"].conclusion_code == "payment_required"
    assert all(row.conclusion_label and row.conclusion_reason and row.next_action for row in rows)
    assert summary.total == len(rows)
    assert (
        summary.actual_success
        + summary.fixable
        + summary.user_action
        + summary.deferred
        == summary.total
    )
