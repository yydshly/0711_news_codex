from __future__ import annotations

import json
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = (
    (re.compile(r"(?i)bearer\s+[\w.\-~=+/]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)(cookie\s*:\s*)[^\r\n]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(authorization\s*:\s*)[^\r\n]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)([?&](?:api[_-]?key|token|access_token)=)[^&#\s]+"), r"\1[REDACTED]"),
    (
        re.compile(r"(?i)\b(api[_-]?key|token|password)\s*[=:]\s*[^\s,&;]+"),
        lambda match: f"{match.group(1)}=[REDACTED]",
    ),
    (re.compile(r"(?i)(?:postgres(?:ql)?|mysql)://[^\s'\"]+"), "[REDACTED_DATABASE_URL]"),
)
_SENSITIVE_FIELD = re.compile(r"(?i)(authorization|cookie|api[_-]?key|token|password|secret)")


def redact(value: object, env: dict[str, str] | None = None) -> str:
    """Remove credentials before values are persisted to logs or events."""
    result = str(value)
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    for secret in (env or os.environ).values():
        if secret and len(secret) > 3:
            result = result.replace(secret, "[REDACTED]")
    return result


def redact_field(name: str, value: object) -> str:
    return "[REDACTED]" if _SENSITIVE_FIELD.search(name) else redact(value)


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "message": redact(record.getMessage()),
            "correlation_id": getattr(record, "correlation_id", "unbound"),
        }
        for key, value in record.__dict__.items():
            if (
                key not in logging.LogRecord("", 0, "", 0, "", (), None).__dict__
                and key != "message"
            ):
                payload[key] = redact_field(key, value)
        return json.dumps(payload, sort_keys=True, default=str)


def configure_logging(root: Path | str = ".") -> logging.Logger:
    """Configure the durable JSONL operational log once for this process."""
    path = Path(root) / ".local" / "logs" / "newsradar.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("newsradar")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(_JsonLineFormatter())
    logger.addHandler(handler)
    return logger
