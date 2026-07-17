from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def _config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_overview_editorial_migration_upgrades_and_downgrades(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'daily-report-overview.db').as_posix()}"
    config = _config(database_url)
    command.upgrade(config, "20260717_0026")
    command.upgrade(config, "20260717_0027")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert {
        "daily_report_overview_items",
        "daily_report_overview_editorial_reviews",
    } <= set(inspector.get_table_names())

    item_columns = {
        column["name"]: column
        for column in inspector.get_columns("daily_report_overview_items")
    }
    assert set(item_columns) >= {
        "id",
        "daily_report_id",
        "event_id",
        "event_version_number",
        "position",
        "snapshot",
        "decision_item_id",
    }
    assert all(
        not item_columns[name]["nullable"]
        for name in (
            "daily_report_id",
            "event_id",
            "event_version_number",
            "position",
            "snapshot",
        )
    )
    item_checks = {
        check["name"]
        for check in inspector.get_check_constraints("daily_report_overview_items")
    }
    assert "ck_daily_report_overview_position" in item_checks
    item_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "daily_report_overview_items"
        )
    }
    assert {
        "uq_daily_report_overview_event_version",
        "uq_daily_report_overview_position",
    } <= item_uniques
    item_indexes = {
        index["name"]: index["column_names"]
        for index in inspector.get_indexes("daily_report_overview_items")
    }
    assert item_indexes["ix_daily_report_overview_report_position"] == [
        "daily_report_id",
        "position",
    ]
    item_foreign_keys = {
        tuple(foreign_key["constrained_columns"]): foreign_key
        for foreign_key in inspector.get_foreign_keys(
            "daily_report_overview_items"
        )
    }
    assert item_foreign_keys[("daily_report_id",)]["referred_table"] == "daily_reports"
    assert item_foreign_keys[("daily_report_id",)]["options"]["ondelete"] == "CASCADE"
    assert item_foreign_keys[("event_id",)]["referred_table"] == "events"
    assert item_foreign_keys[("event_id",)]["options"]["ondelete"] == "RESTRICT"
    assert item_foreign_keys[("decision_item_id",)]["referred_table"] == "daily_report_items"
    assert item_foreign_keys[("decision_item_id",)]["options"]["ondelete"] == "SET NULL"

    review_columns = {
        column["name"]: column
        for column in inspector.get_columns(
            "daily_report_overview_editorial_reviews"
        )
    }
    assert set(review_columns) >= {
        "id",
        "daily_report_overview_item_id",
        "revision",
        "decision",
        "zh_title",
        "zh_summary",
        "review_recommendation",
        "evidence_assessment",
        "duplicate_of_overview_item_id",
        "copied_from_editorial_review_id",
        "created_at",
    }
    assert all(
        not review_columns[name]["nullable"]
        for name in (
            "daily_report_overview_item_id",
            "revision",
            "decision",
            "zh_title",
            "zh_summary",
            "review_recommendation",
            "evidence_assessment",
            "created_at",
        )
    )
    review_checks = {
        check["name"]
        for check in inspector.get_check_constraints(
            "daily_report_overview_editorial_reviews"
        )
    }
    assert {
        "ck_daily_report_overview_review_revision",
        "ck_daily_report_overview_review_decision",
    } <= review_checks
    review_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "daily_report_overview_editorial_reviews"
        )
    }
    assert "uq_daily_report_overview_review_item_revision" in review_uniques
    review_indexes = {
        index["name"]: index["column_names"]
        for index in inspector.get_indexes(
            "daily_report_overview_editorial_reviews"
        )
    }
    assert review_indexes["ix_daily_report_overview_reviews_item_revision"] == [
        "daily_report_overview_item_id",
        "revision",
    ]
    review_foreign_keys = {
        tuple(foreign_key["constrained_columns"]): foreign_key
        for foreign_key in inspector.get_foreign_keys(
            "daily_report_overview_editorial_reviews"
        )
    }
    assert review_foreign_keys[("daily_report_overview_item_id",)]["referred_table"] == (
        "daily_report_overview_items"
    )
    assert review_foreign_keys[("daily_report_overview_item_id",)]["options"][
        "ondelete"
    ] == "CASCADE"
    assert review_foreign_keys[("duplicate_of_overview_item_id",)]["referred_table"] == (
        "daily_report_overview_items"
    )
    assert review_foreign_keys[("copied_from_editorial_review_id",)][
        "referred_table"
    ] == "daily_report_overview_editorial_reviews"

    engine.dispose()
    command.downgrade(config, "20260717_0026")
    downgraded = inspect(create_engine(database_url))
    assert "daily_report_overview_items" not in downgraded.get_table_names()
    assert "daily_report_overview_editorial_reviews" not in downgraded.get_table_names()
