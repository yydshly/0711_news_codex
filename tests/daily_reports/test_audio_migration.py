from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def _upgrade(database_url: str, revision: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, revision)


def test_audio_artifact_migration_creates_append_only_daily_report_table(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'daily-report-audio.db').as_posix()}"
    _upgrade(database_url, "20260717_0025")
    _upgrade(database_url, "20260717_0026")

    inspector = inspect(create_engine(database_url))
    columns = {
        column["name"]
        for column in inspector.get_columns("daily_report_audio_artifacts")
    }
    assert columns >= {
        "id",
        "daily_report_id",
        "rendition",
        "status",
        "script",
        "script_sha256",
        "model",
        "voice_id",
        "audio_format",
        "sample_rate",
        "bitrate",
        "channel",
        "operation_run_id",
        "trace_id",
        "audio_duration_ms",
        "audio_size_bytes",
        "relative_audio_path",
        "audio_sha256",
        "error_code",
        "error_message",
        "created_at",
        "updated_at",
    }
    checks = {
        check["name"]
        for check in inspector.get_check_constraints("daily_report_audio_artifacts")
    }
    assert {
        "ck_daily_report_audio_artifact_rendition",
        "ck_daily_report_audio_artifact_status",
    } <= checks
    assert "ix_daily_report_audio_artifacts_report_rendition" in {
        index["name"]
        for index in inspector.get_indexes("daily_report_audio_artifacts")
    }
