from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base, HighValueWaveMemberRecord, OperationRunRecord
from newsradar.ingestion.schema import FetchOutcome, FetchResult
from newsradar.ingestion.service import SourceFetchSummary
from newsradar.operations.repository import OperationLease, OperationRepository
from newsradar.operations.schema import OperationType
from newsradar.sources.repository import canonical_definition
from newsradar.sources.schema import SourceDefinition
from tests.operations.test_fetch_runtime import _source


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _lease(operation_id: int, attempt_id: int = 1) -> OperationLease:
    return OperationLease(
        operation_id, attempt_id, 1, "worker", {}, OperationType.HIGH_VALUE_NEWS_WAVE
    )


def _freeze(
    db: Session, *sources: SourceDefinition, fetchable: dict[str, bool] | None = None
) -> int:
    operation = OperationRepository(db).enqueue(OperationType.HIGH_VALUE_NEWS_WAVE, {})
    for source in sources:
        _, definition_hash = canonical_definition(source)
        db.add(
            HighValueWaveMemberRecord(
                operation_run_id=operation.id,
                source_id=source.id,
                provider_id=source.provider_id,
                definition_hash=definition_hash,
                roles_snapshot=["discovery"],
                availability_snapshot="ready",
                access_kind_snapshot="rss",
                fetchable=(fetchable or {}).get(source.id, True),
                state="pending",
            )
        )
    db.get(OperationRunRecord, operation.id).progress_total = len(sources)
    db.commit()
    return operation.id


def test_wave_fetches_only_claimed_fetchable_members_and_blocks_others() -> None:
    from newsradar.waves.runtime import HighValueWaveHandler

    first, second, blocked = _source("first"), _source("second"), _source("blocked")
    fetched: list[str] = []
    with _session() as db:
        operation_id = _freeze(db, first, second, blocked, fetchable={"blocked": False})

        def execute(source, operation_id, checkpoint, scope):
            fetched.append(source.id)
            return SourceFetchSummary(
                source.id, FetchResult(outcome=FetchOutcome.SUCCEEDED), fetch_run_id=9
            )

        result = HighValueWaveHandler([first, second, blocked], lambda: db, execute)(
            _lease(operation_id), lambda _: None
        )
        members = {member.source_id: member for member in db.query(HighValueWaveMemberRecord)}

        assert fetched == ["first", "second"]
        assert result.result_summary["fetch_succeeded"] == 2
        assert result.result_summary["blocked"] == 1
        assert members["blocked"].state == "blocked"
        assert members["blocked"].conclusion and "冻结" in members["blocked"].conclusion
        assert db.get(OperationRunRecord, operation_id).progress_current == 3


def test_stale_definition_finishes_without_network() -> None:
    from newsradar.waves.runtime import HighValueWaveHandler

    frozen = _source("source")
    changed = frozen.model_copy(update={"name": "Changed source"})
    calls: list[str] = []
    with _session() as db:
        operation_id = _freeze(db, frozen)
        handler = HighValueWaveHandler([changed], lambda: db, lambda *args: calls.append("network"))

        result = handler.run_member(operation_id=operation_id, source_id="source", attempt_id=1)

        assert result.result_code == "stale_result"
        assert calls == []
        assert db.query(HighValueWaveMemberRecord).one().state == "stale_result"


def test_claim_failure_performs_no_network_io() -> None:
    from newsradar.waves.runtime import HighValueWaveHandler

    source = _source("source")
    calls: list[str] = []
    with _session() as db:
        operation_id = _freeze(db, source)
        db.query(HighValueWaveMemberRecord).one().state = "running"
        db.commit()
        result = HighValueWaveHandler(
            [source], lambda: db, lambda *args: calls.append("network")
        ).run_member(operation_id=operation_id, source_id="source", attempt_id=1)

        assert result.result_code == "already_claimed"
        assert calls == []
