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
