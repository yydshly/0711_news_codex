from __future__ import annotations

import json

from newsradar.operations.logging import configure_logging, redact


def test_redact_removes_secrets_from_common_operational_strings() -> None:
    value = "Bearer abc Cookie: sid=xyz postgresql://user:pass@db/x?api_key=key"

    redacted = redact(value, env={"DATABASE_URL": "postgresql://user:pass@db/x"})

    assert "abc" not in redacted and "sid=xyz" not in redacted and "pass" not in redacted
    assert "key" not in redacted


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
