from typer.testing import CliRunner

from newsradar.cli import app


def test_sources_remediate_exposes_read_only_snapshot_command() -> None:
    result = CliRunner().invoke(app, ["sources", "remediate", "--help"])

    assert result.exit_code == 0
    assert "snapshot" in result.stdout
    assert "report" in result.stdout


def test_remediation_queue_requires_one_explicit_source_and_candidate() -> None:
    result = CliRunner().invoke(app, ["sources", "remediate", "queue", "--help"])

    assert result.exit_code == 0
    assert "SOURCE_ID" in result.stdout
    assert "CANDIDATE_KEY" in result.stdout
