from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from newsradar.db.models import (
    Base,
    HighValueWaveMemberRecord,
    RawItemRecord,
    SourceDefinitionRecord,
)
from newsradar.events.evidence import assess_evidence
from newsradar.events.pipeline import EventPipeline
from newsradar.events.schema import CandidateCluster, EventStatus
from newsradar.events.scoring import decide_publication
from newsradar.waves.repository import WaveRepository


def _source(source_id: str, *, nature: str = "community", roles: list[str] | None = None):
    return SourceDefinitionRecord(
        id=source_id,
        name=source_id,
        status="active",
        nature=nature,
        language="en",
        roles=roles or ["discovery"],
        topics=["ai"],
        authority_score=50,
        poll_interval_minutes=60,
        expected_fields=[],
        definition_hash=f"{source_id}-hash",
    )


def _item(source_id: str, external_id: str, *, last_seen_run_id: int) -> RawItemRecord:
    now = datetime.now(UTC)
    return RawItemRecord(
        source_id=source_id,
        external_id=external_id,
        canonical_url=f"https://example.test/{source_id}/{external_id}",
        payload={},
        title="OpenAI launches a new AI model",
        published_at=now,
        fetched_at=now,
        last_seen_run_id=last_seen_run_id,
    )


def _wave_member(
    operation_id: int,
    source_id: str,
    *,
    fetch_run_id: int,
    nature: str = "first_party",
    roles: list[str] | None = None,
) -> HighValueWaveMemberRecord:
    return HighValueWaveMemberRecord(
        operation_run_id=operation_id,
        source_id=source_id,
        provider_id="provider",
        definition_hash=f"{source_id}-frozen",
        nature_snapshot=nature,
        roles_snapshot=roles or ["evidence"],
        availability_snapshot="ready",
        access_kind_snapshot="rss",
        fetchable=True,
        state="succeeded",
        fetch_run_id=fetch_run_id,
    )


def _selection(db: Session, operation_id: int):
    scope = WaveRepository(db).event_selection_scope(operation_id)
    assert scope is not None
    pipeline = EventPipeline(sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    return pipeline._select_and_classify_items(
        24, now=datetime.now(UTC), selection_scope=scope
    )


def test_wave_selection_uses_frozen_nature_and_roles_after_live_catalog_changes() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = _source("official", nature="community", roles=["discovery"])
        db.add_all((source, _wave_member(1, "official", fetch_run_id=11)))
        db.add(_item("official", "wave-item", last_seen_run_id=11))
        db.commit()

        # The catalog can move after enqueue; the completed wave must not inherit it.
        source.nature = "social"
        source.roles = ["discovery"]
        db.commit()
        selection = _selection(db, 1)

    assert len(selection.included) == 1
    evidence = assess_evidence(selection.included)
    decision = decide_publication(
        CandidateCluster(candidate_key="frozen-source", items=selection.included), evidence
    )
    assert evidence[0].role.value == "official"
    assert evidence[0].independent is True
    assert decision.status is EventStatus.CONFIRMED


def test_wave_selection_excludes_same_window_items_not_seen_by_its_fetch_runs() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            (
                _source("source"),
                _wave_member(1, "source", fetch_run_id=11),
                _item("source", "wave-item", last_seen_run_id=11),
                _item("source", "outside-wave", last_seen_run_id=99),
            )
        )
        db.commit()
        selection = _selection(db, 1)

    assert [item.raw_item_id for item in selection.included] == [1]


def test_wave_selection_requires_the_frozen_source_and_fetch_run_pair() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            (
                _source("in-wave"),
                _source("out-of-wave"),
                _wave_member(1, "in-wave", fetch_run_id=11),
                _item("in-wave", "included", last_seen_run_id=11),
                _item("out-of-wave", "same-fetch-run", last_seen_run_id=11),
            )
        )
        db.commit()
        selection = _selection(db, 1)

    assert [item.canonical_url for item in selection.included] == [
        "https://example.test/in-wave/included"
    ]
