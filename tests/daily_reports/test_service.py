from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from newsradar.daily_reports import DailyReportService
from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.service import _public_url
from newsradar.db.models import (
    Base,
    DailyReportOverviewItemRecord,
    DailyReportRecord,
    EventItemRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    OperationRunRecord,
    ProviderDefinitionRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS
from newsradar.web.event_queries import EventQueryService

NOW = datetime(2026, 7, 16, 4, tzinfo=UTC)
SEEDED_WINDOW_END = NOW
SEEDED_OPERATION_ID = 2301
BROKEN_EVENT_ID = 202

EXPECTED_SNAPSHOT_KEYS = {
    "zh_title",
    "zh_summary",
    "why_it_matters",
    "status",
    "unconfirmed",
    "display_tier",
    "category",
    "rank_score",
    "occurred_at",
    "independent_root_count",
    "confirmation_summary",
    "enrichment_origin",
    "limitations",
    "evidence",
}
EXPECTED_EVIDENCE_KEYS = {
    "title",
    "url",
    "published_at",
    "role",
    "independent",
    "limitations",
}


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            ProviderDefinitionRecord(
                id="github",
                name="GitHub",
                category="research_developer",
                homepage="https://github.com/",
                docs_url="https://docs.github.com/",
                terms_url="https://docs.github.com/site-policy/github-terms/",
                auth_mode="none",
                cost_tier="free",
                availability="ready",
                capabilities=["repository"],
                required_env=[],
                reviewed_at=date(2026, 7, 16),
                evidence=["https://docs.github.com/"],
                unlock_requirements=[],
                definition_hash="github-test-hash",
            )
        )
        session.add(
            SourceDefinitionRecord(
                id="github-openai-python",
                name="OpenAI Python",
                provider_id="github",
                target_type="publisher_feed",
                availability="ready",
                coverage_mode="direct",
                official_identity_url="https://github.com/openai/openai-python",
                unlock_requirements=[],
                status="active",
                nature="first_party",
                language="en",
                roles=["discovery", "evidence"],
                topics=["ai"],
                authority_score=100,
                poll_interval_minutes=60,
                expected_fields=["title", "canonical_url"],
                definition_hash="github-openai-python-test-hash",
            )
        )
        session.commit()
        yield session
    engine.dispose()


def _seed_snapshot_event(
    session: Session,
    *,
    event_id: int,
    status: str,
    display_tier: str,
    rank_score: float,
    occurred_at: datetime | None,
    enrichment_origin: str = "model",
) -> None:
    event_time = occurred_at or NOW
    event = EventRecord(
        id=event_id,
        canonical_key=f"daily-snapshot-{event_id}",
        visibility="current",
        display_tier=display_tier,
        rank_score=rank_score,
        status=status,
        occurred_at=occurred_at,
        current_version_number=1,
    )
    raw = RawItemRecord(
        source_id="github-openai-python",
        external_id=f"daily-evidence-{event_id}",
        canonical_url=f"https://example.com/evidence/{event_id}?token=hidden",
        original_url=f"https://example.com/evidence/{event_id}?token=hidden#fragment",
        payload={},
        title=f"证据 {event_id}",
        published_at=event_time,
    )
    session.add_all((event, raw))
    session.flush()
    payload = {
        "status": status,
        "category": "product_model",
        "publication": {"tier": display_tier},
        "enrichment": {
            "why_it_matters": "影响行业采用路径。",
            "limitations": [],
            "origin": enrichment_origin,
        },
        "evidence_summary": {
            "official_roots": 1 if status == "confirmed" else 0,
            "professional_roots": 0,
        },
        "evidence": [
            {
                "raw_item_id": raw.id,
                "role": "official",
                "root_evidence_key": f"official:{event_id}",
                "independent": True,
                "limitations": [],
            }
        ],
        "private_debug": {"token": "must-not-be-copied"},
    }
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at.isoformat()
    session.add_all(
        (
            EventVersionRecord(
                event_id=event_id,
                version_number=1,
                zh_title=f"事件 {event_id}",
                zh_summary="固定中文摘要",
                payload=payload,
                created_at=NOW,
            ),
            EventItemRecord(
                event_id=event_id,
                raw_item_id=raw.id,
                added_version_number=1,
            ),
            EventScoreRecord(
                event_id=event_id,
                version_number=1,
                heat=rank_score,
                breakdown={
                    "ai_relevance": 90,
                    "source_coverage": 70,
                    "source_authority": 90,
                    "recency": 100,
                    "engagement_velocity": 0,
                    "novelty": 70,
                    "importance": rank_score,
                    "credibility": 90,
                    "heat": rank_score,
                    "rule_version": "score-v2",
                    "reasons": ["official_evidence"],
                },
                created_at=NOW,
            ),
        )
    )


def seed_complete_snapshot(
    session: Session,
    *,
    confirmed: tuple[int, ...] = (101, 102),
    emerging: tuple[int, ...] = (201, 202),
) -> int:
    refs: list[tuple[int, int]] = []
    for index, event_id in enumerate(confirmed):
        _seed_snapshot_event(
            session,
            event_id=event_id,
            status="confirmed",
            display_tier="hotspot",
            rank_score=95 - index,
            occurred_at=NOW - timedelta(hours=index + 1),
        )
        refs.append((event_id, 1))
    for index, event_id in enumerate(emerging):
        _seed_snapshot_event(
            session,
            event_id=event_id,
            status="emerging",
            display_tier="signal",
            rank_score=85 - index,
            occurred_at=NOW - timedelta(hours=index + 1),
            enrichment_origin="rule_fallback" if index == 0 else "model",
        )
        refs.append((event_id, 1))
    for event_id, tier, occurred_at in (
        (301, "audit_only", NOW - timedelta(hours=1)),
        (302, "signal", NOW - timedelta(hours=25)),
        (303, "signal", None),
    ):
        _seed_snapshot_event(
            session,
            event_id=event_id,
            status="emerging",
            display_tier=tier,
            rank_score=70,
            occurred_at=occurred_at,
        )
        refs.append((event_id, 1))
    session.add(
        OperationRunRecord(
            id=SEEDED_OPERATION_ID,
            operation_type="event_pipeline",
            trigger="test",
            status="succeeded",
            requested_scope={
                "window_hours": 72,
                "window_end": NOW.isoformat(),
                "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
            },
            result_summary={
                "event_version_snapshots": [
                    {"event_id": event_id, "version_number": version}
                    for event_id, version in refs
                ]
            },
            created_at=NOW,
            finished_at=NOW,
        )
    )
    session.commit()
    return SEEDED_OPERATION_ID


def seed_ranked_snapshot(
    session: Session,
    *,
    confirmed_count: int,
    emerging_count: int,
) -> None:
    seed_complete_snapshot(
        session,
        confirmed=tuple(range(1001, 1001 + confirmed_count)),
        emerging=tuple(range(2001, 2001 + emerging_count)),
    )


def test_generate_freezes_confirmed_and_emerging_in_separate_sections(
    db_session: Session,
) -> None:
    seed_complete_snapshot(db_session)

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    rows = DailyReportRepository(db_session).items(report.id)

    confirmed = [row for row in rows if row.section == "confirmed"]
    emerging = [row for row in rows if row.section == "emerging"]
    assert [row.snapshot["status"] for row in confirmed] == ["confirmed", "confirmed"]
    assert all(row.snapshot["status"] == "emerging" for row in emerging)
    assert all(row.snapshot["unconfirmed"] is True for row in emerging)
    assert all(row.snapshot["unconfirmed"] is False for row in confirmed)
    assert all(row.snapshot["display_tier"] != "audit_only" for row in emerging)
    assert all(set(row.snapshot) == EXPECTED_SNAPSHOT_KEYS for row in rows)
    assert all(
        set(evidence) == EXPECTED_EVIDENCE_KEYS
        for row in rows
        for evidence in row.snapshot["evidence"]
    )
    assert report.source_operation_id == SEEDED_OPERATION_ID
    stored_window_end = (
        report.window_end.replace(tzinfo=UTC)
        if report.window_end.tzinfo is None
        else report.window_end.astimezone(UTC)
    )
    assert stored_window_end == SEEDED_WINDOW_END


def test_generate_from_operation_uses_exact_snapshot(db_session: Session) -> None:
    operation_id = seed_complete_snapshot(db_session)
    operation = db_session.get(OperationRunRecord, operation_id)
    assert operation is not None
    operation.requested_scope["window_hours"] = 24
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(operation, "requested_scope")
    db_session.add(
        OperationRunRecord(
            id=operation_id + 1,
            operation_type="event_pipeline",
            trigger="test",
            status="succeeded",
            requested_scope={
                "window_hours": 24,
                "window_end": NOW.isoformat(),
                "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
            },
            result_summary={"event_version_snapshots": []},
            created_at=NOW,
            finished_at=NOW,
        )
    )
    db_session.commit()

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate_from_operation(
        operation_id,
        24,
        now=NOW,
    )

    assert report.source_operation_id == operation_id
    assert DailyReportRepository(db_session).items(report.id)


def test_generate_persists_every_displayable_operation_event_for_overview(
    db_session: Session,
) -> None:
    seed_complete_snapshot(db_session)

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    rows = DailyReportRepository(db_session).overview_items(report.id)

    assert [row.event_id for row in rows] == [101, 102, 201, 202, 302]
    assert [row.position for row in rows] == list(range(1, 6))
    assert all(set(row.snapshot) == EXPECTED_SNAPSHOT_KEYS for row in rows)
    assert {
        row.event_id for row in rows if row.decision_item_id is not None
    } == {101, 102, 201, 202}
    assert report.generation_summary["overview_count"] == 5


def test_generate_skips_invalid_overview_only_event_without_blocking_report(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_complete_snapshot(db_session)
    original = EventQueryService.get_operation_event

    def missing_overview_detail(self, event_id, *args, **kwargs):
        if event_id == 302:
            return None
        return original(self, event_id, *args, **kwargs)

    monkeypatch.setattr(EventQueryService, "get_operation_event", missing_overview_detail)

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)

    assert [
        row.event_id for row in DailyReportRepository(db_session).overview_items(report.id)
    ] == [101, 102, 201, 202]
    assert report.generation_summary["skipped_invalid_overview_event"] == 1
    assert len(DailyReportRepository(db_session).items(report.id)) == 4


def test_revise_materializes_overview_for_legacy_archived_report(
    db_session: Session,
) -> None:
    seed_complete_snapshot(db_session)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = service.generate(24, now=NOW)
    db_session.execute(
        delete(DailyReportOverviewItemRecord).where(
            DailyReportOverviewItemRecord.daily_report_id == original.id
        )
    )
    db_session.commit()
    repository.archive(original.id)

    revision = service.revise(original.id)

    assert repository.overview_items(original.id) == ()
    copied = repository.overview_items(revision.id)
    assert [row.event_id for row in copied] == [101, 102, 201, 202, 302]
    assert [row.snapshot["zh_title"] for row in copied] == [
        "事件 101",
        "事件 102",
        "事件 201",
        "事件 202",
        "事件 302",
    ]


def test_generate_sanitizes_evidence_and_never_calls_network_or_model(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_complete_snapshot(db_session)
    monkeypatch.setattr(
        "httpx.Client.request",
        lambda *args, **kwargs: pytest.fail("network"),
    )
    monkeypatch.setattr(
        "httpx.AsyncClient.request",
        lambda *args, **kwargs: pytest.fail("network"),
    )
    monkeypatch.setattr(
        "newsradar.ai.minimax.MiniMaxClient.structured",
        lambda *args, **kwargs: pytest.fail("model"),
    )

    def forbidden_text_enricher(*_args, **_kwargs):
        raise AssertionError("manual report generation must remain read-only")

    monkeypatch.setattr(
        "newsradar.daily_reports.chinese_enrichment.DailyReportChineseEnricher.__init__",
        forbidden_text_enricher,
    )

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    evidence = DailyReportRepository(db_session).items(report.id)[0].snapshot["evidence"]

    assert all("?" not in (item["url"] or "") for item in evidence)
    assert all("#" not in (item["url"] or "") for item in evidence)
    assert all("@" not in (item["url"] or "") for item in evidence)


def test_public_url_rejects_malformed_ipv6() -> None:
    assert _public_url("https://[invalid/evidence") is None


@pytest.mark.parametrize(
    "url",
    (
        "http://localhost/evidence",
        "https://news.localhost/evidence",
        "http://127.0.0.1/evidence",
        "http://10.0.0.8/evidence",
        "http://172.16.0.8/evidence",
        "http://192.168.1.8/evidence",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/evidence",
        "http://[fe80::1]/evidence",
        "http://[ff02::1]/evidence",
        "http://100.64.0.1/evidence",
        "http://2130706433/evidence",
        "http://0x7f000001/evidence",
        "http://127.1/evidence",
        "http://0177.0.0.1/evidence",
        "http://127.0.0.1\\foo",
        "http://10.0.0.1\\foo",
        "http://127%2e0%2e0%2e1/evidence",
        "http://example.com/evidence\tignored",
    ),
)
def test_public_url_rejects_local_and_non_public_ip_literals(url: str) -> None:
    assert _public_url(url) is None


@pytest.mark.parametrize(
    ("url", "expected"),
    (
        (
            "https://example.com/evidence?token=hidden#fragment",
            "https://example.com/evidence",
        ),
        ("https://8.8.8.8/evidence", "https://8.8.8.8/evidence"),
        ("https://example.com./evidence", "https://example.com/evidence"),
        ("https://[2606:4700:4700::1111]/dns", "https://[2606:4700:4700::1111]/dns"),
    ),
)
def test_public_url_keeps_public_hosts_without_query_or_fragment(
    url: str, expected: str
) -> None:
    assert _public_url(url) == expected


@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1/evidence",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.8/evidence",
        "http://[::1]/evidence",
        "http://2130706433/evidence",
        "http://0x7f000001/evidence",
        "http://127.1/evidence",
        "http://0177.0.0.1/evidence",
        "http://127.0.0.1\\foo",
        "http://10.0.0.1\\foo",
        "http://100.64.0.1/evidence",
    ),
)
def test_generate_drops_non_public_evidence_url_from_snapshot(
    db_session: Session, url: str
) -> None:
    seed_complete_snapshot(db_session)
    raw = db_session.scalar(
        select(RawItemRecord)
        .join(EventItemRecord, EventItemRecord.raw_item_id == RawItemRecord.id)
        .where(EventItemRecord.event_id == 101)
    )
    assert raw is not None
    raw.original_url = url
    db_session.commit()

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    row = next(
        item for item in DailyReportRepository(db_session).items(report.id) if item.event_id == 101
    )

    assert row.snapshot["evidence"][0]["url"] is None


def test_generate_skips_malformed_evidence_url_and_keeps_later_event(
    db_session: Session,
) -> None:
    seed_complete_snapshot(db_session)
    broken_raw = db_session.scalar(
        select(RawItemRecord)
        .join(EventItemRecord, EventItemRecord.raw_item_id == RawItemRecord.id)
        .where(EventItemRecord.event_id == 101)
    )
    assert broken_raw is not None
    broken_raw.original_url = "https://[invalid/evidence"
    db_session.commit()

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    rows = DailyReportRepository(db_session).items(report.id)

    assert report.generation_summary["skipped_invalid_event"] == 1
    assert [row.event_id for row in rows if row.section == "confirmed"] == [102]


def test_generate_skips_malformed_detail_snapshot_and_keeps_later_event(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_complete_snapshot(db_session)
    original = EventQueryService.get_operation_event

    def malformed_detail(self, event_id, *args, **kwargs):
        detail = original(self, event_id, *args, **kwargs)
        return replace(detail, limitations=None) if event_id == 101 else detail

    monkeypatch.setattr(EventQueryService, "get_operation_event", malformed_detail)

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    rows = DailyReportRepository(db_session).items(report.id)

    assert report.generation_summary["skipped_invalid_event"] == 1
    assert [row.event_id for row in rows if row.section == "confirmed"] == [102]


def test_generate_requires_complete_snapshot_and_writes_nothing(
    db_session: Session,
) -> None:
    with pytest.raises(ValueError, match="complete_event_snapshot_required"):
        DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    assert db_session.scalar(select(func.count()).select_from(DailyReportRecord)) == 0


def test_generate_rejects_multiple_versions_of_same_event_without_writing(
    db_session: Session,
) -> None:
    seed_complete_snapshot(db_session)
    first_version = db_session.scalar(
        select(EventVersionRecord).where(
            EventVersionRecord.event_id == 101,
            EventVersionRecord.version_number == 1,
        )
    )
    first_score = db_session.scalar(
        select(EventScoreRecord).where(
            EventScoreRecord.event_id == 101,
            EventScoreRecord.version_number == 1,
        )
    )
    operation = db_session.get(OperationRunRecord, SEEDED_OPERATION_ID)
    assert first_version is not None
    assert first_score is not None
    assert operation is not None
    db_session.add_all(
        (
            EventVersionRecord(
                event_id=101,
                version_number=2,
                zh_title="事件 101 第二版本",
                zh_summary=first_version.zh_summary,
                payload=dict(first_version.payload),
                created_at=NOW,
            ),
            EventScoreRecord(
                event_id=101,
                version_number=2,
                heat=first_score.heat,
                breakdown=dict(first_score.breakdown),
                created_at=NOW,
            ),
        )
    )
    summary = dict(operation.result_summary)
    summary["event_version_snapshots"] = [
        *summary["event_version_snapshots"],
        {"event_id": 101, "version_number": 2},
    ]
    operation.result_summary = summary
    db_session.commit()

    with pytest.raises(ValueError, match="ambiguous_event_snapshot_versions"):
        DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    assert db_session.scalar(select(func.count()).select_from(DailyReportRecord)) == 0


def test_generate_allows_empty_sections_without_lowering_threshold(
    db_session: Session,
) -> None:
    seed_complete_snapshot(db_session, confirmed=(), emerging=())

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)

    assert DailyReportRepository(db_session).items(report.id) == ()


def test_generate_caps_each_section_and_keeps_stable_order(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_ranked_snapshot(db_session, confirmed_count=25, emerging_count=25)
    original = EventQueryService.get_operation_event
    monkeypatch.setattr(
        EventQueryService,
        "get_operation_event",
        lambda self, event_id, *args, **kwargs: (
            None
            if event_id == 1001
            else original(self, event_id, *args, **kwargs)
        ),
    )

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    rows = DailyReportRepository(db_session).items(report.id)

    for section in ("confirmed", "emerging"):
        selected = [row for row in rows if row.section == section]
        assert len(selected) == 20
        assert [row.position for row in selected] == list(range(1, 21))
        assert [row.snapshot["rank_score"] for row in selected] == sorted(
            (row.snapshot["rank_score"] for row in selected),
            reverse=True,
        )
    assert report.generation_summary["skipped_invalid_event"] == 1


def test_generate_skips_invalid_detail_and_records_rule_fallback(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_complete_snapshot(db_session)
    original = EventQueryService.get_operation_event
    monkeypatch.setattr(
        EventQueryService,
        "get_operation_event",
        lambda self, event_id, *args, **kwargs: (
            None
            if event_id == BROKEN_EVENT_ID
            else original(self, event_id, *args, **kwargs)
        ),
    )

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)

    assert report.generation_summary["skipped_invalid_event"] == 1
    assert report.generation_summary["skipped_missing_time"] == 1
    assert report.generation_summary["minimax_degraded"] is True


def test_revise_copies_archived_report_without_refreshing_snapshot(
    db_session: Session,
) -> None:
    seed_complete_snapshot(db_session)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = service.generate(24, now=NOW)
    frozen_snapshots = [row.snapshot for row in repository.items(original.id)]
    repository.archive(original.id)

    revision = service.revise(original.id)

    assert revision.supersedes_report_id == original.id
    assert [row.snapshot for row in repository.items(revision.id)] == frozen_snapshots
