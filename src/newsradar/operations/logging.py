from __future__ import annotations

import ast
import json
import logging
import os
import re
from collections.abc import Mapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = (
    (re.compile(r"(?i)bearer\s+[\w.\-~=+/]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)(cookie\s*:\s*)[^\r\n]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(authorization\s*:\s*)[^\r\n]+"), r"\1[REDACTED]"),
    (
        re.compile(r"(?i)([?&](?:key|api[_-]?key|token|access_token)=)[^&#\s]+"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(?i)\b(api[_-]?key|token|password)\s*[=:]\s*[^\s,&;]+"),
        lambda match: f"{match.group(1)}=[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b((?:[a-z][a-z0-9_]*_)?(?:api[_-]?key|token|secret)|database_url)"
            r"\s*[=:]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,&;]+)"
        ),
        lambda match: f"{match.group(1)}=[REDACTED]",
    ),
    (re.compile(r"(?i)(?:postgres(?:ql)?|mysql)://[^\s'\"]+"), "[REDACTED_DATABASE_URL]"),
)
_SENSITIVE_FIELD = re.compile(
    r"(?i)(authorization|cookie|api[_-]?key|token|password|secret|database[_-]?url)"
)
_QUOTED_SENSITIVE_PAIR = re.compile(
    r"(?ix)([\"'](?:authorization|cookie|password|database[_-]?url|"
    r"(?:[a-z][a-z0-9_]*_)?(?:api[_-]?key|token|secret))"
    r"[\"']\s*:\s*)(?:\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|[^,}\]\s]+)"
)
_UNPARSED = object()


def redact_value(value: object, env: Mapping[str, str] | None = None) -> object:
    """Recursively remove secret-bearing keys before structured values are serialized.

    Callers that need text should use :func:`redact`; keeping structure here prevents a
    dict/list supplied as a logging ``extra`` field from bypassing redaction via ``str``.
    """
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if _SENSITIVE_FIELD.search(str(key))
            else redact_value(item, env)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, env) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item, env) for item in value)
    if isinstance(value, str):
        return _redact_text(value, env)
    return _redact_text(str(value), env)


def _redact_text(value: str, env: Mapping[str, str] | None) -> str:
    parsed = _parse_structured_text(value)
    if parsed is not _UNPARSED:
        cleaned = redact_value(parsed, env)
        return json.dumps(cleaned, sort_keys=True, default=str)

    result = value
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    result = _QUOTED_SENSITIVE_PAIR.sub(r"\1[REDACTED]", result)
    for secret in (env if env is not None else os.environ).values():
        if secret and len(secret) > 3:
            result = result.replace(secret, "[REDACTED]")
    return result


def _parse_structured_text(value: str) -> object:
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{(":
        return _UNPARSED
    try:
        return json.loads(stripped)
    except (TypeError, ValueError):
        try:
            return ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            return _UNPARSED


def redact(value: object, env: Mapping[str, str] | None = None) -> str:
    """Remove credentials before values are persisted to logs or events."""
    cleaned = redact_value(value, env)
    if isinstance(cleaned, (dict, list, tuple)):
        return json.dumps(cleaned, sort_keys=True, default=str)
    return str(cleaned)


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
                payload[key] = "[REDACTED]" if _SENSITIVE_FIELD.search(key) else redact_value(value)
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
