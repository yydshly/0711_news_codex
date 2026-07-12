from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from typer.testing import CliRunner

from newsradar.cli import app

from .test_provider_schema import valid_provider
from .test_source_schema import valid_source

runner = CliRunner()


def write_source(root: Path) -> None:
    root.mkdir()
    (root / "source.yaml").write_text(yaml.safe_dump(valid_source()), encoding="utf-8")


def test_validate_command_reports_source_count(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    write_source(root)
    result = runner.invoke(app, ["sources", "validate", "--root", str(root)])
    assert result.exit_code == 0
    assert "Validated 1 source" in result.stdout


def test_report_command_writes_markdown(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    output = tmp_path / "report.md"
    write_source(root)
    result = runner.invoke(app, ["sources", "report", "--root", str(root), "--output", str(output)])
    assert result.exit_code == 0
    assert output.exists()
    assert "Anthropic News" in output.read_text(encoding="utf-8")


def test_probe_command_rejects_unknown_source(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    write_source(root)
    result = runner.invoke(
        app, ["sources", "probe", "missing", "--root", str(root), "--no-persist"]
    )
    assert result.exit_code == 2
    assert "Unknown source id" in result.stdout


def test_probe_command_can_write_live_report(tmp_path: Path, monkeypatch) -> None:
    from .test_risk_and_reporting import success_result

    root = tmp_path / "sources"
    output = tmp_path / "live.md"
    write_source(root)

    async def fake_probe(selected, persist):
        return {selected[0].id: success_result(selected[0].id)}

    monkeypatch.setattr("newsradar.cli._probe_sources", fake_probe)
    result = runner.invoke(
        app,
        [
            "sources",
            "probe",
            "anthropic-news",
            "--root",
            str(root),
            "--no-persist",
            "--report-output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    assert "success" in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("command", "method"),
    [("init", "initialize"), ("start", "start"), ("status", "status"), ("stop", "stop")],
)
def test_db_command_delegates_to_manager(monkeypatch, command: str, method: str) -> None:
    fake = Mock()
    getattr(fake, method).return_value = f"{command} complete"
    monkeypatch.setattr("newsradar.cli.build_local_postgres_manager", lambda: fake)

    result = runner.invoke(app, ["db", command])

    assert result.exit_code == 0
    assert f"{command} complete" in result.stdout
    getattr(fake, method).assert_called_once_with()


def test_db_command_turns_manager_error_into_safe_cli_failure(monkeypatch) -> None:
    from newsradar.local_postgres import LocalPostgresError

    fake = Mock()
    fake.start.side_effect = LocalPostgresError("Port 55432 is already in use")
    monkeypatch.setattr("newsradar.cli.build_local_postgres_manager", lambda: fake)

    result = runner.invoke(app, ["db", "start"])

    assert result.exit_code == 1
    assert "Database error: Port 55432 is already in use" in result.output


def test_powershell_wrapper_limits_actions_and_delegates_to_cli() -> None:
    wrapper = Path("scripts/postgres.ps1").read_text(encoding="utf-8")

    assert 'ValidateSet("init", "start", "status", "stop")' in wrapper
    assert "uv run newsradar db $Action" in wrapper
    assert "Get-ChildItem Env:" not in wrapper


def test_diagnostics_create_reports_archive_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))
    monkeypatch.setattr(
        "newsradar.cli.collect_diagnostic_snapshot",
        lambda session: object(),
    )
    archive = tmp_path / "diagnostics.zip"
    monkeypatch.setattr(
        "newsradar.cli.create_diagnostic_bundle", lambda destination, snapshot: archive
    )

    result = runner.invoke(app, ["diagnostics", "create", "--destination", str(tmp_path)])

    assert result.exit_code == 0
    assert str(archive) in result.stdout


def test_provider_validate_command_reports_count(tmp_path: Path) -> None:
    root = tmp_path / "providers"
    root.mkdir()
    (root / "bluesky.yaml").write_text(yaml.safe_dump(valid_provider()), encoding="utf-8")

    result = runner.invoke(app, ["providers", "validate", "--root", str(root)])

    assert result.exit_code == 0
    assert "Validated 1 provider" in result.stdout


def test_coverage_command_filters_provider_and_writes_report(tmp_path: Path) -> None:
    provider_root = tmp_path / "providers"
    source_root = tmp_path / "sources"
    output = tmp_path / "coverage.md"
    provider_root.mkdir()
    source_root.mkdir()
    (provider_root / "bluesky.yaml").write_text(yaml.safe_dump(valid_provider()), encoding="utf-8")
    source = valid_source()
    source.update(
        {
            "provider_id": "bluesky",
            "official_identity_url": "https://bsky.app/profile/anthropic.com",
        }
    )
    (source_root / "source.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "sources",
            "coverage",
            "--provider",
            "bluesky",
            "--provider-root",
            str(provider_root),
            "--root",
            str(source_root),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "Catalog targets | 1" in output.read_text(encoding="utf-8")


def test_fetch_rejects_unapproved_sources_without_one_off(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    write_source(root)

    result = runner.invoke(app, ["fetch", "anthropic-news", "--root", str(root)])

    assert result.exit_code == 2
    assert "No approved ingestion sources" in result.stdout


def test_fetch_one_off_requires_confirmation(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    write_source(root)

    result = runner.invoke(
        app, ["fetch", "anthropic-news", "--root", str(root), "--one-off"], input="n\n"
    )

    assert result.exit_code == 1
    assert "One-off fetch risk" in result.stdout


def test_worker_command_claims_and_runs_one_queued_operation(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "sources"
    write_source(root)
    handler = object()
    calls: list[object] = []

    class FakeWorker:
        def __init__(self, repository, worker_id, *, lease_guard, monitor_interval_seconds):
            assert worker_id == "worker-test"
            assert callable(lease_guard)
            assert monitor_interval_seconds == 15

        def run_once(self, received_handler):
            calls.append(received_handler)
            return True

    monkeypatch.setattr(
        "newsradar.cli.FetchOperationHandler.production", lambda sources: handler
    )
    monkeypatch.setattr("newsradar.cli.Worker", FakeWorker)
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))

    result = runner.invoke(
        app, ["worker", "--root", str(root), "--worker-id", "worker-test", "--once"]
    )

    assert result.exit_code == 0
    assert calls == [handler]
    assert "processed 1 operation" in result.stdout


@pytest.mark.asyncio
async def test_fetch_batch_isolates_one_source_processing_exception(monkeypatch) -> None:
    from newsradar.ingestion.schema import FetchOutcome, FetchResult
    from newsradar.ingestion.service import SourceFetchSummary

    class Policy:
        class client:
            @staticmethod
            async def aclose():
                return None

    class Service:
        def __init__(self, session, factory):
            pass

        async def fetch_source(self, source, **kwargs):
            if source.id == "broken":
                raise RuntimeError("write failed")
            return SourceFetchSummary(source.id, FetchResult(outcome=FetchOutcome.SUCCEEDED))

    first = valid_source()
    first["id"] = "broken"
    second = valid_source()
    second["id"] = "healthy"
    monkeypatch.setattr("newsradar.cli.HttpPolicy.default", lambda: Policy())
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))
    monkeypatch.setattr("newsradar.cli.IngestionService", Service)

    from newsradar.cli import _fetch_sources
    from newsradar.sources.schema import SourceDefinition

    results = await _fetch_sources(
        [SourceDefinition.model_validate(first), SourceDefinition.model_validate(second)],
        approved=True,
        max_items=None,
        dry_run=False,
        operation_id=1,
    )

    assert [result.result.outcome for result in results] == [
        FetchOutcome.FAILED,
        FetchOutcome.SUCCEEDED,
    ]
