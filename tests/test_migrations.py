import subprocess
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import TEXT, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from newsradar.db.models import EventMergeCandidateRecord


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _upgrade(database_url: str, revision: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, revision)


def test_event_merge_candidate_migration_round_trips_with_matching_constraints(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path / "event-merge-candidates.db")
    _upgrade(database_url, "20260716_0023")
    engine = create_engine(database_url)

    _upgrade(database_url, "20260716_0024")

    expected_columns = {
        "id",
        "revision",
        "supersedes_candidate_id",
        "left_event_id",
        "left_version_number",
        "right_event_id",
        "right_version_number",
        "candidate_type",
        "status",
        "algorithm_version",
        "input_fingerprint",
        "facts_snapshot",
        "reason_codes",
        "zh_reason",
        "zh_next_action",
        "generated_operation_id",
        "reviewed_operation_id",
        "applied_operation_id",
        "reviewed_at",
        "result_summary",
        "created_at",
        "updated_at",
    }
    expected_checks = {
        "ck_event_merge_pair_order",
        "ck_event_merge_left_version",
        "ck_event_merge_right_version",
        "ck_event_merge_candidate_type",
        "ck_event_merge_candidate_status",
        "ck_event_merge_candidate_revision",
    }
    model_table = EventMergeCandidateRecord.__table__
    assert set(model_table.columns.keys()) == expected_columns
    assert {
        constraint.name
        for constraint in model_table.constraints
        if constraint.name in expected_checks
    } == expected_checks
    assert {index.name for index in model_table.indexes} == {
        "ix_event_merge_candidates_status_type",
        "uq_event_merge_candidate_root",
    }
    model_root_index = next(
        index
        for index in model_table.indexes
        if index.name == "uq_event_merge_candidate_root"
    )
    assert model_root_index.unique
    assert str(model_root_index.dialect_options["sqlite"]["where"]) == (
        "supersedes_candidate_id IS NULL"
    )
    assert str(model_root_index.dialect_options["postgresql"]["where"]) == (
        "supersedes_candidate_id IS NULL"
    )
    assert {
        (tuple(foreign_key.parent.name for foreign_key in constraint.elements), ondelete)
        for constraint in model_table.foreign_key_constraints
        if (ondelete := constraint.ondelete) is not None
    } == {
        (("left_event_id", "left_version_number"), "RESTRICT"),
        (("right_event_id", "right_version_number"), "RESTRICT"),
        (("generated_operation_id",), "RESTRICT"),
        (("reviewed_operation_id",), "RESTRICT"),
        (("applied_operation_id",), "RESTRICT"),
        (("supersedes_candidate_id",), "RESTRICT"),
    }
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "event_merge_candidates" in inspector.get_table_names()
        assert {
            column["name"] for column in inspector.get_columns("event_merge_candidates")
        } == expected_columns
        assert {
            constraint["name"]
            for constraint in inspector.get_check_constraints("event_merge_candidates")
        } == expected_checks
        unique_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(
                "event_merge_candidates"
            )
        }
        assert set(unique_constraints) == {
            "uq_event_merge_candidate_input",
            "uq_event_merge_candidate_supersedes",
        }
        assert unique_constraints["uq_event_merge_candidate_input"] == (
            "left_event_id",
            "left_version_number",
            "right_event_id",
            "right_version_number",
            "algorithm_version",
            "input_fingerprint",
            "revision",
        )
        assert unique_constraints["uq_event_merge_candidate_supersedes"] == (
            "supersedes_candidate_id",
        )
        indexes = {
            index["name"]: index
            for index in inspector.get_indexes("event_merge_candidates")
        }
        assert set(indexes) == {
            "ix_event_merge_candidates_status_type",
            "uq_event_merge_candidate_root",
        }
        root_index = indexes["uq_event_merge_candidate_root"]
        assert root_index["unique"] == 1
        assert tuple(root_index["column_names"]) == (
            "left_event_id",
            "left_version_number",
            "right_event_id",
            "right_version_number",
            "algorithm_version",
        )
        assert str(root_index["dialect_options"]["sqlite_where"]) == (
            "supersedes_candidate_id IS NULL"
        )
        foreign_keys = inspector.get_foreign_keys("event_merge_candidates")
        assert {
            (tuple(foreign_key["constrained_columns"]), foreign_key["referred_table"])
            for foreign_key in foreign_keys
        } == {
            (("left_event_id", "left_version_number"), "event_versions"),
            (("right_event_id", "right_version_number"), "event_versions"),
            (("generated_operation_id",), "operation_runs"),
            (("reviewed_operation_id",), "operation_runs"),
            (("applied_operation_id",), "operation_runs"),
            (("supersedes_candidate_id",), "event_merge_candidates"),
        }
        assert all(
            foreign_key["options"].get("ondelete") == "RESTRICT"
            for foreign_key in foreign_keys
        )

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "20260716_0023")

    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "event_merge_candidates" not in tables
        assert {"events", "event_versions", "event_items", "daily_reports"} <= tables

    _upgrade(database_url, "20260716_0024")
    with engine.connect() as connection:
        assert "event_merge_candidates" in inspect(connection).get_table_names()


def test_daily_report_migration_creates_archive_tables_without_changing_events(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path / "daily-reports.db")
    _upgrade(database_url, "20260716_0022")
    before = _seed_event_history(database_url)

    _upgrade(database_url, "head")

    engine = create_engine(database_url)
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert {"daily_reports", "daily_report_items"} <= set(inspector.get_table_names())
        assert {"daily_report_item_editorial_reviews"} <= set(inspector.get_table_names())
        report_columns = {column["name"] for column in inspector.get_columns("daily_reports")}
        item_columns = {
            column["name"] for column in inspector.get_columns("daily_report_items")
        }
        review_columns = {
            column["name"]
            for column in inspector.get_columns("daily_report_item_editorial_reviews")
        }
        assert {
            "report_date",
            "timezone",
            "window_hours",
            "window_start",
            "window_end",
            "source_operation_id",
            "status",
            "revision",
            "supersedes_report_id",
            "generation_summary",
            "generated_at",
            "archived_at",
        } <= report_columns
        assert {
            "daily_report_id",
            "event_id",
            "event_version_number",
            "section",
            "position",
            "included",
            "snapshot",
        } <= item_columns
        assert {index["name"] for index in inspector.get_indexes("daily_reports")} >= {
            "uq_daily_report_identity",
            "uq_daily_report_supersedes",
        }
        assert review_columns >= {
            "id",
            "daily_report_item_id",
            "revision",
            "decision",
            "zh_title",
            "zh_summary",
            "review_recommendation",
            "evidence_assessment",
            "created_at",
            "copied_from_editorial_review_id",
        }
        review_indexes = {
            index["name"]
            for index in inspector.get_indexes("daily_report_item_editorial_reviews")
        }
        assert "ix_daily_report_editorial_reviews_item_revision" in review_indexes
        after = {
            table_name: connection.execute(
                text(f"SELECT count(*) FROM {table_name}")
            ).scalar_one()
            for table_name in ("events", "event_versions", "event_items", "event_scores")
        }
        assert after == before


def test_daily_report_editorial_review_migration_round_trips(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "daily-report-editorial-reviews.db")
    _upgrade(database_url, "20260716_0024")
    engine = create_engine(database_url)

    _upgrade(database_url, "20260717_0025")
    with engine.connect() as connection:
        assert "daily_report_item_editorial_reviews" in inspect(
            connection
        ).get_table_names()

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "20260716_0024")
    with engine.connect() as connection:
        assert "daily_report_item_editorial_reviews" not in inspect(
            connection
        ).get_table_names()


def test_daily_report_migration_downgrade_removes_only_report_tables(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "daily-reports-downgrade.db")
    _upgrade(database_url, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        trigger_names = set(
            connection.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'trigger' AND name LIKE 'trg_daily_report_%'"
                )
            ).scalars()
        )
        assert trigger_names == {
            "trg_daily_report_archived_delete",
            "trg_daily_report_archived_update",
            "trg_daily_report_item_archived_delete",
            "trg_daily_report_item_archived_insert",
            "trg_daily_report_item_archived_update",
        }
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "20260716_0022")
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "daily_reports" not in tables
        assert "daily_report_items" not in tables
        assert {"events", "event_versions", "event_items", "event_scores"} <= tables
        assert connection.execute(
            text(
                "SELECT count(*) FROM sqlite_master "
                "WHERE type = 'trigger' AND name LIKE 'trg_daily_report_%'"
            )
        ).scalar_one() == 0


def test_daily_report_migration_downgrade_accepts_legacy_0023_without_new_indexes(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path / "legacy-daily-report-0023.db")
    _upgrade(database_url, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_daily_report_supersedes"))
        connection.execute(text("DROP INDEX uq_daily_report_identity"))

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "20260716_0022")

    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "daily_reports" not in tables
        assert "daily_report_items" not in tables
        assert {"events", "event_versions", "event_items", "event_scores"} <= tables


def _daily_report_guard_database(tmp_path: Path):
    database_url = _sqlite_url(tmp_path / "daily-report-guards.db")
    _upgrade(database_url, "20260716_0022")
    _seed_event_history(database_url)
    _upgrade(database_url, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO operation_runs "
                "(id, operation_type, trigger, status, requested_scope, result_summary, "
                "attempt_count, progress_current, created_at, updated_at) VALUES "
                "(9901, 'event_pipeline', 'test', 'succeeded', '{}', '{}', 1, 0, "
                "'2026-07-16T03:00:00+00:00', '2026-07-16T04:00:00+00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO daily_reports "
                "(id, report_date, timezone, window_hours, window_start, window_end, "
                "source_operation_id, status, revision, supersedes_report_id, "
                "generation_summary, generated_at, archived_at) VALUES "
                "(1, '2026-07-16', 'Asia/Shanghai', 24, '2026-07-15T04:00:00+00:00', "
                "'2026-07-16T04:00:00+00:00', 9901, 'draft', 1, NULL, '{}', "
                "'2026-07-16T04:00:00+00:00', NULL), "
                "(2, '2026-07-17', 'Asia/Shanghai', 24, '2026-07-16T04:00:00+00:00', "
                "'2026-07-17T04:00:00+00:00', 9901, 'draft', 1, NULL, '{}', "
                "'2026-07-17T04:00:00+00:00', NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO daily_report_items "
                "(id, daily_report_id, event_id, event_version_number, section, position, "
                "included, snapshot) VALUES "
                "(1, 1, 1, 2, 'confirmed', 1, 1, '{}'), "
                "(2, 2, 1, 1, 'emerging', 2, 1, '{}')"
            )
        )
    return engine


@pytest.mark.parametrize(
    "statement",
    (
        "UPDATE daily_reports SET generation_summary = '{\"changed\": true}' WHERE id = 1",
        "DELETE FROM daily_reports WHERE id = 1",
        "INSERT INTO daily_report_items "
        "(daily_report_id, event_id, event_version_number, section, position, included, snapshot) "
        "VALUES (1, 1, 1, 'emerging', 3, 1, '{}')",
        "UPDATE daily_report_items SET included = 0 WHERE id = 1",
        "DELETE FROM daily_report_items WHERE id = 1",
        "UPDATE daily_report_items SET daily_report_id = 1 WHERE id = 2",
    ),
)
def test_daily_report_migration_rejects_direct_sql_mutation_after_archive(
    tmp_path: Path, statement: str
) -> None:
    engine = _daily_report_guard_database(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE daily_reports SET status = 'archived', "
                "archived_at = '2026-07-16T05:00:00+00:00' WHERE id = 1"
            )
        )

    with pytest.raises(IntegrityError, match="daily_report_archived_immutable"):
        with engine.begin() as connection:
            connection.execute(text(statement))


@pytest.mark.parametrize(
    "statement",
    (
        "INSERT INTO daily_reports "
        "(report_date, timezone, window_hours, window_start, window_end, source_operation_id, "
        "status, revision, generation_summary, generated_at, archived_at) VALUES "
        "('2026-07-18', 'Asia/Shanghai', 24, '2026-07-17', '2026-07-18', 9901, "
        "'draft', 1, '{}', '2026-07-18', '2026-07-18')",
        "INSERT INTO daily_reports "
        "(report_date, timezone, window_hours, window_start, window_end, source_operation_id, "
        "status, revision, generation_summary, generated_at, archived_at) VALUES "
        "('2026-07-18', 'Asia/Shanghai', 24, '2026-07-17', '2026-07-18', 9901, "
        "'archived', 1, '{}', '2026-07-18', NULL)",
        "UPDATE daily_reports SET archived_at = '2026-07-17' WHERE id = 2",
    ),
)
def test_daily_report_migration_rejects_inconsistent_status_and_archive_time(
    tmp_path: Path, statement: str
) -> None:
    engine = _daily_report_guard_database(tmp_path)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text(statement))


def test_daily_report_migration_enforces_normal_identity_and_one_direct_child(
    tmp_path: Path,
) -> None:
    engine = _daily_report_guard_database(tmp_path)
    normal_duplicate = (
        "INSERT INTO daily_reports "
        "(report_date, timezone, window_hours, window_start, window_end, source_operation_id, "
        "status, revision, supersedes_report_id, generation_summary, generated_at, archived_at) "
        "VALUES ('2026-07-16', 'Asia/Shanghai', 24, '2026-07-15', '2026-07-16', 9901, "
        "'draft', 2, NULL, '{}', '2026-07-16', NULL)"
    )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text(normal_duplicate))

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO daily_reports "
                "(report_date, timezone, window_hours, window_start, window_end, "
                "source_operation_id, status, revision, supersedes_report_id, "
                "generation_summary, generated_at, archived_at) VALUES "
                "('2026-07-16', 'Asia/Shanghai', 24, '2026-07-15', '2026-07-16', "
                "9901, 'draft', 2, 1, '{}', '2026-07-16', NULL)"
            )
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO daily_reports "
                    "(report_date, timezone, window_hours, window_start, window_end, "
                    "source_operation_id, status, revision, supersedes_report_id, "
                    "generation_summary, generated_at, archived_at) VALUES "
                    "('2026-07-16', 'Asia/Shanghai', 24, '2026-07-15', '2026-07-16', "
                    "9901, 'draft', 3, 1, '{}', '2026-07-16', NULL)"
                )
            )


def test_high_value_wave_migration_creates_member_snapshots_without_altering_history(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path / "high-value-wave.db")
    _upgrade(database_url, "20260716_0019")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO operation_runs (id, operation_type, trigger, status, requested_scope, "
                "result_summary, attempt_count, progress_current, created_at, updated_at) VALUES "
                "(99, 'fetch', 'test', 'succeeded', '{}', '{}', 1, 0, CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP)"
            )
        )
    _upgrade(database_url, "head")
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "high_value_wave_members" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("high_value_wave_members")}
        assert {
            "nature_snapshot",
            "roles_snapshot",
            "fetchable",
            "claim_attempt_id",
            "finished_at",
        } <= columns
        assert (
            connection.execute(
                text("SELECT operation_type FROM operation_runs WHERE id = 99")
            ).scalar_one()
            == "fetch"
        )


def test_event_score_observation_time_migration_preserves_existing_scores(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path / "event-score-observation.db")
    _upgrade(database_url, "20260716_0020")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO event_scores (event_id, version_number, heat, breakdown, created_at) "
                "VALUES (1, 1, 50, '{}', '2026-07-08T00:05:00+00:00')"
            )
        )

    _upgrade(database_url, "head")

    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("event_scores")}
        assert "observed_at" in columns
        heat = connection.execute(
            text("SELECT heat FROM event_scores WHERE id = 1")
        ).scalar_one()
        assert heat == 50


def _seed_event_history(database_url: str) -> dict[str, int]:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO source_providers (
                    id, name, category, homepage, docs_url, terms_url, auth_mode, cost_tier,
                    availability, capabilities, required_env, reviewed_at, evidence,
                    unlock_requirements, definition_hash, created_at, updated_at
                ) VALUES (
                    'independent', 'Independent', 'publisher', 'https://example.com',
                    'https://example.com/docs', 'https://example.com/terms', 'none', 'free',
                    'ready', '[]', '[]', '2026-07-13', '[]', '[]', 'provider-hash',
                    '2026-07-13T00:00:00+00:00', '2026-07-13T00:00:00+00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO source_definitions (
                    id, name, status, nature, language, roles, topics, authority_score,
                    poll_interval_minutes, expected_fields, definition_hash, created_at, updated_at,
                    provider_id, target_type, availability, coverage_mode, unlock_requirements
                ) VALUES (
                    'legacy-source', 'Legacy Source', 'approved', 'publisher', 'zh', '[]', '[]', 80,
                    60, '[]', 'source-hash', '2026-07-13T00:00:00+00:00',
                    '2026-07-13T00:00:00+00:00', 'independent', 'publisher_feed', 'ready',
                    'direct', '[]'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO raw_items (
                    id, source_id, external_id, canonical_url, payload, fetched_at
                ) VALUES (
                    101, 'legacy-source', 'legacy-item', 'https://example.com/legacy-item', '{}',
                    '2026-07-13T00:00:00+00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO events (
                    id, canonical_key, status, occurred_at, current_version_number,
                    created_at, updated_at
                ) VALUES (
                    1, 'legacy-release', 'confirmed', '2026-07-13T00:00:00+00:00', 2,
                    '2026-07-13T00:00:00+00:00', '2026-07-13T01:00:00+00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO event_versions (
                    event_id, version_number, zh_title, zh_summary, payload, created_at
                ) VALUES
                    (1, 1, '旧事件第一版', '第一版摘要', '{}', '2026-07-13T00:00:00+00:00'),
                    (1, 2, '旧事件第二版', '第二版摘要', '{}', '2026-07-13T01:00:00+00:00')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO event_items (
                    event_id, raw_item_id, added_version_number, removed_version_number, created_at
                ) VALUES
                    (1, 101, 1, NULL, '2026-07-13T00:00:00+00:00')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO event_scores (
                    event_id, version_number, heat, breakdown, created_at
                ) VALUES
                    (1, 1, 60, '{}', '2026-07-13T00:00:00+00:00'),
                    (1, 2, 80, '{}', '2026-07-13T01:00:00+00:00')
                """
            )
        )
        return {
            table_name: connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()
            for table_name in ("events", "event_versions", "event_items", "event_scores")
        }


def test_full_offline_migration_creates_provider_tables_once() -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head", "--sql"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.count("CREATE TABLE source_providers") == 1
    assert result.stdout.count("ADD COLUMN provider_id") == 1


def test_catalog_refresh_migration_adds_frozen_members_and_nullable_probe_provenance(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path / "catalog-refresh.db")
    _upgrade(database_url, "20260715_0016")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO source_providers (
                    id, name, category, homepage, docs_url, terms_url, auth_mode, cost_tier,
                    availability, capabilities, required_env, reviewed_at, evidence,
                    unlock_requirements, definition_hash, created_at, updated_at
                ) VALUES (
                    'migration-provider', 'Migration Provider', 'publisher', 'https://example.com',
                    'https://example.com/docs', 'https://example.com/terms', 'none', 'free',
                    'ready', '[]', '[]', '2026-07-15', '[]', '[]', 'provider-hash',
                    '2026-07-15T00:00:00+00:00', '2026-07-15T00:00:00+00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO source_definitions (
                    id, name, status, nature, language, roles, topics, authority_score,
                    poll_interval_minutes, expected_fields, definition_hash, created_at, updated_at,
                    provider_id, target_type, availability, coverage_mode, unlock_requirements
                ) VALUES (
                    'migration-source', 'Migration Source', 'candidate', 'publisher', 'en', '[]',
                    '[]', 1, 60, '[]', 'source-hash', '2026-07-15T00:00:00+00:00',
                    '2026-07-15T00:00:00+00:00', 'migration-provider', 'publisher_feed',
                    'ready', 'direct', '[]'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO source_provider_probe_runs (
                    provider_id, probe_type, outcome, availability, reason, checked_at, evidence_url
                ) VALUES (
                    'migration-provider', 'capability', 'success', 'ready', 'legacy provider probe',
                    '2026-07-15T00:00:00+00:00', 'https://example.com/docs'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO source_probe_runs (
                    source_id, access_kind, access_url, outcome, started_at, finished_at,
                    response_headers, metrics, suggested_status, reason
                ) VALUES (
                    'migration-source', 'rss', 'https://example.com/feed', 'success',
                    '2026-07-15T00:00:00+00:00', '2026-07-15T00:00:01+00:00',
                    '{}', '{}', 'active', 'legacy source probe'
                )
                """
            )
        )
    _upgrade(database_url, "head")

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "source_catalog_refresh_members" in inspector.get_table_names()
        columns = {
            column["name"]: column
            for column in inspector.get_columns("source_catalog_refresh_members")
        }
        assert {"operation_run_id", "source_id", "definition_hash", "content_probe_run_ids"} <= set(
            columns
        )
        for table_name in ("source_probe_runs", "source_provider_probe_runs"):
            probe_columns = {column["name"]: column for column in inspector.get_columns(table_name)}
            assert probe_columns["operation_run_id"]["nullable"] is True
        assert (
            connection.execute(
                text(
                    "SELECT operation_run_id FROM source_probe_runs "
                    "WHERE reason = 'legacy source probe'"
                )
            ).scalar_one()
            is None
        )
        assert (
            connection.execute(
                text(
                    "SELECT operation_run_id FROM source_provider_probe_runs "
                    "WHERE reason = 'legacy provider probe'"
                )
            ).scalar_one()
            is None
        )
        assert {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("source_catalog_refresh_members")
        } >= {("operation_run_id", "source_id")}


def test_0018_preserves_null_provider_hash_on_0017_members(tmp_path: Path) -> None:
    db_url = _sqlite_url(tmp_path / "catalog-provider-hash.db")
    _upgrade(db_url, "20260715_0017")
    engine = create_engine(db_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO operation_runs (
                    id, operation_type, trigger, status, requested_scope, result_summary,
                    progress_current, progress_total, attempt_count, created_at, updated_at
                ) VALUES (
                    17, 'source_catalog_refresh', 'test', 'queued', '{}', '{}', 0, 1, 0,
                    '2026-07-15T00:00:00+00:00', '2026-07-15T00:00:00+00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO source_providers (
                    id, name, category, homepage, docs_url, terms_url, auth_mode, cost_tier,
                    availability, capabilities, required_env, reviewed_at, evidence,
                    unlock_requirements, definition_hash, created_at, updated_at
                ) VALUES (
                    'migration-provider', 'Migration Provider', 'publisher', 'https://example.com',
                    'https://example.com/docs', 'https://example.com/terms', 'none', 'free',
                    'ready', '[]', '[]', '2026-07-15', '[]', '[]', 'provider-hash',
                    '2026-07-15T00:00:00+00:00', '2026-07-15T00:00:00+00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO source_definitions (
                    id, name, status, nature, language, roles, topics, authority_score,
                    poll_interval_minutes, expected_fields, definition_hash, created_at, updated_at,
                    provider_id, target_type, availability, coverage_mode, unlock_requirements
                ) VALUES (
                    'migration-source', 'Migration Source', 'candidate', 'publisher', 'en', '[]',
                    '[]', 1, 60, '[]', 'source-hash', '2026-07-15T00:00:00+00:00',
                    '2026-07-15T00:00:00+00:00', 'migration-provider', 'publisher_feed',
                    'ready', 'direct', '[]'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO source_catalog_refresh_members (
                    operation_run_id, source_id, provider_id, definition_hash,
                    availability_snapshot, coverage_mode_snapshot, access_kind_snapshot, lane,
                    state, content_probe_run_ids, attempt_count
                ) VALUES (17, 'migration-source', 'migration-provider', 'source-hash',
                    'ready', 'direct', 'rss', 'content', 'pending', '[]', 0)
                """
            )
        )

    _upgrade(db_url, "20260716_0018")

    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT provider_definition_hash FROM source_catalog_refresh_members "
                    "WHERE operation_run_id = 17"
                )
            ).scalar_one()
            is None
        )
    _upgrade(db_url, "head")
    with engine.connect() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("source_catalog_refresh_members")
        }
        assert "claim_attempt_id" in columns


def test_raw_item_ingestion_upgrade_preserves_0002_history(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260711_0002")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO source_providers (
                    id, name, category, homepage, docs_url, terms_url, auth_mode, cost_tier,
                    availability, capabilities, required_env, reviewed_at, evidence,
                    unlock_requirements, definition_hash, created_at, updated_at
                ) VALUES (
                    'independent', 'Independent', 'publisher', 'https://example.com',
                    'https://example.com/docs', 'https://example.com/terms', 'none', 'free',
                    'ready', '[]', '[]', '2026-07-11', '[]', '[]', 'provider-hash',
                    '2026-07-11T00:00:00+00:00', '2026-07-11T00:00:00+00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO source_definitions (
                    id, name, status, nature, language, roles, topics, authority_score,
                    poll_interval_minutes, expected_fields, definition_hash, created_at, updated_at,
                    provider_id, target_type, availability, coverage_mode, unlock_requirements
                ) VALUES (
                    'legacy-source', 'Legacy', 'approved', 'publisher', 'en', '[]', '[]', 1,
                    60, '[]', 'source-hash', '2026-07-11T00:00:00+00:00',
                    '2026-07-11T00:00:00+00:00', 'independent', 'publisher_feed', 'ready',
                    'direct', '[]'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO source_probe_runs (
                    source_id, access_kind, access_url, outcome, started_at, finished_at,
                    response_headers, metrics, suggested_status, reason
                ) VALUES (
                    'legacy-source', 'rss', 'https://example.com/feed', 'succeeded',
                    '2026-07-11T00:00:00+00:00', '2026-07-11T00:00:01+00:00',
                    '{}', '{}', 'approved', 'legacy probe'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO raw_items (
                    source_id, external_id, canonical_url, payload, published_at, fetched_at
                ) VALUES (
                    'legacy-source', '42', 'https://example.com/article',
                    '{"legacy": true}', '2026-07-10T00:00:00+00:00',
                    '2026-07-11T00:00:00+00:00'
                )
                """
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "operation_runs" in inspector.get_table_names()
        fetch_run_foreign_keys = inspector.get_foreign_keys("fetch_runs")
        assert {
            (tuple(foreign_key["constrained_columns"]), foreign_key["referred_table"])
            for foreign_key in fetch_run_foreign_keys
        } >= {
            (("operation_run_id",), "operation_runs"),
            (("operation_attempt_id",), "operation_attempts"),
            (("access_method_id",), "source_access_methods"),
        }
        raw_item_foreign_keys = inspector.get_foreign_keys("raw_items")
        assert {
            (tuple(foreign_key["constrained_columns"]), foreign_key["referred_table"])
            for foreign_key in raw_item_foreign_keys
        } >= {
            (("first_seen_run_id",), "fetch_runs"),
            (("last_seen_run_id",), "fetch_runs"),
        }
        raw_item_columns = {
            column["name"]: column["type"] for column in inspector.get_columns("raw_items")
        }
        assert isinstance(raw_item_columns["external_id"], TEXT)
        fetch_run_item_columns = {
            column["name"]: column["type"] for column in inspector.get_columns("fetch_run_items")
        }
        assert isinstance(fetch_run_item_columns["external_id"], TEXT)
        payload = connection.execute(
            text("SELECT payload FROM raw_items WHERE external_id = '42'")
        ).scalar_one()
        assert payload == '{"legacy": true}'
        assert (
            connection.execute(
                text("SELECT name FROM source_providers WHERE id = 'independent'")
            ).scalar_one()
            == "Independent"
        )
        assert (
            connection.execute(
                text("SELECT name FROM source_definitions WHERE id = 'legacy-source'")
            ).scalar_one()
            == "Legacy"
        )
        assert (
            connection.execute(
                text("SELECT reason FROM source_probe_runs WHERE source_id = 'legacy-source'")
            ).scalar_one()
            == "legacy probe"
        )

    command.downgrade(config, "20260711_0002")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "20260711_0002"
        )
        assert "operation_runs" not in inspect(connection).get_table_names()
        assert (
            connection.execute(
                text("SELECT payload FROM raw_items WHERE external_id = '42'")
            ).scalar_one()
            == '{"legacy": true}'
        )


def test_v1_1_closure_migration_adds_multi_credential_storage(tmp_path: Path) -> None:
    database_path = tmp_path / "closure.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.connect() as connection:
        access_methods = inspect(connection).get_columns("source_access_methods")
        columns = {column["name"] for column in access_methods}
        raw_item_indexes = {index["name"] for index in inspect(connection).get_indexes("raw_items")}
        access_method_fk = next(
            foreign_key
            for foreign_key in inspect(connection).get_foreign_keys("fetch_runs")
            if foreign_key["constrained_columns"] == ["access_method_id"]
        )

    assert "auth_envs" in columns
    assert "ix_raw_items_title_fingerprint_published_at" in raw_item_indexes
    assert access_method_fk["options"].get("ondelete") == "SET NULL"


def test_source_research_migration_preserves_existing_source_and_raw_item(tmp_path: Path) -> None:
    database_path = tmp_path / "source-research.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(config, "20260712_0008")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO source_providers (id, name, category, homepage, docs_url, terms_url,
                auth_mode, cost_tier, availability, capabilities, required_env, reviewed_at,
                evidence, unlock_requirements, definition_hash, created_at, updated_at)
            VALUES ('independent', 'Independent', 'publisher', 'https://example.com',
                'https://example.com/docs', 'https://example.com/terms', 'none', 'free',
                'ready', '[]', '[]', '2026-07-11', '[]', '[]', 'provider-hash',
                '2026-07-11T00:00:00+00:00', '2026-07-11T00:00:00+00:00')
        """)
        )
        connection.execute(
            text("""
            INSERT INTO source_definitions (id, name, status, nature, language, roles, topics,
                authority_score, poll_interval_minutes, expected_fields, definition_hash,
                created_at, updated_at, provider_id, target_type, availability, coverage_mode,
                unlock_requirements)
            VALUES ('source', 'Source', 'candidate', 'publisher', 'en', '[]', '[]', 1, 60,
                '[]', 'source-hash', '2026-07-11T00:00:00+00:00',
                '2026-07-11T00:00:00+00:00', 'independent', 'publisher_feed', 'ready',
                'direct', '[]')
        """)
        )
        connection.execute(
            text("""
            INSERT INTO raw_items (source_id, external_id, canonical_url, payload, fetched_at)
            VALUES ('source', 'raw-1', 'https://example.com/item', '{}',
                    '2026-07-12T00:00:00+00:00')
        """)
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert {
            "source_research_profiles",
            "source_acquisition_candidates",
            "source_acquisition_probe_runs",
        } <= set(inspector.get_table_names())
        assert connection.execute(text("SELECT external_id FROM raw_items")).scalar_one() == "raw-1"
        assert (
            connection.execute(text("SELECT name FROM source_definitions")).scalar_one() == "Source"
        )
        assert {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("source_acquisition_candidates")
        } >= {("source_id", "candidate_key")}
        candidate_columns = {
            column["name"] for column in inspector.get_columns("source_acquisition_candidates")
        }
        assert {"is_current", "removed_at"} <= candidate_columns


def test_event_intelligence_migration_creates_event_tables_and_preserves_raw_items(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "event-intelligence.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "20260712_0006")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO source_providers (
                    id, name, category, homepage, docs_url, terms_url, auth_mode, cost_tier,
                    availability, capabilities, required_env, reviewed_at, evidence,
                    unlock_requirements, definition_hash, created_at, updated_at
                ) VALUES (
                    'independent', 'Independent', 'publisher', 'https://example.com',
                    'https://example.com/docs', 'https://example.com/terms', 'none', 'free',
                    'ready', '[]', '[]', '2026-07-11', '[]', '[]', 'provider-hash',
                    '2026-07-11T00:00:00+00:00', '2026-07-11T00:00:00+00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO source_definitions (
                    id, name, status, nature, language, roles, topics, authority_score,
                    poll_interval_minutes, expected_fields, definition_hash, created_at, updated_at,
                    provider_id, target_type, availability, coverage_mode, unlock_requirements
                ) VALUES (
                    'source', 'Source', 'approved', 'publisher', 'en', '[]', '[]', 1,
                    60, '[]', 'source-hash', '2026-07-11T00:00:00+00:00',
                    '2026-07-11T00:00:00+00:00', 'independent', 'publisher_feed', 'ready',
                    'direct', '[]'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO raw_items (source_id, external_id, canonical_url, payload, fetched_at)
                VALUES ('source', 'raw-1', 'https://example.com/item', '{}',
                        '2026-07-12T00:00:00+00:00')
                """
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        assert {
            "raw_item_processing",
            "event_candidates",
            "event_candidate_items",
            "events",
            "event_versions",
            "event_items",
            "entities",
            "event_entities",
            "event_scores",
            "event_model_runs",
        } <= tables

        def unique_columns(table_name: str) -> set[tuple[str, ...]]:
            return {
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints(table_name)
            }

        assert unique_columns("raw_item_processing") >= {
            ("raw_item_id", "stage", "algorithm_version")
        }
        assert unique_columns("event_candidates") >= {("candidate_key", "algorithm_version")}
        assert unique_columns("event_versions") >= {("event_id", "version_number")}
        assert unique_columns("event_items") >= {
            ("event_id", "raw_item_id", "added_version_number")
        }
        assert unique_columns("entities") >= {("canonical_key", "entity_type")}
        assert {index["name"] for index in inspector.get_indexes("events")} >= {
            "ix_events_status_occurred_at"
        }
        assert {index["name"] for index in inspector.get_indexes("event_scores")} >= {
            "ix_event_scores_ranking"
        }
        assert {index["name"] for index in inspector.get_indexes("event_candidates")} >= {
            "ix_event_candidates_state"
        }
        assert {index["name"] for index in inspector.get_indexes("event_items")} >= {
            "ix_event_items_active_membership"
        }
        assert connection.execute(text("SELECT external_id FROM raw_items")).scalar_one() == "raw-1"

    command.downgrade(config, "20260712_0006")
    with engine.connect() as connection:
        assert "events" not in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT external_id FROM raw_items")).scalar_one() == "raw-1"


def test_event_quality_v2_migration_preserves_history_and_marks_it_legacy(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path / "event-quality.db")
    _upgrade(database_url, "20260713_0013")
    counts_before = _seed_event_history(database_url)

    _upgrade(database_url, "head")

    with create_engine(database_url).connect() as connection:
        inspector = inspect(connection)
        assert (
            connection.execute(text("SELECT count(*) FROM events")).scalar_one()
            == (counts_before["events"])
        )
        assert (
            connection.execute(text("SELECT count(*) FROM event_versions")).scalar_one()
            == (counts_before["event_versions"])
        )
        assert (
            connection.execute(text("SELECT count(*) FROM event_items")).scalar_one()
            == (counts_before["event_items"])
        )
        assert (
            connection.execute(text("SELECT count(*) FROM event_scores")).scalar_one()
            == (counts_before["event_scores"])
        )
        legacy_visibilities = connection.execute(
            text("SELECT DISTINCT visibility FROM events")
        ).scalars()
        assert legacy_visibilities.all() == ["legacy"]
        event_columns = {column["name"]: column for column in inspector.get_columns("events")}
        assert event_columns["visibility"]["nullable"] is False
        assert {"display_tier", "rank_score"} <= set(event_columns)
        assert {index["name"] for index in inspector.get_indexes("events")} >= {
            "ix_events_visibility_status_occurred_at",
            "ix_events_tier_rank_occurred_at",
        }
        assert "event_pair_decisions" in inspector.get_table_names()
        assert {index["name"] for index in inspector.get_indexes("event_pair_decisions")} >= {
            "ix_event_pair_decisions_lookup"
        }
        model_run_columns = {column["name"] for column in inspector.get_columns("event_model_runs")}
        assert "pair_decision_id" in model_run_columns
        processing_columns = {
            column["name"] for column in inspector.get_columns("raw_item_processing")
        }
        assert {"outcome", "score", "reason_codes", "details"} <= processing_columns
