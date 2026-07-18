from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_postgresql_retention_guard_compares_generation_summary_as_exact_json_text() -> None:
    migration_path = (
        Path(__file__).parents[2]
        / "migrations"
        / "versions"
        / "20260718_0030_fix_daily_report_retention_json_guard.py"
    )
    spec = spec_from_file_location("daily_report_retention_json_guard", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements: list[str] = []
    migration.op = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=lambda statement: statements.append(str(statement)),
    )

    migration.upgrade()

    function_sql = "\n".join(statements)
    normalized_sql = " ".join(function_sql.split())
    assert (
        "NEW.generation_summary::text IS DISTINCT FROM "
        "OLD.generation_summary::text"
    ) in normalized_sql
    assert "NEW.generation_summary, NEW.generated_at" not in function_sql


def test_postgresql_retention_guard_rejects_downgrade_to_unsafe_json_comparison() -> None:
    migration_path = (
        Path(__file__).parents[2]
        / "migrations"
        / "versions"
        / "20260718_0030_fix_daily_report_retention_json_guard.py"
    )
    spec = spec_from_file_location("daily_report_retention_json_guard", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )

    with pytest.raises(RuntimeError, match="cannot safely downgrade"):
        migration.downgrade()
