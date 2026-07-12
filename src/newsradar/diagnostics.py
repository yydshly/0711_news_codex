"""Bounded, scrubbed diagnostic snapshots for local operators."""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from newsradar.db.models import (
    OperationEventRecord,
    OperationRunRecord,
    ProviderDefinitionRecord,
    SourceDefinitionRecord,
    WorkerRecord,
)
from newsradar.operations.logging import redact, redact_field

_CONFIGURED_VARIABLES = (
    "DATABASE_URL",
    "MINIMAX_API_KEY",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "YOUTUBE_API_KEY",
)


@dataclass(frozen=True, slots=True)
class DiagnosticSnapshot:
    created_at: datetime
    application_version: str
    migration_revision: str | None
    database_status: str
    workers: list[dict[str, Any]]
    queue_depth: int
    current_operations: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]
    definition_hashes: dict[str, list[str]]
    configured_variables: dict[str, bool]


def create_diagnostic_bundle(destination: Path, snapshot: DiagnosticSnapshot) -> Path:
    """Write a small ZIP containing operational facts, never environment values."""
    destination.mkdir(parents=True, exist_ok=True)
    stamp = snapshot.created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive = destination / f"newsradar-diagnostics-{stamp}.zip"
    payload = _scrub(asdict(snapshot))
    manifest = {
        "format": 1,
        "created_at": snapshot.created_at.astimezone(UTC).isoformat(),
        "entries": ["snapshot.json"],
        "scrubbed": True,
    }
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "manifest.json", json.dumps(manifest, sort_keys=True, indent=2, default=str)
        )
        bundle.writestr("snapshot.json", json.dumps(payload, sort_keys=True, indent=2, default=str))
    return archive


def collect_diagnostic_snapshot(
    session: Session, *, environment: dict[str, str] | None = None
) -> DiagnosticSnapshot:
    """Collect bounded DB projections; credentials are represented only as booleans."""
    workers = [
        {
            "worker_id": row.worker_id,
            "status": row.status,
            "last_heartbeat_at": row.last_heartbeat_at,
            "current_operation_run_id": row.current_operation_run_id,
        }
        for row in session.scalars(select(WorkerRecord).order_by(WorkerRecord.worker_id).limit(50))
    ]
    operations = [
        {
            "id": row.id,
            "operation_type": row.operation_type,
            "status": row.status,
            "error_code": row.error_code,
        }
        for row in session.scalars(
            select(OperationRunRecord)
            .where(OperationRunRecord.status.in_(("queued", "running")))
            .order_by(OperationRunRecord.created_at.desc())
            .limit(50)
        )
    ]
    events = [
        {
            "level": row.level,
            "phase": row.phase,
            "message": row.message,
            "details": row.details,
            "error_code": row.error_code,
            "created_at": row.created_at,
        }
        for row in session.scalars(
            select(OperationEventRecord).order_by(OperationEventRecord.id.desc()).limit(100)
        )
    ]
    env = environment if environment is not None else os.environ
    return DiagnosticSnapshot(
        created_at=datetime.now(UTC),
        application_version="0.1.0",
        migration_revision=_migration_revision(session),
        database_status="online",
        workers=workers,
        queue_depth=session.scalar(
            select(func.count())
            .select_from(OperationRunRecord)
            .where(OperationRunRecord.status == "queued")
        ) or 0,
        current_operations=operations,
        recent_events=events,
        definition_hashes={
            "sources": list(session.scalars(select(SourceDefinitionRecord.definition_hash))),
            "providers": list(session.scalars(select(ProviderDefinitionRecord.definition_hash))),
        },
        configured_variables={name: bool(env.get(name)) for name in _CONFIGURED_VARIABLES},
    )


def _migration_revision(session: Session) -> str | None:
    try:
        return session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:
        return None


def _scrub(value: Any, key: str = "") -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        return {name: _scrub(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, key) for item in value]
    if key:
        return redact_field(key, value)
    return redact(value)
