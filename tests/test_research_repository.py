from datetime import UTC, datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    SourceAcquisitionCandidateRecord,
    SourceAcquisitionProbeRunRecord,
    SourceDefinitionVersion,
    SourceResearchProfileRecord,
)
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import SourceDefinition

from .test_source_schema import valid_source


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def researched_source() -> SourceDefinition:
    data = valid_source()
    data["research"] = {
        "status": "verified",
        "purpose": "Track releases",
        "wanted_information": ["title", "url"],
        "risk_conclusion": "Public RSS is acceptable.",
        "no_fallback_reason": "The official feed is sufficient.",
        "reviewed_at": "2026-07-12",
        "candidates": [
            {
                "key": "official-rss",
                "kind": "rss",
                "implementation": "feedparser",
                "officiality": "official",
                "authentication": "none",
                "roles": ["discovery", "metadata"],
                "fields": ["title", "canonical_url"],
                "limitations": [],
                "evidence": ["https://www.anthropic.com/news"],
                "reviewed_at": "2026-07-12",
                "sample_status": "succeeded",
                "decision": "primary",
            }
        ],
    }
    return SourceDefinition.model_validate(data)


def test_sync_persists_current_research_projection_and_is_idempotent() -> None:
    source = researched_source()
    with make_session() as session:
        repository = SourceRepository(session)
        repository.sync([source])
        result = repository.sync([source])
        session.commit()

        assert result.unchanged == 1
        profile = session.get(SourceResearchProfileRecord, source.id)
        candidate = session.scalar(select(SourceAcquisitionCandidateRecord))
        assert profile is not None
        assert profile.status == "verified"
        assert candidate is not None
        assert candidate.candidate_key == "official-rss"
        assert session.scalar(select(func.count()).select_from(SourceDefinitionVersion)) == 1
        assert (
            session.scalar(select(func.count()).select_from(SourceAcquisitionCandidateRecord)) == 1
        )


def test_sync_versions_candidate_changes_and_removes_only_current_projection() -> None:
    original = researched_source()
    changed_data = original.model_dump(mode="json", exclude={"total_risk": True, "risk": {"total"}})
    changed_data["research"]["candidates"][0]["fields"] = ["title", "content"]
    changed = SourceDefinition.model_validate(changed_data)
    removed_data = changed.model_dump(mode="json", exclude={"total_risk": True, "risk": {"total"}})
    removed_data["research"]["status"] = "needs_research"
    removed_data["research"]["candidates"] = []
    removed = SourceDefinition.model_validate(removed_data)

    with make_session() as session:
        repository = SourceRepository(session)
        repository.sync([original])
        repository.sync([changed])
        repository.sync([removed])
        session.commit()

        assert session.scalar(select(func.count()).select_from(SourceDefinitionVersion)) == 3
        assert session.scalars(select(SourceAcquisitionCandidateRecord)).all() == []


def test_candidate_update_preserves_probe_history_and_sanitizes_details() -> None:
    original = researched_source()
    changed_data = original.model_dump(mode="json", exclude={"total_risk": True, "risk": {"total"}})
    changed_data["research"]["candidates"][0]["limitations"] = ["No full text"]
    changed = SourceDefinition.model_validate(changed_data)
    now = datetime.now(UTC)

    with make_session() as session:
        repository = SourceRepository(session)
        repository.sync([original])
        candidate = session.scalar(select(SourceAcquisitionCandidateRecord))
        assert candidate is not None
        repository.save_acquisition_probe_run(
            candidate_id=candidate.id,
            started_at=now,
            completed_at=now,
            outcome="succeeded",
            details={
                "authorization": "Bearer secret",
                "url": "https://user:secret@example.test/feed",
                "fields": ["title"],
            },
        )
        repository.sync([changed])
        session.commit()

        updated = session.scalar(select(SourceAcquisitionCandidateRecord))
        run = session.scalar(select(SourceAcquisitionProbeRunRecord))
        assert updated is not None
        assert updated.id == candidate.id
        assert updated.limitations == ["No full text"]
        assert run is not None
        assert run.candidate_id == updated.id
        assert run.details == {"url": "[redacted credential URL]", "fields": ["title"]}
