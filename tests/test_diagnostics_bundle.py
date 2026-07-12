from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from newsradar.db.models import Base
from newsradar.diagnostics import (
    DiagnosticSnapshot,
    collect_diagnostic_snapshot,
    create_diagnostic_bundle,
)


def test_diagnostic_bundle_contains_safe_runtime_evidence(tmp_path) -> None:
    secret = "super-secret-value"
    snapshot = DiagnosticSnapshot(
        created_at=datetime(2026, 7, 12, 10, 30, tzinfo=UTC),
        application_version="0.1.0",
        migration_revision="20260712_0005",
        database_status="online",
        workers=[{"worker_id": "worker-a", "status": "online"}],
        queue_depth=2,
        current_operations=[{"id": 7, "status": "running"}],
        recent_events=[
            {"message": f"Authorization: Bearer {secret}", "details": {"token": secret}}
        ],
        definition_hashes={"sources": ["source-hash"], "providers": ["provider-hash"]},
        configured_variables={"DATABASE_URL": True, "MINIMAX_API_KEY": False},
    )

    archive = create_diagnostic_bundle(tmp_path, snapshot)

    assert archive.exists()
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {"manifest.json", "snapshot.json"}
        payload = json.loads(bundle.read("snapshot.json"))
    assert payload["migration_revision"] == "20260712_0005"
    assert payload["configured_variables"] == {"DATABASE_URL": True, "MINIMAX_API_KEY": False}
    assert payload["recent_events"][0]["details"]["token"] == "[REDACTED]"
    assert secret not in archive.read_bytes().decode("latin-1")


def test_diagnostic_snapshot_exposes_configuration_as_booleans_only() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        session.execute(text("INSERT INTO alembic_version VALUES ('20260712_0005')"))
        snapshot = collect_diagnostic_snapshot(
            session,
            environment={"DATABASE_URL": "postgresql://secret", "MINIMAX_API_KEY": "key-value"},
        )

        assert snapshot.database_status == "online"
        assert snapshot.migration_revision == "20260712_0005"
        assert snapshot.configured_variables["DATABASE_URL"] is True
        assert snapshot.configured_variables["MINIMAX_API_KEY"] is True
