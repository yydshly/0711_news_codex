from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import event

from newsradar.db.models import (
    EntityRecord,
    EventModelRunRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    FetchRunRecord,
    ModelUsageRecord,
    OperationRunRecord,
    RawItemRecord,
    SourceDefinitionRecord,
    SourceProbeRunRecord,
    SourceProbeSampleRecord,
    WorkerRecord,
)
from newsradar.web.capability_queries import (
    CapabilityQueryService,
    CatalogSnapshot,
    load_catalog_snapshot,
)

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def test_current_yaml_catalog_is_loaded_as_the_capability_truth():
    catalog = load_catalog_snapshot()

    assert catalog.readable is True
    assert catalog.provider_file_count == 67
    assert len(catalog.provider_ids) == 68
    assert len(catalog.target_ids) == 166
    assert len(catalog.direct_target_ids) == 48
    assert len(catalog.indirect_target_ids) == 53
    assert len(catalog.catalog_only_target_ids) == 65


def test_default_catalog_loading_is_independent_of_process_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    catalog = load_catalog_snapshot()

    assert catalog.readable is True
    assert len(catalog.target_ids) == 166


def test_missing_or_invalid_catalog_is_reported_unavailable(tmp_path):
    missing = load_catalog_snapshot(tmp_path / "missing-providers", tmp_path / "missing-sources")
    assert missing.readable is False

    provider_root = tmp_path / "providers"
    source_root = tmp_path / "sources"
    provider_root.mkdir()
    source_root.mkdir()
    project_root = Path(__file__).resolve().parents[2]
    (provider_root / "provider.yaml").write_text(
        (project_root / "providers" / "ai-snake-oil.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (source_root / "broken.yaml").write_text("id: [broken", encoding="utf-8")

    invalid = load_catalog_snapshot(provider_root, source_root)
    assert invalid.readable is False


def _catalog() -> CatalogSnapshot:
    return CatalogSnapshot(
        readable=True,
        provider_file_count=2,
        provider_ids=frozenset({"github", "x", "independent"}),
        target_ids=frozenset({"github-openai-python", "search-ai", "x-openai"}),
        direct_target_ids=frozenset({"github-openai-python", "x-openai"}),
        ready_direct_target_ids=frozenset({"github-openai-python"}),
        indirect_target_ids=frozenset({"search-ai"}),
        catalog_only_target_ids=frozenset(),
    )


def _seed_outputs(db_session) -> None:
    db_session.add(
        SourceDefinitionRecord(
            id="legacy-source",
            name="Legacy",
            provider_id="independent",
            target_type="publisher_feed",
            availability="ready",
            coverage_mode="direct",
            status="candidate",
            nature="first_party",
            language="en",
            roles=["discovery"],
            topics=["ai"],
            authority_score=1,
            poll_interval_minutes=60,
            expected_fields=["title", "canonical_url"],
            definition_hash="legacy",
        )
    )
    db_session.flush()
    probe = SourceProbeRunRecord(
        source_id="github-openai-python",
        access_kind="rss",
        access_url="https://feeds.example/github-openai-python",
        outcome="success",
        started_at=NOW - timedelta(seconds=1),
        finished_at=NOW,
        latency_ms=10,
        http_status=200,
        final_url="https://feeds.example/github-openai-python",
        response_headers={},
        metrics={"sample_count": 1, "field_completeness": 1.0},
        schema_fingerprint="current-schema",
        suggested_status="active",
        reason="ok",
    )
    db_session.add(probe)
    db_session.flush()
    db_session.add(
        SourceProbeSampleRecord(
            probe_run_id=probe.id,
            sample_index=0,
            canonical_url="https://example.com/current",
            published_at=NOW,
            fields_present=["title", "canonical_url"],
            sample_hash="sample",
        )
    )
    for source_id, outcome in (
        ("github-openai-python", "succeeded"),
        ("github-openai-python", "no_change"),
        ("search-ai", "failed"),
        ("legacy-source", "succeeded"),
    ):
        db_session.add(
            FetchRunRecord(
                source_id=source_id,
                started_at=NOW - timedelta(hours=1),
                finished_at=NOW,
                outcome=outcome,
            )
        )
    db_session.add_all(
        [
            RawItemRecord(
                source_id="github-openai-python",
                external_id="current",
                canonical_url="https://example.com/current",
                payload={},
                title="当前来源条目",
                published_at=NOW - timedelta(minutes=10),
                fetched_at=NOW,
            ),
            RawItemRecord(
                source_id="legacy-source",
                external_id="legacy",
                canonical_url="https://example.com/legacy",
                payload={},
                title="残留条目",
                fetched_at=NOW,
            ),
        ]
    )
    event = EventRecord(
        canonical_key="event-1",
        status="confirmed",
        occurred_at=NOW - timedelta(minutes=5),
        current_version_number=1,
    )
    db_session.add(event)
    db_session.flush()
    db_session.add_all(
        [
            EventVersionRecord(
                event_id=event.id,
                version_number=1,
                zh_title="测试事件",
                zh_summary="测试摘要",
                payload={},
            ),
            EventScoreRecord(
                event_id=event.id,
                version_number=1,
                heat=8.5,
                breakdown={},
            ),
            EntityRecord(
                canonical_key="openai",
                entity_type="organization",
                name="OpenAI",
                aliases=[],
            ),
            ModelUsageRecord(
                purpose="event_enrichment",
                model="MiniMax-M3",
                input_tokens=10,
                output_tokens=5,
                outcome="success",
            ),
            EventModelRunRecord(
                event_id=event.id,
                stage="enrichment",
                algorithm_version="minimax-v1",
            ),
            WorkerRecord(
                worker_id="recent-worker",
                hostname="local",
                process_id=1,
                started_at=NOW - timedelta(hours=1),
                last_heartbeat_at=NOW - timedelta(minutes=1),
                status="idle",
            ),
            WorkerRecord(
                worker_id="old-worker",
                hostname="local",
                process_id=2,
                started_at=NOW - timedelta(days=2),
                last_heartbeat_at=NOW - timedelta(hours=1),
                status="running",
            ),
            OperationRunRecord(
                operation_type="fetch",
                trigger="manual",
                status="failed",
                requested_scope={},
                result_summary={},
                created_at=NOW,
                updated_at=NOW,
            ),
        ]
    )
    db_session.commit()


def test_capability_overview_uses_catalog_truth_and_runtime_facts(db_session):
    _seed_outputs(db_session)

    view = CapabilityQueryService(db_session).build(_catalog(), minimax_configured=True, now=NOW)

    assert view.provider_count == 3
    assert view.target_count == 3
    assert view.db_target_count == 4
    assert view.db_only_target_ids == ("legacy-source",)
    assert view.catalog_only_db_target_ids == ()
    assert view.latest_probe_counts == (("success", 1), ("unprobed", 2))
    assert view.trial_eligible_count == 1
    assert view.fetched_source_count == 1
    assert view.fetch_outcome_counts == (
        ("failed", 1),
        ("no_change", 1),
        ("succeeded", 1),
    )
    assert view.raw_item_count == 1
    assert view.raw_source_count == 1
    assert [item.title for item in view.recent_items] == ["当前来源条目"]
    assert view.event_count == 1
    assert view.confirmed_event_count == 1
    assert view.recent_events[0].title == "测试事件"
    assert view.recent_events[0].heat == 8.5
    assert view.minimax_configured is True
    assert view.model_usage_count == 1
    assert view.event_model_run_count == 1
    assert view.entity_count == 1
    assert view.recent_worker_activity_count == 1
    assert view.operation_status_counts == (("failed", 1),)
    assert any(gap.key == "catalog_drift" for gap in view.gaps)


def test_capability_overview_does_not_expose_sensitive_configuration(db_session):
    view = CapabilityQueryService(db_session).build(_catalog(), minimax_configured=False, now=NOW)

    serialized = repr(view)
    assert view.minimax_configured is False
    assert any(gap.key == "minimax_not_configured" for gap in view.gaps)
    for secret in (
        "MINIMAX_API_KEY",
        "DATABASE_URL",
        "Authorization",
        "Cookie",
        "proxy",
    ):
        assert secret not in serialized


def test_indirect_fetch_does_not_hide_ready_direct_fetch_gap(db_session):
    db_session.add(
        FetchRunRecord(
            source_id="search-ai",
            started_at=NOW,
            finished_at=NOW,
            outcome="succeeded",
        )
    )
    db_session.commit()

    view = CapabilityQueryService(db_session).build(_catalog(), minimax_configured=False, now=NOW)

    assert view.fetched_source_count == 1
    fetch_gap = next(gap for gap in view.gaps if gap.key == "fetch_coverage")
    assert "0 个完成过真实抓取" in fetch_gap.meaning


def test_recent_event_preview_is_a_single_database_limited_query(db_session):
    _seed_outputs(db_session)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        view = CapabilityQueryService(db_session).build(
            _catalog(), minimax_configured=True, now=NOW
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    preview_queries = [
        statement
        for statement in statements
        if "event_versions" in statement and "join event_versions" in statement
    ]
    assert len(view.recent_events) == 1
    assert len(preview_queries) == 1
    assert "limit" in preview_queries[0]


def test_unreadable_catalog_falls_back_to_database_and_marks_gap(db_session):
    snapshot = CatalogSnapshot.unavailable("catalog unavailable")

    view = CapabilityQueryService(db_session).build(snapshot, minimax_configured=False, now=NOW)

    assert view.catalog_readable is False
    assert view.target_count == 3
    assert any(gap.key == "catalog_unreadable" for gap in view.gaps)
