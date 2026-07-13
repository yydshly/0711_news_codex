from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    Base,
    RawItemRecord,
    SourceAcquisitionProbeRunRecord,
    SourceProbeRunRecord,
)
from newsradar.operations.repository import OperationLease, OperationRepository
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.operations.worker import Worker
from newsradar.research.probes.schema import AcquisitionProbeOutcome, probe_result
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import SourceDefinition
from tests.test_source_schema import valid_source


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _source(authentication: str = "none") -> SourceDefinition:
    data = valid_source()
    data["research"] = {
        "status": "needs_research",
        "candidates": [
            {
                "key": "official-rss",
                "kind": "rss",
                "implementation": "feedparser",
                "officiality": "official",
                "authentication": authentication,
                "roles": ["discovery"],
                "fields": ["title", "canonical_url", "published_at"],
                "limitations": ["仅验证候选方式"],
                "evidence": ["https://www.anthropic.com/news/rss.xml"],
                "reviewed_at": "2026-07-13",
                "sample_status": "not_run",
                "decision": "primary",
            }
        ],
    }
    return SourceDefinition.model_validate(data)


class _OwnedProbe:
    async def __aenter__(self) -> _OwnedProbe:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def probe(self, source, candidate, limit=5):
        assert limit == 5
        return probe_result(
            source,
            candidate,
            AcquisitionProbeOutcome.SUCCEEDED,
            "候选 RSS 可读取。",
        )


def test_worker_runs_remediation_and_persists_research_probe_without_raw_item() -> None:
    from newsradar.remediation.runtime import SourceRemediationHandler

    source = _source()
    engine = _engine()
    with Session(engine) as session:
        repository = SourceRepository(session)
        repository.sync([source])
        original = SourceProbeRunRecord(
            source_id=source.id,
            access_kind="rss",
            access_url="https://www.anthropic.com/news/rss.xml",
            outcome="failed",
            started_at=datetime(2026, 7, 13, tzinfo=UTC),
            finished_at=datetime(2026, 7, 13, tzinfo=UTC),
            response_headers={},
            metrics={},
            suggested_status="degraded",
            reason="基线失败",
        )
        session.add(original)
        session.flush()
        OperationRepository(session).enqueue(
            OperationType.SOURCE_REMEDIATION,
            {
                "source_id": source.id,
                "candidate_key": "official-rss",
                "original_probe_id": original.id,
                "deadline_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            },
        )
        session.commit()

        handler = SourceRemediationHandler(
            [source],
            lambda: Session(engine),
            lambda _source, _candidate: _OwnedProbe(),
        )
        processed = Worker(OperationRepository(session), "worker-a").run_once(handler)

        assert processed is True
        session.expire_all()
        assert (
            session.scalar(select(func.count()).select_from(SourceAcquisitionProbeRunRecord)) == 1
        )
        stored = session.scalar(select(SourceAcquisitionProbeRunRecord))
        operation_id = session.scalar(select(SourceAcquisitionProbeRunRecord.operation_run_id))
        assert operation_id is not None
        assert stored.original_probe_id == original.id
        assert session.scalar(select(func.count()).select_from(RawItemRecord)) == 0


def test_remediation_requiring_credentials_does_not_open_a_network_probe() -> None:
    from newsradar.remediation.runtime import SourceRemediationHandler

    source = _source("api_key")
    engine = _engine()
    calls: list[str] = []
    handler = SourceRemediationHandler(
        [source],
        lambda: Session(engine),
        lambda _source, _candidate: calls.append("network"),  # type: ignore[arg-type]
    )

    result = handler(
        OperationLease(
            operation_id=1,
            attempt_id=1,
            attempt_number=1,
            worker_id="worker-a",
            operation_type="source_remediation",
            requested_scope={
                "source_id": source.id,
                "candidate_key": "official-rss",
                "original_probe_id": 1,
            },
        ),
        lambda _boundary: None,
    )

    assert result.status == OperationStatus.FAILED
    assert result.error_code == "candidate_requires_credentials"
    assert calls == []


def test_connect_error_is_classified_as_network_transient() -> None:
    from newsradar.remediation.runtime import _result_category

    source = _source()
    candidate = source.research.candidates[0]
    result = probe_result(
        source,
        candidate,
        AcquisitionProbeOutcome.FAILED,
        "公开接口暂时无法连接。",
        "ConnectError",
    )

    assert _result_category(result) == "network_transient"
