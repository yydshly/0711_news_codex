from contextlib import nullcontext
from datetime import UTC, datetime

from typer.testing import CliRunner

from newsradar.cli import app
from newsradar.ingestion.trial import ProbeSnapshot
from newsradar.sources.schema import SourceDefinition
from tests.test_source_schema import valid_source


runner = CliRunner()


def _source(source_id: str, *, coverage_mode: str = "direct") -> SourceDefinition:
    data = valid_source()
    data.update(
        {
            "id": source_id,
            "provider_id": "hn",
            "coverage_mode": coverage_mode,
            "ingestion": {"enabled": False},
        }
    )
    return SourceDefinition.model_validate(data)


def _successful_probe() -> ProbeSnapshot:
    return ProbeSnapshot(
        outcome="success",
        sample_count=1,
        field_completeness=1.0,
        sample_fields=frozenset({"title", "canonical_url"}),
        finished_at=datetime(2026, 7, 13, tzinfo=UTC),
    )


def test_trial_fetch_queues_only_eligible_direct_sources(monkeypatch) -> None:
    eligible = _source("hn-eligible")
    ineligible = _source("hn-no-probe")
    non_direct = _source("hn-discovery", coverage_mode="indirect")
    queued: list[dict[str, object]] = []

    class FakeSourceRepository:
        def __init__(self, session) -> None:
            pass

        def sync(self, sources) -> None:
            assert list(sources) == [eligible, ineligible, non_direct]

        def latest_probe_snapshot(self, source_id: str):
            return _successful_probe() if source_id != ineligible.id else None

    class FakeCommands:
        def __init__(self, session) -> None:
            pass

        def enqueue_fetch(self, **kwargs) -> int:
            queued.append(kwargs)
            return 41

    monkeypatch.setattr("newsradar.cli.load_source_tree", lambda root: [eligible, ineligible, non_direct])
    monkeypatch.setattr("newsradar.cli.SourceRepository", FakeSourceRepository)
    monkeypatch.setattr("newsradar.cli.OperationCommandService", FakeCommands)
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))

    result = runner.invoke(app, ["fetch", "--trial", "--provider", "hn", "--no-wait"])

    assert result.exit_code == 0
    assert "Trial candidates: 1" in result.stdout
    assert "no_probe" in result.stdout
    assert "discovery_only" in result.stdout
    assert queued == [
        {
            "source_id": eligible.id,
            "provider": "hn",
            "dry_run": False,
            "max_items": None,
            "trial": True,
            "trigger": "cli",
        }
    ]


def test_trial_fetch_rejects_one_off() -> None:
    result = runner.invoke(app, ["fetch", "--trial", "--one-off"])

    assert result.exit_code == 2
    assert "--trial cannot be used with --one-off" in result.stdout
