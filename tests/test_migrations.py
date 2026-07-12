import subprocess


def test_full_offline_migration_creates_provider_tables_once() -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head", "--sql"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.count("CREATE TABLE source_providers") == 1
    assert result.stdout.count("ADD COLUMN provider_id") == 1
