from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from newsradar.daily_reports import DailyReportService
from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.schema import (
    REPORT_TIMEZONE,
    DailyReportDraft,
    DailyReportEditorialReviewDraft,
    DailyReportItemDraft,
    DailyReportOverviewEditorialReviewDraft,
    DailyReportOverviewItemDraft,
    EditorialDecision,
    ReportSection,
)
from newsradar.daily_reports.service import _decision_drafts, _public_url
from newsradar.db.models import (
    Base,
    DailyReportOverviewItemRecord,
    DailyReportRecord,
    EventItemRecord,
    EventMergeCandidateRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    OperationRunRecord,
    ProviderDefinitionRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.event_merges.schema import MergeApplyResult
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
EXPECTED_OVERVIEW_SNAPSHOT_KEYS = EXPECTED_SNAPSHOT_KEYS | {"daily_disposition"}
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


def _seed_operation_with_ids(
    session: Session,
    operation_id: int,
    event_ids: tuple[int, ...],
    window_end: datetime,
    *,
    window_hours: int = 24,
) -> int:
    refs: list[tuple[int, int]] = []
    for index, event_id in enumerate(event_ids):
        event = session.get(EventRecord, event_id)
        if event is None:
            _seed_snapshot_event(
                session,
                event_id=event_id,
                status="confirmed",
                display_tier="hotspot",
                rank_score=100 - index,
                occurred_at=window_end - timedelta(minutes=index + 1),
            )
            version_number = 1
        else:
            version_number = event.current_version_number
        refs.append((event_id, version_number))
    session.add(
        OperationRunRecord(
            id=operation_id,
            operation_type="event_pipeline",
            trigger="test",
            status="succeeded",
            requested_scope={
                "window_hours": window_hours,
                "window_end": window_end.isoformat(),
                "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
            },
            result_summary={
                "event_version_snapshots": [
                    {"event_id": event_id, "version_number": version_number}
                    for event_id, version_number in refs
                ]
            },
            created_at=window_end,
            finished_at=window_end,
        )
    )
    session.commit()
    return operation_id


def seed_complete_snapshot(
    session: Session,
    *,
    confirmed: tuple[int, ...] = (101, 102),
    emerging: tuple[int, ...] = (201, 202),
    audit_only: tuple[int, ...] | None = None,
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
    if audit_only is None:
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
    else:
        for index, event_id in enumerate(audit_only):
            _seed_snapshot_event(
                session,
                event_id=event_id,
                status="emerging",
                display_tier="audit_only",
                rank_score=70 - index,
                occurred_at=NOW - timedelta(hours=index + 1),
            )
            refs.append((event_id, 1))
    session.add(
        OperationRunRecord(
            id=SEEDED_OPERATION_ID,
            operation_type="event_pipeline",
            trigger="test",
            status="succeeded",
            requested_scope={
                "window_hours": 24 if audit_only is not None else 72,
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


def _daily_report_draft(
    session: Session,
    *,
    source_operation_id: int,
    report_date: date = date(2026, 7, 19),
    window_hours: int = 24,
    supersedes_report_id: int | None = None,
    decision_event_versions: tuple[tuple[int, int], ...] = (),
    overview_event_versions: tuple[tuple[int, int], ...] = (),
) -> DailyReportDraft:
    if session.get(OperationRunRecord, source_operation_id) is None:
        session.add(
            OperationRunRecord(
                id=source_operation_id,
                operation_type="event_pipeline",
                trigger="test",
                status="succeeded",
                requested_scope={},
                result_summary={},
                created_at=NOW,
                finished_at=NOW,
            )
        )
    for event_id, version_number in {
        *decision_event_versions,
        *overview_event_versions,
    }:
        event = session.get(EventRecord, event_id)
        if event is None:
            session.add(
                EventRecord(
                    id=event_id,
                    canonical_key=f"daily-report-lifecycle-{event_id}",
                    status="confirmed",
                    current_version_number=version_number,
                    occurred_at=NOW,
                )
            )
        elif event.current_version_number < version_number:
            event.current_version_number = version_number
    session.commit()
    return DailyReportDraft(
        report_date=report_date,
        window_hours=window_hours,
        window_start=NOW - timedelta(hours=window_hours),
        window_end=NOW,
        source_operation_id=source_operation_id,
        generation_summary={},
        supersedes_report_id=supersedes_report_id,
        items=tuple(
            DailyReportItemDraft(
                event_id=event_id,
                event_version_number=version_number,
                section=ReportSection.CONFIRMED,
                position=position,
                snapshot={"zh_title": f"Event {event_id} v{version_number}"},
            )
            for position, (event_id, version_number) in enumerate(
                decision_event_versions, start=1
            )
        ),
        overview_items=tuple(
            DailyReportOverviewItemDraft(
                event_id=event_id,
                event_version_number=version_number,
                position=position,
                snapshot={"zh_title": f"Event {event_id} v{version_number}"},
            )
            for position, (event_id, version_number) in enumerate(
                overview_event_versions, start=1
            )
        ),
    )


def _archived_report(
    session: Session,
    *,
    report_date: date = date(2026, 7, 19),
    revision: int,
    window_hours: int = 24,
    decision_event_versions: tuple[tuple[int, int], ...] = (),
    overview_event_versions: tuple[tuple[int, int], ...] = (),
    reviewed_decision_event_version: tuple[int, int] | None = None,
    reviewed_event_version: tuple[int, int] | None = None,
) -> DailyReportRecord:
    source_operation_id = int(report_date.strftime("%m%d")) * 100 + revision
    repository = DailyReportRepository(session, utcnow=lambda: NOW)
    report = repository.create_draft(
        _daily_report_draft(
            session,
            source_operation_id=source_operation_id,
            report_date=report_date,
            window_hours=window_hours,
            decision_event_versions=decision_event_versions,
            overview_event_versions=overview_event_versions,
        )
    )
    assert report.revision == revision
    if reviewed_decision_event_version is not None:
        reviewed_item = next(
            item
            for item in repository.items(report.id)
            if (item.event_id, item.event_version_number)
            == reviewed_decision_event_version
        )
        repository.save_editorial_review(
            report.id,
            reviewed_item.id,
            DailyReportEditorialReviewDraft.create(
                decision="keep",
                zh_title="Reviewed title",
                zh_summary="Reviewed summary",
                review_recommendation="Keep this event.",
                evidence_assessment="Evidence is sufficient.",
            ),
        )
    if reviewed_event_version is not None:
        reviewed_item = next(
            item
            for item in repository.overview_items(report.id)
            if (item.event_id, item.event_version_number) == reviewed_event_version
        )
        repository.save_overview_editorial_review(
            report.id,
            reviewed_item.id,
            DailyReportOverviewEditorialReviewDraft.create(
                decision="keep",
                zh_title="Reviewed title",
                zh_summary="Reviewed summary",
                review_recommendation="Keep this event.",
                evidence_assessment="Evidence is sufficient.",
            ),
        )
    return repository.archive(report.id)


def _archived_report_with_review(
    session: Session,
    *,
    event_id: int,
    version: int,
) -> DailyReportRecord:
    return _archived_report(
        session,
        revision=1,
        overview_event_versions=((event_id, version),),
        reviewed_event_version=(event_id, version),
    )


def test_latest_archived_for_day_returns_only_latest_eligible_report(
    db_session: Session,
) -> None:
    older = _archived_report(db_session, revision=1)
    latest = _archived_report(db_session, revision=2)
    deleted = _archived_report(db_session, revision=3)
    deleted.deleted_at = NOW
    other_day = _archived_report(
        db_session, report_date=date(2026, 7, 18), revision=1
    )
    db_session.commit()

    selected = DailyReportRepository(db_session).latest_archived_for_day(
        date(2026, 7, 19), excluding_operation_id=9999
    )

    assert selected is not None
    assert selected.id == latest.id
    assert selected.id not in {older.id, deleted.id, other_day.id}


def test_create_cumulative_draft_links_predecessor_and_copies_matching_review(
    db_session: Session,
) -> None:
    predecessor = _archived_report_with_review(db_session, event_id=101, version=1)
    draft = _daily_report_draft(
        db_session,
        source_operation_id=2402,
        supersedes_report_id=predecessor.id,
        overview_event_versions=((101, 1), (102, 1)),
    )

    successor = DailyReportRepository(db_session).create_cumulative_draft(draft)
    copied = DailyReportRepository(db_session).overview_items(successor.id)

    assert successor.supersedes_report_id == predecessor.id
    assert successor.revision == predecessor.revision + 1
    assert len(
        DailyReportRepository(db_session).overview_editorial_reviews(copied[0].id)
    ) == 1
    assert (
        DailyReportRepository(db_session).overview_editorial_reviews(copied[1].id)
        == ()
    )


def test_create_cumulative_draft_keeps_one_chain_across_window_sizes(
    db_session: Session,
) -> None:
    predecessor = _archived_report(db_session, revision=1, window_hours=72)
    draft = _daily_report_draft(
        db_session,
        source_operation_id=2402,
        window_hours=24,
        supersedes_report_id=predecessor.id,
    )

    successor = DailyReportRepository(db_session).create_cumulative_draft(draft)

    assert successor.supersedes_report_id == predecessor.id
    assert successor.revision == predecessor.revision + 1


def test_create_cumulative_draft_does_not_copy_review_to_new_event_version(
    db_session: Session,
) -> None:
    predecessor = _archived_report_with_review(db_session, event_id=101, version=1)
    draft = _daily_report_draft(
        db_session,
        source_operation_id=2402,
        supersedes_report_id=predecessor.id,
        overview_event_versions=((101, 2),),
    )

    successor = DailyReportRepository(db_session).create_cumulative_draft(draft)
    item = DailyReportRepository(db_session).overview_items(successor.id)[0]

    assert DailyReportRepository(db_session).overview_editorial_reviews(item.id) == ()


def test_create_cumulative_draft_retargets_duplicate_review_to_newer_target_version(
    db_session: Session,
) -> None:
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    predecessor = repository.create_draft(
        _daily_report_draft(
            db_session,
            source_operation_id=2401,
            overview_event_versions=((101, 1), (102, 1)),
        )
    )
    target, duplicate = repository.overview_items(predecessor.id)
    source_review = repository.save_overview_editorial_review(
        predecessor.id,
        duplicate.id,
        DailyReportOverviewEditorialReviewDraft.create(
            decision="duplicate",
            zh_title="Duplicate event",
            zh_summary="This event duplicates the target.",
            review_recommendation="Keep the target event.",
            evidence_assessment="Both items describe the same event.",
            duplicate_of_overview_item_id=target.id,
        ),
    )
    repository.archive(predecessor.id)
    successor_draft = _daily_report_draft(
        db_session,
        source_operation_id=2402,
        supersedes_report_id=predecessor.id,
        overview_event_versions=((101, 2), (102, 1)),
    )

    successor = repository.create_cumulative_draft(successor_draft)

    successor_target, successor_duplicate = repository.overview_items(successor.id)
    copied_review = repository.overview_editorial_reviews(successor_duplicate.id)[0]
    assert copied_review.copied_from_editorial_review_id == source_review.id
    assert copied_review.duplicate_of_overview_item_id == successor_target.id
    assert (successor_target.event_id, successor_target.event_version_number) == (
        101,
        2,
    )


def test_create_cumulative_draft_copies_decision_review_by_event_version(
    db_session: Session,
) -> None:
    predecessor = _archived_report(
        db_session,
        revision=1,
        decision_event_versions=((101, 1), (102, 1)),
        reviewed_decision_event_version=(102, 1),
    )
    draft = _daily_report_draft(
        db_session,
        source_operation_id=2402,
        supersedes_report_id=predecessor.id,
        decision_event_versions=((102, 1),),
    )

    successor = DailyReportRepository(db_session).create_cumulative_draft(draft)
    item = DailyReportRepository(db_session).items(successor.id)[0]

    assert len(DailyReportRepository(db_session).editorial_reviews(item.id)) == 1


def test_create_cumulative_draft_does_not_reuse_other_operation_successor(
    db_session: Session,
) -> None:
    predecessor = _archived_report(db_session, revision=1)
    repository = DailyReportRepository(db_session)
    repository.create_cumulative_draft(
        _daily_report_draft(
            db_session,
            source_operation_id=2402,
            supersedes_report_id=predecessor.id,
        )
    )

    with pytest.raises(RuntimeError):
        repository.create_cumulative_draft(
            _daily_report_draft(
                db_session,
                source_operation_id=2403,
                supersedes_report_id=predecessor.id,
            )
        )


def test_create_cumulative_draft_reuses_exact_child_after_head_advances(
    db_session: Session,
) -> None:
    predecessor = _archived_report(db_session, revision=1)
    repository = DailyReportRepository(db_session)
    original_draft = _daily_report_draft(
        db_session,
        source_operation_id=2402,
        supersedes_report_id=predecessor.id,
    )
    first_successor = repository.create_cumulative_draft(original_draft)
    repository.archive(first_successor.id)
    later_successor = repository.create_cumulative_draft(
        _daily_report_draft(
            db_session,
            source_operation_id=2403,
            supersedes_report_id=first_successor.id,
        )
    )
    repository.archive(later_successor.id)

    retried = repository.create_cumulative_draft(original_draft)

    assert retried.id == first_successor.id
    assert retried.source_operation_id == 2402


def test_overview_decisions_are_keyed_by_exact_event_version(
    db_session: Session,
) -> None:
    predecessor = _archived_report_with_review(db_session, event_id=101, version=1)

    assert DailyReportRepository(db_session).overview_decisions(predecessor.id) == {
        (101, 1): EditorialDecision.KEEP
    }


def test_applied_event_survivors_maps_legacy_to_survivor(
    db_session: Session,
) -> None:
    _daily_report_draft(
        db_session,
        source_operation_id=2501,
        overview_event_versions=((101, 2), (102, 1)),
    )
    db_session.add(
        EventMergeCandidateRecord(
            id=1,
            left_event_id=101,
            left_version_number=2,
            right_event_id=102,
            right_version_number=1,
            candidate_type="legacy_identity",
            status="applied",
            algorithm_version="event-merge-v3",
            input_fingerprint="a" * 64,
            facts_snapshot={},
            reason_codes=["exact_cross_algorithm_membership"],
            zh_reason="Same event.",
            zh_next_action="Use the survivor.",
            generated_operation_id=2501,
            result_summary=MergeApplyResult(
                status="applied",
                candidate_id=1,
                survivor_event_id=101,
                survivor_version_number=2,
                legacy_event_id=102,
                legacy_version_number=1,
            ).model_dump(mode="json"),
        )
    )
    db_session.commit()

    assert DailyReportRepository(db_session).applied_event_survivors({101, 102}) == {
        102: 101,
        101: 101,
    }


def test_applied_event_survivors_accepts_published_result_versions(
    db_session: Session,
) -> None:
    _daily_report_draft(
        db_session,
        source_operation_id=2501,
        overview_event_versions=((101, 1), (102, 1)),
    )
    db_session.add(
        EventMergeCandidateRecord(
            id=1,
            left_event_id=101,
            left_version_number=1,
            right_event_id=102,
            right_version_number=1,
            candidate_type="legacy_identity",
            status="applied",
            algorithm_version="event-merge-v3",
            input_fingerprint="c" * 64,
            facts_snapshot={},
            reason_codes=["exact_cross_algorithm_membership"],
            zh_reason="Same event.",
            zh_next_action="Use the survivor.",
            generated_operation_id=2501,
            result_summary=MergeApplyResult(
                status="succeeded",
                candidate_id=1,
                survivor_event_id=101,
                survivor_version_number=2,
                legacy_event_id=102,
                legacy_version_number=2,
            ).model_dump(mode="json"),
        )
    )
    db_session.commit()

    assert DailyReportRepository(db_session).applied_event_survivors({101, 102}) == {
        102: 101,
        101: 101,
    }


def test_applied_event_survivors_ignores_incomplete_summary(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _daily_report_draft(
        db_session,
        source_operation_id=2501,
        overview_event_versions=((101, 1), (102, 1)),
    )
    db_session.add(
        EventMergeCandidateRecord(
            id=1,
            left_event_id=101,
            left_version_number=1,
            right_event_id=102,
            right_version_number=1,
            candidate_type="legacy_identity",
            status="applied",
            algorithm_version="event-merge-v3",
            input_fingerprint="b" * 64,
            facts_snapshot={},
            reason_codes=["exact_cross_algorithm_membership"],
            zh_reason="Same event.",
            zh_next_action="Use the survivor.",
            generated_operation_id=2501,
            result_summary={"status": "applied", "candidate_id": 1},
        )
    )
    db_session.commit()

    assert DailyReportRepository(db_session).applied_event_survivors({101, 102}) == {
        101: 101,
        102: 102,
    }
    assert any(
        record.message == "invalid applied event merge result ignored"
        and record.candidate_id == 1
        for record in caplog.records
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


def test_generate_keeps_all_eight_events_in_overview_but_only_two_in_decision(
    db_session: Session,
) -> None:
    operation_id = seed_complete_snapshot(
        db_session,
        confirmed=(),
        emerging=(201, 202),
        audit_only=(301, 302, 303, 304, 305, 306),
    )

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate_from_operation(
        operation_id, 24, now=NOW
    )
    repository = DailyReportRepository(db_session)

    assert len(repository.items(report.id)) == 2
    assert len(repository.overview_items(report.id)) == 8
    assert report.generation_summary["decision_count"] == 2
    assert report.generation_summary["overview_count"] == 8
    assert report.generation_summary["omitted_from_decision_count"] == 6


def test_second_same_day_report_accumulates_eleven_and_reranks_decisions(
    db_session: Session,
) -> None:
    first_operation = _seed_operation_with_ids(
        db_session, 2401, tuple(range(1, 9)), NOW
    )
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    first = service.generate_from_operation(first_operation, 24, now=NOW)
    repository.archive(first.id)
    second_operation = _seed_operation_with_ids(
        db_session, 2402, (8, 9, 10, 11), NOW + timedelta(hours=1)
    )

    second = service.generate_from_operation(
        second_operation, 24, now=NOW + timedelta(hours=1)
    )

    assert second.supersedes_report_id == first.id
    assert [row.event_id for row in repository.overview_items(second.id)] == list(
        range(1, 12)
    )
    assert [row.event_id for row in repository.items(second.id)] == [
        1,
        9,
        2,
        10,
        3,
        11,
        4,
        5,
        6,
        7,
        8,
    ]
    assert second.generation_summary["overview_count"] == 11


def test_second_same_day_report_with_only_old_events_does_not_shrink(
    db_session: Session,
) -> None:
    first_operation = _seed_operation_with_ids(
        db_session,
        2401,
        tuple(range(1, 12)),
        NOW,
        window_hours=72,
    )
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    first = service.generate_from_operation(first_operation, 72, now=NOW)
    repository.archive(first.id)
    second_operation = _seed_operation_with_ids(
        db_session, 2402, (10, 11), NOW + timedelta(hours=1)
    )

    second = service.generate_from_operation(
        second_operation, 24, now=NOW + timedelta(hours=1)
    )

    assert [row.event_id for row in repository.overview_items(second.id)] == list(
        range(1, 12)
    )


def test_second_same_day_generation_failure_leaves_archived_head_unchanged(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_operation = _seed_operation_with_ids(
        db_session, 2401, tuple(range(1, 9)), NOW
    )
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    first = service.generate_from_operation(first_operation, 24, now=NOW)
    repository.archive(first.id)
    second_operation = _seed_operation_with_ids(db_session, 2402, (9,), NOW)
    monkeypatch.setattr(
        service,
        "_overview_drafts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("materialization failed")
        ),
    )

    with pytest.raises(RuntimeError, match="materialization failed"):
        service.generate_from_operation(second_operation, 24, now=NOW)

    archived_head = repository.latest_archived_for_day(
        NOW.astimezone(ZoneInfo(REPORT_TIMEZONE)).date(),
        excluding_operation_id=second_operation,
    )
    assert archived_head is not None
    assert archived_head.id == first.id
    assert db_session.scalar(
        select(func.count(DailyReportRecord.id)).where(
            DailyReportRecord.supersedes_report_id == first.id
        )
    ) == 0


def test_second_same_day_malformed_snapshot_ranking_sorts_last_without_blocking(
    db_session: Session,
) -> None:
    first_operation = _seed_operation_with_ids(
        db_session, 2401, tuple(range(1, 9)), NOW
    )
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    first = service.generate_from_operation(first_operation, 24, now=NOW)
    malformed = repository.overview_items(first.id)[0]
    malformed.snapshot = {
        **malformed.snapshot,
        "rank_score": "not-a-number",
        "occurred_at": "not-a-datetime",
    }
    repository.archive(first.id)
    second_operation = _seed_operation_with_ids(
        db_session, 2402, (9,), NOW + timedelta(hours=1)
    )

    second = service.generate_from_operation(
        second_operation, 24, now=NOW + timedelta(hours=1)
    )

    decision_event_ids = [row.event_id for row in repository.items(second.id)]
    assert set(decision_event_ids) == set(range(1, 10))
    assert decision_event_ids[-1] == 1


def test_decision_ranking_puts_huge_integer_score_last_without_blocking() -> None:
    occurred_at = NOW.isoformat()
    huge = DailyReportOverviewItemDraft(
        event_id=1,
        event_version_number=1,
        position=1,
        snapshot={
            "status": "confirmed",
            "display_tier": "hotspot",
            "rank_score": 10**1000,
            "occurred_at": occurred_at,
        },
    )
    valid = DailyReportOverviewItemDraft(
        event_id=2,
        event_version_number=1,
        position=2,
        snapshot={
            "status": "confirmed",
            "display_tier": "hotspot",
            "rank_score": 10,
            "occurred_at": occurred_at,
        },
    )

    decisions = _decision_drafts((huge, valid))

    assert [item.event_id for item in decisions] == [2, 1]


def test_revision_unions_archived_overview_with_full_operation_snapshot(
    db_session: Session,
) -> None:
    operation_id = _seed_operation_with_ids(
        db_session, 2401, tuple(range(1, 9)), NOW
    )
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = service.generate_from_operation(operation_id, 24, now=NOW)
    db_session.execute(
        delete(DailyReportOverviewItemRecord).where(
            DailyReportOverviewItemRecord.daily_report_id == original.id,
            DailyReportOverviewItemRecord.event_id > 4,
        )
    )
    db_session.commit()
    repository.archive(original.id)

    revision = service.revise(original.id)

    assert [row.event_id for row in repository.overview_items(revision.id)] == list(
        range(1, 9)
    )


def test_generate_persists_every_displayable_operation_event_for_overview(
    db_session: Session,
) -> None:
    seed_complete_snapshot(db_session)

    report = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    rows = DailyReportRepository(db_session).overview_items(report.id)

    assert [row.event_id for row in rows] == [101, 102, 201, 202, 301, 302]
    assert [row.position for row in rows] == list(range(1, 7))
    assert all(set(row.snapshot) == EXPECTED_OVERVIEW_SNAPSHOT_KEYS for row in rows)
    assert {
        row.event_id for row in rows if row.decision_item_id is not None
    } == {101, 102, 201, 202, 302}
    assert report.generation_summary["overview_count"] == 6


def test_generate_keeps_invalid_overview_event_as_degraded_item(
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

    rows = DailyReportRepository(db_session).overview_items(report.id)

    assert [row.event_id for row in rows] == [101, 102, 201, 202, 301, 302]
    assert rows[-1].snapshot["display_degradation_reason"] == "event_detail_unavailable"
    assert report.generation_summary["skipped_invalid_overview_event"] == 1
    assert len(DailyReportRepository(db_session).items(report.id)) == 4


def test_revise_complete_snapshot_keeps_decisions_and_rebuilds_full_overview(
    db_session: Session,
) -> None:
    seed_complete_snapshot(db_session)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = service.generate(24, now=NOW)
    frozen_decisions = [row.snapshot for row in repository.items(original.id)]
    db_session.execute(
        delete(DailyReportOverviewItemRecord).where(
            DailyReportOverviewItemRecord.daily_report_id == original.id
        )
    )
    db_session.commit()
    repository.archive(original.id)

    revision = service.revise(original.id)

    assert repository.overview_items(original.id) == ()
    assert [row.snapshot for row in repository.items(revision.id)] == frozen_decisions
    copied = repository.overview_items(revision.id)
    assert [row.event_id for row in copied] == [101, 102, 201, 202, 301, 302]
    assert [row.snapshot["zh_title"] for row in copied] == [
        "事件 101",
        "事件 102",
        "事件 201",
        "事件 202",
        "事件 301",
        "事件 302",
    ]
    assert revision.generation_summary["revision_overview_source"] == "event_snapshot"


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
    seed_complete_snapshot(db_session, confirmed=(), emerging=(), audit_only=())

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


def test_revise_legacy_manifest_copies_archived_overview_and_reviews(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation_id = seed_complete_snapshot(db_session)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = service.generate(24, now=NOW)
    overview = repository.overview_items(original.id)
    reviewed = overview[1]
    source_review = repository.save_overview_editorial_review(
        original.id,
        reviewed.id,
        DailyReportOverviewEditorialReviewDraft.create(
            decision="duplicate",
            zh_title="重复事件",
            zh_summary="与首条事件内容重复。",
            review_recommendation="合并到首条事件。",
            evidence_assessment="使用相同的第一方证据。",
            duplicate_of_overview_item_id=overview[0].id,
        ),
    )
    frozen = [
        (
            row.event_id,
            row.event_version_number,
            row.position,
            dict(row.snapshot),
            row.decision_item_id is not None,
        )
        for row in overview
    ]
    repository.archive(original.id)
    operation = db_session.get(OperationRunRecord, operation_id)
    assert operation is not None
    operation.result_summary = {
        key: value
        for key, value in operation.result_summary.items()
        if key != "event_version_snapshots"
    }
    db_session.commit()
    monkeypatch.setattr(
        service,
        "_overview_drafts",
        lambda *_args, **_kwargs: pytest.fail("overview rebuild"),
    )

    revision = service.revise(original.id)

    copied = repository.overview_items(revision.id)
    assert [
        (
            row.event_id,
            row.event_version_number,
            row.position,
            dict(row.snapshot),
            row.decision_item_id is not None,
        )
        for row in copied
    ] == frozen
    copied_review = repository.overview_editorial_reviews(copied[1].id)[0]
    assert copied_review.copied_from_editorial_review_id == source_review.id
    assert copied_review.duplicate_of_overview_item_id == copied[0].id
    assert revision.generation_summary["revision_overview_source"] == (
        "archived_report_snapshot"
    )
    assert revision.generation_summary["revision_overview_diagnostic_zh"] == (
        "历史操作快照缺失，本修订版沿用归档版固定条目；"
        "系统没有重新抓取或混入当前事件。"
    )


def test_revise_present_but_invalid_manifest_is_rejected_without_draft(
    db_session: Session,
) -> None:
    operation_id = seed_complete_snapshot(db_session)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = service.generate(24, now=NOW)
    repository.archive(original.id)
    operation = db_session.get(OperationRunRecord, operation_id)
    assert operation is not None
    operation.result_summary = {"event_version_snapshots": "invalid"}
    db_session.commit()

    with pytest.raises(ValueError, match="complete_event_snapshot_required"):
        service.revise(original.id)

    assert db_session.scalar(
        select(func.count(DailyReportRecord.id)).where(
            DailyReportRecord.status == "draft"
        )
    ) == 0


@pytest.mark.parametrize("corruption", ["missing_operation", "non_dict_summary"])
def test_revise_rejects_missing_operation_or_non_dict_summary(
    db_session: Session,
    corruption: str,
) -> None:
    operation_id = seed_complete_snapshot(db_session)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = service.generate(24, now=NOW)
    repository.archive(original.id)
    operation = db_session.get(OperationRunRecord, operation_id)
    assert operation is not None
    if corruption == "missing_operation":
        db_session.execute(
            delete(OperationRunRecord).where(OperationRunRecord.id == operation_id)
        )
    else:
        operation.result_summary = []
    db_session.commit()

    with pytest.raises(ValueError, match="complete_event_snapshot_required"):
        service.revise(original.id)

    assert db_session.scalar(
        select(func.count(DailyReportRecord.id)).where(
            DailyReportRecord.status == "draft"
        )
    ) == 0


def test_revise_returns_existing_active_draft_without_snapshot_lookup(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_complete_snapshot(db_session)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = DailyReportService(db_session, utcnow=lambda: NOW).generate(24, now=NOW)
    repository.archive(original.id)
    active = repository.revise(original.id)
    active.generation_summary = {"sentinel": "do-not-overwrite"}
    db_session.commit()
    monkeypatch.setattr(
        "newsradar.daily_reports.service.event_snapshot_by_id",
        lambda *_args, **_kwargs: pytest.fail("snapshot lookup"),
    )

    reused = DailyReportService(db_session, utcnow=lambda: NOW).revise(original.id)

    assert reused.id == active.id
    assert reused.generation_summary == {"sentinel": "do-not-overwrite"}


def test_revise_rejects_stale_materialization_when_revision_chain_advances(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_complete_snapshot(db_session)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = service.generate(24, now=NOW)
    repository.archive(original.id)
    original_revise = service._reports.revise
    advanced_head_id: int | None = None

    def advance_then_revise(*args, **kwargs):
        nonlocal advanced_head_id
        advanced = repository.revise(original.id)
        repository.archive(advanced.id)
        advanced_head_id = advanced.id
        return original_revise(*args, **kwargs)

    monkeypatch.setattr(service._reports, "revise", advance_then_revise)

    with pytest.raises(RuntimeError, match="daily_report_revision_chain_changed"):
        service.revise(original.id)

    assert advanced_head_id is not None
    assert db_session.scalar(
        select(func.count(DailyReportRecord.id)).where(
            DailyReportRecord.supersedes_report_id == advanced_head_id
        )
    ) == 0


def test_revise_reuses_active_draft_won_during_materialization(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_complete_snapshot(db_session)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    original = service.generate(24, now=NOW)
    repository.archive(original.id)
    original_revise = service._reports.revise
    winning_draft_id: int | None = None

    def win_then_revise(*args, **kwargs):
        nonlocal winning_draft_id
        winner = repository.revise(original.id)
        winning_draft_id = winner.id
        return original_revise(*args, **kwargs)

    monkeypatch.setattr(service._reports, "revise", win_then_revise)

    revision = service.revise(original.id)

    assert winning_draft_id is not None
    assert revision.id == winning_draft_id
    assert db_session.scalars(
        select(DailyReportRecord.id).where(
            DailyReportRecord.supersedes_report_id == original.id,
            DailyReportRecord.deleted_at.is_(None),
        )
    ).all() == [winning_draft_id]


def test_revise_reads_decisions_from_latest_archived_head(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_complete_snapshot(db_session)
    service = DailyReportService(db_session, utcnow=lambda: NOW)
    repository = DailyReportRepository(db_session, utcnow=lambda: NOW)
    parent = service.generate(24, now=NOW)
    repository.archive(parent.id)
    child = repository.revise(parent.id)
    repository.archive(child.id)
    original_items = service._reports.items
    item_report_ids: list[int] = []

    def tracking_items(report_id: int):
        item_report_ids.append(report_id)
        return original_items(report_id)

    monkeypatch.setattr(service._reports, "items", tracking_items)

    revision = service.revise(parent.id)

    assert revision.supersedes_report_id == child.id
    assert item_report_ids[0] == child.id
