
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newsradar.db.models import Base, HighValueWaveMemberRecord, OperationRunRecord
from newsradar.waves import WaveMemberSnapshot, WavePlan
from newsradar.waves.repository import WaveRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def plan(*members: WaveMemberSnapshot) -> WavePlan:
    return WavePlan("high-value", tuple(members), "digest", 24, 7)


def member(source_id: str, *, fetchable: bool = True) -> WaveMemberSnapshot:
    return WaveMemberSnapshot(
        source_id=source_id,
        provider_id="provider",
        definition_hash=f"hash-{source_id}",
        roles=("discovery",),
        availability="ready",
        access_kind="rss",
        fetchable=fetchable,
        blocked_reason=None if fetchable else "missing_credentials",
    )


def test_create_members_freezes_wave_plan(session: Session) -> None:
    WaveRepository(session).create_members(11, plan(member("b"), member("a", fetchable=False)))

    records = WaveRepository(session).members(11)

    assert [record.source_id for record in records] == ["a", "b"]
    assert records[0].roles_snapshot == ["discovery"]
    assert records[0].fetchable is False
    assert records[0].state == "blocked"


def test_unique_operation_source_constraint_rejects_duplicate_member(session: Session) -> None:
    WaveRepository(session).create_members(11, plan(member("a")))
    session.add(
        HighValueWaveMemberRecord(
            operation_run_id=11,
            source_id="a",
            provider_id="provider",
            definition_hash="other",
            roles_snapshot=[],
            availability_snapshot="ready",
            access_kind_snapshot="rss",
            fetchable=True,
            state="pending",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_finish_member_fences_stale_claim_and_advances_progress_once(session: Session) -> None:
    session.add(
        OperationRunRecord(
            id=11,
            operation_type="high_value_news_wave",
            trigger="test",
            status="running",
            requested_scope={},
            result_summary={},
            progress_total=1,
        )
    )
    session.commit()
    repository = WaveRepository(session)
    repository.create_members(11, plan(member("a")))
    repository.claim_member(11, "a", claim_attempt_id=7)
    with pytest.raises(PermissionError):
        repository.finish_member(
            11, "a", state="succeeded", result_code=None, conclusion="late", claim_attempt_id=8
        )
    repository.finish_member(
        11, "a", state="succeeded", result_code=None, conclusion="done", claim_attempt_id=7
    )
    repository.finish_member(
        11, "a", state="succeeded", result_code=None, conclusion="again", claim_attempt_id=7
    )
    assert session.get(OperationRunRecord, 11).progress_current == 1
