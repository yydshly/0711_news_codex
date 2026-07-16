from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, OperationRunRecord
from newsradar.web.operation_queries import OperationQueryService


def test_operation_query_projects_newest_runs_and_error_state() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                OperationRunRecord(
                    operation_type="fetch", trigger="manual", status="failed",
                    requested_scope={"source_id": "gdelt-ai"}, result_summary={},
                    attempt_count=1, error_code="rate_limited", error_message="429",
                ),
                OperationRunRecord(
                    operation_type="source_sync", trigger="manual", status="succeeded",
                    requested_scope={}, result_summary={}, attempt_count=1,
                ),
            ]
        )
        session.commit()
        rows = OperationQueryService(session).list_recent()

    assert [row.operation_type for row in rows] == ["source_sync", "fetch"]
    assert rows[1].source_id == "gdelt-ai"
    assert rows[1].error_code == "rate_limited"


def test_operation_detail_projects_only_allow_listed_wave_metrics() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        record = OperationRunRecord(
            operation_type="high_value_news_wave",
            trigger="manual",
            status="succeeded",
            requested_scope={},
            result_summary={
                "member_total": 41,
                "evidence_capable_members": 18,
                "direct_evidence_fetch_succeeded": 15,
                "events_with_official_root": 4,
                "events_with_one_professional_root": 3,
                "events_with_two_professional_roots": 2,
                "confirmed_event_count": 6,
                "ambiguous_pairs_checked": 7,
                "model_pair_fallback_count": 1,
                "api_key": "must-not-project",
                "Authorization": "Bearer must-not-project",
            },
        )
        session.add(record)
        session.commit()
        detail = OperationQueryService(session).get(record.id)

    assert detail is not None
    assert detail.wave_metrics is not None
    assert detail.wave_metrics.member_total == 41
    assert not hasattr(detail.wave_metrics, "api_key")
