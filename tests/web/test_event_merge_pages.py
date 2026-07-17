from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from newsradar.db.models import (
    EventItemRecord,
    EventMergeCandidateRecord,
    EventRecord,
    EventVersionRecord,
    OperationRunRecord,
    RawItemRecord,
)
from newsradar.web.app import create_app

NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)


def _seed_operation(session, operation_id: int = 100) -> None:
    session.add(
        OperationRunRecord(
            id=operation_id,
            operation_type="event_merge_scan",
            trigger="test",
            status="succeeded",
            requested_scope={},
            result_summary={},
        )
    )


def _seed_event(
    session,
    event_id: int,
    member_ids: tuple[int, ...],
    *,
    version: int = 1,
    title: str | None = None,
    source_ids: tuple[str, ...] | None = None,
) -> None:
    source_ids = source_ids or tuple("github-openai-python" for _ in member_ids)
    session.add(
        EventRecord(
            id=event_id,
            canonical_key=f"event-{event_id}",
            visibility="current",
            status="confirmed",
            occurred_at=NOW,
            current_version_number=version,
        )
    )
    for version_number in range(1, version + 1):
        session.add(
            EventVersionRecord(
                event_id=event_id,
                version_number=version_number,
                zh_title=(title or f"事件 {event_id}") + f" v{version_number}",
                zh_summary=f"冻结摘要 {event_id}-{version_number}",
                payload={"status": "confirmed", "occurred_at": NOW.isoformat()},
            )
        )
    for raw_item_id, source_id in zip(member_ids, source_ids, strict=True):
        if session.get(RawItemRecord, raw_item_id) is None:
            session.add(
                RawItemRecord(
                    id=raw_item_id,
                    source_id=source_id,
                    external_id=f"raw-{raw_item_id}",
                    canonical_url=(
                        f"https://user:password@media.example/story/{raw_item_id}"
                        "?token=SECRET-MARKER#private"
                    ),
                    original_url=(
                        f"https://media.example/story/{raw_item_id}"
                        "?api_key=SECRET-MARKER#private"
                    ),
                    payload={},
                    title=f"原始报道 {raw_item_id}",
                    publisher_name=f"媒体 {source_id}",
                    published_at=NOW + timedelta(minutes=raw_item_id),
                    origin_resolution_status="resolved",
                )
            )
        session.add(
            EventItemRecord(
                event_id=event_id,
                raw_item_id=raw_item_id,
                added_version_number=1,
            )
        )


def _facts(
    event_id: int,
    version: int,
    raw_item_ids: tuple[int, ...],
    source_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "version_number": version,
        "visibility": "current",
        "canonical_key": f"event-{event_id}",
        "algorithm_versions": ["cluster-v3"],
        "raw_item_ids": list(raw_item_ids),
        "source_ids": list(source_ids),
        "publishers": [f"媒体 {source_id}" for source_id in source_ids],
        "published_at": [NOW.isoformat()],
        "safe_url_identities": [
            "media.example/story?token=SECRET-MARKER#private",
            "user:password@media.example/private",
        ],
        "strong_identities": ["media.example/story"],
        "object_entities": ["model:orion"],
        "actions": ["launch"],
        "evidence_roots": [
            "https://user:password@media.example/evidence?token=SECRET-MARKER#private"
        ],
        "key_numbers": ["2 billion"],
    }


def _seed_candidate(
    session,
    candidate_id: int,
    candidate_type: str,
    *,
    status: str = "pending",
    left_id: int = 1,
    right_id: int = 2,
    left_version: int = 1,
    right_version: int = 1,
    reason_codes: tuple[str, ...] | None = None,
    algorithm_version: str = "event-merge-v2",
) -> EventMergeCandidateRecord:
    reason_codes = reason_codes or {
        "legacy_identity": ("exact_cross_algorithm_membership",),
        "deterministic_merge": ("same_strong_identity",),
        "manual_review": ("same_object_action_without_strong_identity",),
    }[candidate_type]
    record = EventMergeCandidateRecord(
        id=candidate_id,
        left_event_id=left_id,
        left_version_number=left_version,
        right_event_id=right_id,
        right_version_number=right_version,
        candidate_type=candidate_type,
        status=status,
        algorithm_version=algorithm_version,
        input_fingerprint=(f"{candidate_id:x}" * 64)[:64],
        facts_snapshot={
            "left": _facts(left_id, left_version, (11,), ("github-openai-python",)),
            "right": _facts(right_id, right_version, (22,), ("search-ai",)),
        },
        reason_codes=list(reason_codes),
        zh_reason="不应直接信任：token=SECRET-MARKER",
        zh_next_action="不应直接信任数据库自由文本",
        generated_operation_id=100,
        result_summary={"error": "postgres password=SECRET-MARKER"},
    )
    session.add(record)
    return record


def _seed_candidate_catalog(session) -> None:
    _seed_operation(session)
    _seed_event(session, 1, (11,), version=2, title="左侧冻结事件")
    _seed_event(session, 2, (22,), version=2, title="右侧冻结事件")
    _seed_event(
        session,
        3,
        (33, 34),
        source_ids=("github-openai-python", "search-ai"),
    )
    _seed_event(session, 4, (11, 44))
    _seed_candidate(
        session,
        1,
        "legacy_identity",
        left_version=1,
        right_version=1,
    )
    _seed_candidate(session, 2, "deterministic_merge", left_id=1, right_id=3)
    _seed_candidate(session, 3, "manual_review", left_id=2, right_id=3)
    session.commit()


def _token(page: str) -> str:
    return page.split('name="action_token" value="', 1)[1].split('"', 1)[0]


def _safe_headers() -> dict[str, str]:
    return {"Origin": "http://127.0.0.1", "Host": "127.0.0.1"}


def test_summary_separates_current_membership_and_candidate_states(db_session) -> None:
    _seed_candidate_catalog(db_session)

    from newsradar.web.event_merge_queries import EventMergeQueryService

    summary = EventMergeQueryService(db_session).summary()

    assert summary.current_event_count == 4
    assert summary.single_member_event_count == 2
    assert summary.cross_source_event_count == 1
    assert summary.raw_items_in_multiple_current_events == 1
    assert summary.legacy_identity_pending_count == 1
    assert summary.deterministic_pending_count == 1
    assert summary.manual_pending_count == 1


def test_candidate_list_is_filtered_and_capped_at_200(db_session) -> None:
    _seed_candidate_catalog(db_session)
    for event_id in range(10, 211):
        _seed_event(db_session, event_id, ())
        _seed_candidate(
            db_session,
            event_id,
            "deterministic_merge",
            left_id=1,
            right_id=event_id,
        )
    db_session.commit()

    from newsradar.web.event_merge_queries import EventMergeQueryService

    service = EventMergeQueryService(db_session)
    rows = service.list_candidates("pending", "manual_review", limit=999)

    assert [row.candidate_id for row in rows] == [3]
    statements: list[str] = []
    bind = db_session.get_bind()

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    sqlalchemy_event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        bounded_rows = service.list_candidates("pending", None, limit=999)
    finally:
        sqlalchemy_event.remove(bind, "before_cursor_execute", capture_statement)

    assert len(bounded_rows) == 200
    assert len(statements) <= 2


def test_summary_includes_terminal_candidate_states(db_session) -> None:
    _seed_candidate_catalog(db_session)
    _seed_candidate(
        db_session, 4, "deterministic_merge", status="applied", left_id=1, right_id=4
    )
    _seed_candidate(
        db_session, 5, "manual_review", status="dismissed", left_id=2, right_id=4
    )
    _seed_candidate(
        db_session, 6, "manual_review", status="expired", left_id=3, right_id=4
    )
    _seed_event(db_session, 5, ())
    legacy = db_session.get(EventRecord, 5)
    assert legacy is not None
    legacy.visibility = "legacy"
    _seed_candidate(
        db_session, 7, "manual_review", status="failed", left_id=1, right_id=5
    )
    db_session.commit()

    from newsradar.web.event_merge_queries import EventMergeQueryService

    summary = EventMergeQueryService(db_session).summary()

    assert summary.applied_count == 1
    assert summary.dismissed_count == 1
    assert summary.expired_count == 1
    assert summary.failed_count == 1


def test_summary_uses_fixed_aggregate_queries_instead_of_loading_catalog_rows(
    db_session,
) -> None:
    _seed_candidate_catalog(db_session)
    db_session.add_all(
        EventRecord(
            id=event_id,
            canonical_key=f"large-summary-{event_id}",
            visibility="current",
            status="emerging",
            current_version_number=0,
        )
        for event_id in range(100, 1_100)
    )
    db_session.commit()

    from newsradar.web.event_merge_queries import EventMergeQueryService

    statements: list[str] = []
    bind = db_session.get_bind()

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.casefold())

    sqlalchemy_event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        summary = EventMergeQueryService(db_session).summary()
    finally:
        sqlalchemy_event.remove(bind, "before_cursor_execute", capture_statement)

    assert summary.current_event_count == 1_004
    assert summary.single_member_event_count == 2
    assert len(statements) <= 3
    assert all("count(" in statement or "sum(" in statement for statement in statements)
    assert any("group by" in statement for statement in statements)


def test_candidate_detail_uses_snapshot_versions_and_redacts_sensitive_urls(
    db_session,
) -> None:
    _seed_candidate_catalog(db_session)

    from newsradar.web.event_merge_queries import EventMergeQueryService

    detail = EventMergeQueryService(db_session).get_candidate(1)

    assert detail is not None
    assert detail.left.version_number == 1
    assert detail.left.title == "左侧冻结事件 v1"
    assert detail.left.visibility == "current"
    assert detail.zh_reason == "旧算法与当前算法事件包含完全相同的原始条目。"
    assert detail.reason_code == "exact_cross_algorithm_membership"
    assert detail.shared_strong_identities == ("media.example/story",)
    assert detail.left.members[0].raw_item_id == 11
    serialized = repr(detail)
    assert "SECRET-MARKER" not in serialized
    assert "token=" not in serialized.casefold()
    assert "password@" not in serialized.casefold()
    assert "#private" not in serialized.casefold()


def test_candidate_detail_never_rehydrates_mutable_raw_item_fields(
    db_session, monkeypatch
) -> None:
    _seed_candidate_catalog(db_session)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)
    monkeypatch.setattr("newsradar.web.app.token_urlsafe", lambda _length: "fixed-token")

    from newsradar.web.event_merge_queries import EventMergeQueryService

    before_model = EventMergeQueryService(db_session).get_candidate(1)
    with TestClient(create_app()) as client:
        before_html = client.get("/event-merge-candidates/1").text

    raw = db_session.get(RawItemRecord, 11)
    assert raw is not None
    raw.source_id = "x-openai"
    raw.title = "MUTATED-TITLE"
    raw.publisher_name = "MUTATED-PUBLISHER"
    raw.published_at = NOW + timedelta(days=30)
    raw.original_url = "https://mutated.example/password/NEW-SECRET"
    raw.canonical_url = "https://mutated.example/token/NEW-SECRET"
    raw.origin_resolution_status = "unresolved"
    db_session.commit()

    after_model = EventMergeQueryService(db_session).get_candidate(1)
    with TestClient(create_app()) as client:
        after_html = client.get("/event-merge-candidates/1").text

    assert before_model == after_model
    assert repr(before_model) == repr(after_model)
    assert before_html == after_html
    assert "MUTATED" not in after_html
    assert "NEW-SECRET" not in after_html
    assert "当前 RawItem 页面，非候选冻结证据" in after_html


def test_shared_strong_identity_is_computed_before_display_truncation(
    db_session,
) -> None:
    _seed_candidate_catalog(db_session)
    candidate = db_session.get(EventMergeCandidateRecord, 2)
    assert candidate is not None
    left = _facts(1, 1, (11,), ("github-openai-python",))
    right = _facts(3, 1, (33,), ("search-ai",))
    left["strong_identities"] = [f"left.example/story-{index}" for index in range(100)] + [
        "shared.example/story"
    ]
    right["strong_identities"] = [
        f"right.example/story-{index}" for index in range(100)
    ] + ["shared.example/story"]
    candidate.facts_snapshot = {"left": left, "right": right}
    db_session.commit()

    from newsradar.web.event_merge_queries import EventMergeQueryService

    detail = EventMergeQueryService(db_session).get_candidate(2)

    assert detail is not None
    assert detail.shared_strong_identities == ("shared.example/story",)
    assert detail.shared_strong_identity_count == 1
    assert detail.displayed_shared_strong_identity_count == 1
    assert not detail.shared_strong_identities_truncated
    assert detail.left.strong_identity_count == 101
    assert detail.left.displayed_strong_identity_count == 100
    assert detail.left.strong_identities_truncated


def test_raw_item_member_display_reports_total_and_truncation(
    db_session, monkeypatch
) -> None:
    _seed_candidate_catalog(db_session)
    candidate = db_session.get(EventMergeCandidateRecord, 1)
    assert candidate is not None
    snapshot = dict(candidate.facts_snapshot)
    left = dict(snapshot["left"])
    left["raw_item_ids"] = list(range(1_000, 1_501))
    candidate.facts_snapshot = {**snapshot, "left": left}
    db_session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    from newsradar.web.event_merge_queries import EventMergeQueryService

    detail = EventMergeQueryService(db_session).get_candidate(1)
    with TestClient(create_app()) as client:
        response = client.get("/event-merge-candidates/1")

    assert detail is not None
    assert detail.left.raw_item_count == 501
    assert detail.left.displayed_raw_item_count == 500
    assert detail.left.raw_items_truncated
    assert len(detail.left.members) == 500
    assert response.status_code == 200
    assert "冻结成员共 501 条" in response.text
    assert "仅显示前 500 条" in response.text


@pytest.mark.parametrize("secret_key", ["token", "api_key", "credential", "password"])
def test_candidate_projection_rejects_secret_shaped_url_paths(
    db_session, monkeypatch, secret_key
) -> None:
    _seed_candidate_catalog(db_session)
    candidate = db_session.get(EventMergeCandidateRecord, 2)
    assert candidate is not None
    snapshot = dict(candidate.facts_snapshot)
    secret_url = f"https://media.example/{secret_key}/SECRET-MARKER/story"
    for side_name in ("left", "right"):
        side = dict(snapshot[side_name])
        side["safe_url_identities"] = [secret_url]
        side["strong_identities"] = [secret_url]
        side["evidence_roots"] = [secret_url]
        snapshot[side_name] = side
    candidate.facts_snapshot = snapshot
    db_session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    from newsradar.web.event_merge_queries import EventMergeQueryService

    detail = EventMergeQueryService(db_session).get_candidate(2)
    with TestClient(create_app()) as client:
        response = client.get("/event-merge-candidates/2")

    assert detail is not None
    assert "SECRET-MARKER" not in repr(detail)
    assert secret_key not in repr(detail).casefold()
    assert "SECRET-MARKER" not in response.text


@pytest.mark.parametrize(
    "secret_path",
    [
        "token:SECRET-MARKER/story",
        "API_KEY=SECRET-MARKER/story",
        "%2574oken/SECRET-MARKER/story",
        "%252574oken/SECRET-MARKER/story",
    ],
)
def test_candidate_projection_rejects_assigned_or_recursively_encoded_secret_paths(
    db_session, monkeypatch, secret_path
) -> None:
    _seed_candidate_catalog(db_session)
    candidate = db_session.get(EventMergeCandidateRecord, 2)
    assert candidate is not None
    snapshot = dict(candidate.facts_snapshot)
    secret_url = f"https://media.example/{secret_path}"
    for side_name in ("left", "right"):
        side = dict(snapshot[side_name])
        side["safe_url_identities"] = [secret_url]
        side["strong_identities"] = [secret_url]
        side["evidence_roots"] = [secret_url]
        snapshot[side_name] = side
    candidate.facts_snapshot = snapshot
    db_session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    from newsradar.web.event_merge_queries import EventMergeQueryService

    detail = EventMergeQueryService(db_session).get_candidate(2)
    with TestClient(create_app()) as client:
        response = client.get("/event-merge-candidates/2")

    assert detail is not None
    assert "SECRET-MARKER" not in repr(detail)
    assert "SECRET-MARKER" not in response.text


def test_candidate_projection_keeps_non_sensitive_tokenization_path(
    db_session, monkeypatch
) -> None:
    _seed_candidate_catalog(db_session)
    candidate = db_session.get(EventMergeCandidateRecord, 2)
    assert candidate is not None
    snapshot = dict(candidate.facts_snapshot)
    public_url = "https://media.example/news/tokenization-story"
    for side_name in ("left", "right"):
        side = dict(snapshot[side_name])
        side["safe_url_identities"] = [public_url]
        snapshot[side_name] = side
    candidate.facts_snapshot = snapshot
    db_session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    from newsradar.web.event_merge_queries import EventMergeQueryService

    detail = EventMergeQueryService(db_session).get_candidate(2)
    with TestClient(create_app()) as client:
        response = client.get("/event-merge-candidates/2")

    assert detail is not None
    assert detail.left.safe_urls == (public_url,)
    assert "tokenization-story" in response.text


def test_unknown_reason_uses_bounded_generic_chinese_copy(db_session) -> None:
    _seed_candidate_catalog(db_session)
    candidate = db_session.get(EventMergeCandidateRecord, 3)
    assert candidate is not None
    candidate.reason_codes = ["unknown:" + "SECRET-MARKER" * 100]
    db_session.commit()

    from newsradar.web.event_merge_queries import EventMergeQueryService

    detail = EventMergeQueryService(db_session).get_candidate(3)

    assert detail is not None
    assert detail.zh_reason == "候选原因暂未提供可公开的中文说明。"
    assert "SECRET-MARKER" not in repr(detail)


def test_candidate_pages_label_identity_retirement_without_false_content_claim(
    db_session, monkeypatch
) -> None:
    _seed_candidate_catalog(db_session)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        listing = client.get("/event-merge-candidates")
        detail = client.get("/event-merge-candidates/1")

    assert listing.status_code == 200
    assert "事件合并候选" in listing.text
    assert "当前事件" in listing.text
    assert ">4</strong>" in listing.text
    assert detail.status_code == 200
    assert "旧算法身份重复" in detail.text
    assert "跨来源内容已确认相同" not in detail.text
    assert "SECRET-MARKER" not in detail.text


def test_partial_membership_reason_uses_centralized_chinese_copy(db_session) -> None:
    _seed_candidate_catalog(db_session)
    candidate = db_session.get(EventMergeCandidateRecord, 3)
    assert candidate is not None
    candidate.reason_codes = ["partial_membership_overlap"]
    db_session.commit()

    from newsradar.web.event_merge_queries import EventMergeQueryService

    detail = EventMergeQueryService(db_session).get_candidate(3)

    assert detail is not None
    assert detail.algorithm_version == "event-merge-v2"
    assert detail.reason_code == "partial_membership_overlap"
    assert detail.zh_reason == "两个事件的原始条目部分重叠，但成员集合并不完全相同。"
    assert detail.zh_next_action == "人工核对未重叠条目后，确认合并或保持分开。"


def test_historical_v1_candidate_remains_readable(db_session) -> None:
    _seed_candidate_catalog(db_session)
    candidate = db_session.get(EventMergeCandidateRecord, 1)
    assert candidate is not None
    candidate.algorithm_version = "event-merge-v1"
    db_session.commit()

    from newsradar.web.event_merge_queries import EventMergeQueryService

    detail = EventMergeQueryService(db_session).get_candidate(1)

    assert detail is not None
    assert detail.algorithm_version == "event-merge-v1"


def test_candidate_detail_missing_is_404(db_session, monkeypatch) -> None:
    _seed_candidate_catalog(db_session)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        response = client.get("/event-merge-candidates/999")

    assert response.status_code == 404
    assert "未找到该事件合并候选" in response.text


def test_candidate_detail_only_renders_actions_valid_for_type_and_state(
    db_session, monkeypatch
) -> None:
    _seed_candidate_catalog(db_session)
    expired = db_session.get(EventMergeCandidateRecord, 1)
    assert expired is not None
    expired.status = "expired"
    db_session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        automatic = client.get("/event-merge-candidates/2")
        manual = client.get("/event-merge-candidates/3")
        inactive = client.get("/event-merge-candidates/1")

    assert "/event-merge-candidates/2/apply" in automatic.text
    assert "/event-merge-candidates/2/confirm" not in automatic.text
    assert "/event-merge-candidates/3/confirm" in manual.text
    assert "/event-merge-candidates/3/apply" not in manual.text
    assert "/event-merge-candidates/1/apply" not in inactive.text
    assert "/event-merge-candidates/1/recheck" not in inactive.text


def test_malformed_candidate_snapshot_is_isolated_from_list_page(
    db_session, monkeypatch
) -> None:
    _seed_candidate_catalog(db_session)
    malformed = db_session.get(EventMergeCandidateRecord, 2)
    assert malformed is not None
    malformed.facts_snapshot = {
        "left": "token=SECRET-MARKER",
        "right": ["password=SECRET-MARKER"],
    }
    malformed.reason_codes = [{"raw": "SECRET-MARKER"}]
    db_session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        listing = client.get("/event-merge-candidates")
        healthy = client.get("/event-merge-candidates/1")

    assert listing.status_code == 200
    assert healthy.status_code == 200
    assert "SECRET-MARKER" not in listing.text


@pytest.mark.parametrize(
    ("candidate_id", "decision", "operation_type"),
    [
        (1, "apply", "event_merge"),
        (2, "dismiss", "event_merge"),
        (3, "confirm", "event_merge"),
        (3, "recheck", "event_merge"),
    ],
)
def test_candidate_decision_only_enqueues_operation(
    db_session, monkeypatch, candidate_id, decision, operation_type
) -> None:
    _seed_candidate_catalog(db_session)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        page = client.get(f"/event-merge-candidates/{candidate_id}")
        before = db_session.get(EventRecord, 1).current_version_number
        response = client.post(
            f"/event-merge-candidates/{candidate_id}/{decision}",
            data={"action_token": _token(page.text)},
            headers=_safe_headers(),
            follow_redirects=False,
        )

    assert response.status_code == 303
    operation = db_session.scalars(
        select(OperationRunRecord).where(OperationRunRecord.id != 100)
    ).one()
    assert operation.operation_type == operation_type
    assert operation.requested_scope["candidate_id"] == candidate_id
    assert operation.requested_scope["decision"] == decision
    assert operation.trigger == "web"
    assert db_session.get(EventRecord, 1).current_version_number == before


def test_scan_only_enqueues_scan_operation(db_session, monkeypatch) -> None:
    _seed_candidate_catalog(db_session)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        page = client.get("/event-merge-candidates")
        response = client.post(
            "/event-merge-candidates/scan",
            data={"action_token": _token(page.text)},
            headers=_safe_headers(),
            follow_redirects=False,
        )

    assert response.status_code == 303
    operation = db_session.scalars(
        select(OperationRunRecord).where(OperationRunRecord.id != 100)
    ).one()
    assert operation.operation_type == "event_merge_scan"
    assert operation.trigger == "web"


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/event-merge-candidates/999/apply", 404),
        ("/event-merge-candidates/1/confirm", 422),
        ("/event-merge-candidates/3/apply", 422),
        ("/event-merge-candidates/1/explode", 422),
    ],
)
def test_candidate_decision_rejects_missing_or_invalid_actions(
    db_session, monkeypatch, path, expected_status
) -> None:
    _seed_candidate_catalog(db_session)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        page = client.get("/event-merge-candidates")
        response = client.post(
            path,
            data={"action_token": _token(page.text)},
            headers=_safe_headers(),
        )

    assert response.status_code == expected_status
    assert db_session.query(OperationRunRecord).count() == 1


@pytest.mark.parametrize("status", ["expired", "applied"])
def test_candidate_decision_rejects_non_pending_candidate(
    db_session, monkeypatch, status
) -> None:
    _seed_candidate_catalog(db_session)
    candidate = db_session.get(EventMergeCandidateRecord, 1)
    assert candidate is not None
    candidate.status = status
    db_session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        page = client.get("/event-merge-candidates")
        response = client.post(
            "/event-merge-candidates/1/apply",
            data={"action_token": _token(page.text)},
            headers=_safe_headers(),
        )

    assert response.status_code == 409
    assert db_session.query(OperationRunRecord).count() == 1


def test_candidate_action_rejects_unsafe_origin_and_reused_token(
    db_session, monkeypatch
) -> None:
    _seed_candidate_catalog(db_session)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        token = _token(client.get("/event-merge-candidates/1").text)
        unsafe = client.post(
            "/event-merge-candidates/1/apply",
            data={"action_token": token},
            headers={"Origin": "https://attacker.example", "Host": "127.0.0.1"},
        )
        first = client.post(
            "/event-merge-candidates/1/apply",
            data={"action_token": token},
            headers=_safe_headers(),
            follow_redirects=False,
        )
        reused = client.post(
            "/event-merge-candidates/1/apply",
            data={"action_token": token},
            headers=_safe_headers(),
        )

    assert unsafe.status_code == 400
    assert first.status_code == 303
    assert reused.status_code == 400


def test_candidate_page_handles_database_unavailable_without_raw_error(
    monkeypatch,
) -> None:
    class BrokenService:
        def __init__(self, _session) -> None:
            raise OperationalError("SELECT secret", {}, RuntimeError("SECRET-MARKER"))

    monkeypatch.setattr("newsradar.web.app.EventMergeQueryService", BrokenService)

    with TestClient(create_app()) as client:
        response = client.get("/event-merge-candidates")

    assert response.status_code == 503
    assert "SECRET-MARKER" not in response.text


def test_candidate_page_handles_unknown_exception_without_echo(
    monkeypatch, caplog
) -> None:
    class BrokenService:
        def __init__(self, _session) -> None:
            raise RuntimeError("token=SECRET-MARKER")

    monkeypatch.setattr("newsradar.web.app.EventMergeQueryService", BrokenService)

    with TestClient(create_app()) as client:
        response = client.get("/event-merge-candidates")

    assert response.status_code == 503
    assert "SECRET-MARKER" not in response.text
    assert "SECRET-MARKER" not in caplog.text


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (
            OperationalError("INSERT secret", {}, RuntimeError("token=SECRET-MARKER")),
            503,
        ),
        (RuntimeError("password=SECRET-MARKER"), 503),
        (ValueError("token=SECRET-MARKER"), 422),
    ],
)
def test_candidate_post_failure_is_redacted(
    db_session, monkeypatch, caplog, error, expected_status
) -> None:
    caplog.set_level(logging.INFO, logger="newsradar.web.app")
    _seed_candidate_catalog(db_session)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    def fail_enqueue(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(
        "newsradar.web.app.OperationCommandService.enqueue_event_merge_decision",
        fail_enqueue,
    )

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        page = client.get("/event-merge-candidates/1")
        response = client.post(
            "/event-merge-candidates/1/apply",
            data={"action_token": _token(page.text)},
            headers=_safe_headers(),
        )

    assert response.status_code == expected_status
    assert "SECRET-MARKER" not in response.text
    assert "SECRET-MARKER" not in caplog.text
    assert all("SECRET-MARKER" not in repr(record.__dict__) for record in caplog.records)


def test_candidate_scan_value_error_log_is_redacted(
    db_session, monkeypatch, caplog
) -> None:
    caplog.set_level(logging.INFO, logger="newsradar.web.app")
    _seed_candidate_catalog(db_session)
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    def fail_enqueue(*_args, **_kwargs):
        raise ValueError("password=SECRET-MARKER")

    monkeypatch.setattr(
        "newsradar.web.app.OperationCommandService.enqueue_event_merge_scan",
        fail_enqueue,
    )

    with TestClient(create_app()) as client:
        page = client.get("/event-merge-candidates")
        response = client.post(
            "/event-merge-candidates/scan",
            data={"action_token": _token(page.text)},
            headers=_safe_headers(),
        )

    assert response.status_code == 422
    assert "SECRET-MARKER" not in response.text
    assert "SECRET-MARKER" not in caplog.text
    assert all("SECRET-MARKER" not in repr(record.__dict__) for record in caplog.records)
