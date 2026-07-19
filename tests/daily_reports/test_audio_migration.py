import logging
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

    foreign_keys = {
        tuple(foreign_key["constrained_columns"]): foreign_key
        for foreign_key in inspector.get_foreign_keys("daily_report_audio_artifacts")
    }
    assert foreign_keys[("daily_report_id",)]["referred_table"] == "daily_reports"
    assert foreign_keys[("daily_report_id",)]["options"]["ondelete"] == "CASCADE"
    assert foreign_keys[("operation_run_id",)]["referred_table"] == "operation_runs"
    assert foreign_keys[("operation_run_id",)]["options"]["ondelete"] == "RESTRICT"

    indexes = {
        index["name"]: index["column_names"]
        for index in inspector.get_indexes("daily_report_audio_artifacts")
    }
    assert indexes["ix_daily_report_audio_artifacts_report_rendition"] == [
        "daily_report_id",
        "rendition",
        "created_at",
    ]

    columns_by_name = {
        column["name"]: column
        for column in inspector.get_columns("daily_report_audio_artifacts")
    }
    required_columns = {
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
        "created_at",
        "updated_at",
    }
    assert all(not columns_by_name[name]["nullable"] for name in required_columns)
    assert {
        "rendition": 16,
        "status": 16,
        "script_sha256": 64,
        "model": 64,
        "voice_id": 120,
        "relative_audio_path": 512,
    }.items() <= {
        name: columns_by_name[name]["type"].length
        for name in columns_by_name
        if getattr(columns_by_name[name]["type"], "length", None) is not None
    }.items()


def test_audio_migration_preserves_existing_application_loggers(tmp_path: Path) -> None:
    logger = logging.getLogger("newsradar.daily_reports.repository")
    original_disabled = logger.disabled
    logger.disabled = False
    database_url = f"sqlite:///{(tmp_path / 'logger-isolation.db').as_posix()}"

    try:
        _upgrade(database_url, "20260717_0026")

        assert logger.disabled is False
    finally:
        logger.disabled = original_disabled
