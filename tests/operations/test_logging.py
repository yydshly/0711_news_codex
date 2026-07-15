from __future__ import annotations

import json

from newsradar.operations.logging import configure_logging, redact
from newsradar.operations.repository import OperationRepository
from newsradar.operations.schema import OperationType
from newsradar.operations.worker import Worker
from tests.operations.test_worker import session


def test_redact_removes_secrets_from_common_operational_strings() -> None:
    value = "Bearer abc Cookie: sid=xyz postgresql://user:pass@db/x?api_key=key"

    redacted = redact(value, env={"DATABASE_URL": "postgresql://user:pass@db/x"})

    assert "abc" not in redacted and "sid=xyz" not in redacted and "pass" not in redacted
    assert "key" not in redacted


def test_redact_removes_key_value_secrets_without_environment_values() -> None:
    redacted = redact(
        "api_key=api-secret token=token-secret password=hunter2 "
        "Authorization: Basic very-secret Cookie: sid=cookie-secret"
    )

    for secret in ("api-secret", "token-secret", "hunter2", "very-secret", "cookie-secret"):
        assert secret not in redacted


def test_jsonl_redacts_sensitive_extra_field_values(tmp_path: object) -> None:
    logger = configure_logging(tmp_path)  # type: ignore[arg-type]
    logger.info(
        "operation complete",
        extra={"correlation_id": "op-1", "password": "hunter2", "api_key": "abc"},
    )
    for handler in logger.handlers:
        handler.flush()

    payload = json.loads(
        (tmp_path / ".local" / "logs" / "newsradar.log").read_text().splitlines()[-1]  # type: ignore[operator]
    )
    assert payload["password"] == "[REDACTED]"
    assert payload["api_key"] == "[REDACTED]"


def test_jsonl_redacts_database_url_extra_field(tmp_path: object) -> None:
    logger = configure_logging(tmp_path)  # type: ignore[arg-type]
    logger.info(
        "operation complete",
        extra={"correlation_id": "op-1", "DATABASE_URL": "postgresql://user:database-secret@db/news"},
    )
    for handler in logger.handlers:
        handler.flush()

    payload = json.loads(
        (tmp_path / ".local" / "logs" / "newsradar.log").read_text().splitlines()[-1]  # type: ignore[operator]
    )
    assert payload["DATABASE_URL"] == "[REDACTED]"


def test_configure_logging_writes_jsonl_and_rotates(tmp_path: object) -> None:
    logger = configure_logging(tmp_path)  # type: ignore[arg-type]
    logger.info("finished", extra={"correlation_id": "op-1", "token": "Bearer abc"})
    for handler in logger.handlers:
        handler.maxBytes = 1
    logger.info("again", extra={"correlation_id": "op-1"})
    for handler in logger.handlers:
        handler.flush()

    lines = (tmp_path / ".local" / "logs" / "newsradar.log").read_text().splitlines()  # type: ignore[operator]
    assert json.loads(lines[-1])["correlation_id"] == "op-1"
    assert list((tmp_path / ".local" / "logs").glob("newsradar.log.*"))  # type: ignore[operator]


def test_worker_log_includes_operation_attempt_worker_and_source_ids(tmp_path: object) -> None:
    logger = configure_logging(tmp_path)  # type: ignore[arg-type]
    with session() as db:
        repository = OperationRepository(db)
        repository.enqueue(OperationType.FETCH, {"source_id": "source-1", "request_id": "req-1"})

        Worker(repository, "worker-1", logger=logger).run_once(lambda lease, checkpoint: None)

    for handler in logger.handlers:
        handler.flush()
    payload = json.loads(
        (tmp_path / ".local" / "logs" / "newsradar.log").read_text().splitlines()[-1]  # type: ignore[operator]
    )
    assert payload["operation_id"] == "1"
    assert payload["attempt_id"] == "1"
    assert payload["worker_id"] == "worker-1"
    assert payload["source_id"] == "source-1"
    assert payload["request_id"] == "req-1"
