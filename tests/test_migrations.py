import subprocess
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_full_offline_migration_creates_provider_tables_once() -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head", "--sql"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.count("CREATE TABLE source_providers") == 1
    assert result.stdout.count("ADD COLUMN provider_id") == 1


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
        payload = connection.execute(
            text("SELECT payload FROM raw_items WHERE external_id = '42'")
        ).scalar_one()
        assert payload == '{"legacy": true}'
        assert connection.execute(
            text("SELECT name FROM source_providers WHERE id = 'independent'")
        ).scalar_one() == "Independent"
        assert connection.execute(
            text("SELECT name FROM source_definitions WHERE id = 'legacy-source'")
        ).scalar_one() == "Legacy"
        assert connection.execute(
            text("SELECT reason FROM source_probe_runs WHERE source_id = 'legacy-source'")
        ).scalar_one() == "legacy probe"

    command.downgrade(config, "20260711_0002")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "20260711_0002"
        )
        assert "operation_runs" not in inspect(connection).get_table_names()
        assert connection.execute(
            text("SELECT payload FROM raw_items WHERE external_id = '42'")
        ).scalar_one() == '{"legacy": true}'
