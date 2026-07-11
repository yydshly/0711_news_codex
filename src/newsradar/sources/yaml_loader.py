from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .schema import SourceDefinition

SENSITIVE_FRAGMENTS = ("api_key", "apikey", "secret", "password", "cookie", "token")


def _reject_plaintext_credentials(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(fragment in normalized for fragment in SENSITIVE_FRAGMENTS):
                raise ValueError(f"Found credential-like key at {path}.{key}")
            _reject_plaintext_credentials(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _reject_plaintext_credentials(child, f"{path}[{index}]")


def load_source_file(path: Path) -> SourceDefinition:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Source file must contain a YAML mapping: {path}")
    _reject_plaintext_credentials(raw)
    return SourceDefinition.model_validate(raw)


def load_source_tree(root: Path) -> list[SourceDefinition]:
    sources: list[SourceDefinition] = []
    seen: set[str] = set()
    for path in sorted(root.rglob("*.yaml")):
        source = load_source_file(path)
        if source.id in seen:
            raise ValueError(f"Duplicate source id: {source.id}")
        seen.add(source.id)
        sources.append(source)
    return sources
