from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from newsradar.web.viewmodels import DashboardSummary


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
    content = next(row for row in rows if row.probe_type == "content")
    assert content.probe_type_label == "内容探测"


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


def test_catalog_rows_include_list_metadata_without_detail_queries(query_service):
    provider = next(row for row in query_service.providers() if row.provider_id == "github")
    assert provider.auth_mode == "none"
    assert provider.auth_label == "无需认证"
    assert provider.capabilities == ("search",)

    target = next(
        row for row in query_service.targets() if row.source_id == "github-openai-python"
    )
    assert target.roles == ("discovery",)
    assert target.role_labels == ("发现",)


def test_details_contain_audited_fields_but_no_secret_values(query_service):
    provider = query_service.provider_detail("x")
    assert provider is not None
    assert provider.required_env == ("X_API_KEY",)
    assert provider.targets[0].source_id == "x-openai"

    target = query_service.target_detail("x-openai")
    assert target is not None
    assert target.access_methods[0].auth_env == "X_API_KEY"
    assert "headers" not in target.access_methods[0].__dataclass_fields__
    assert "secret-token-value" not in repr(target)
    assert target.risk is not None


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


def test_gap_groups_use_fixed_order_and_keep_blocked_targets_visible(query_service):
    groups = query_service.gap_groups()
    assert [group.availability for group in groups] == ["requires_payment"]
    assert groups[0].target_count == 1
    assert groups[0].targets[0].provider_name == "X"
    assert groups[0].targets[0].alternative == "无已审核替代路径"
