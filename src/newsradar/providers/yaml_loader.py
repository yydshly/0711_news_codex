from __future__ import annotations

from pathlib import Path

import yaml

from newsradar.sources.yaml_loader import _reject_plaintext_credentials

from .schema import ProviderDefinition


def load_provider_file(path: Path) -> ProviderDefinition:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Provider file must contain a YAML mapping: {path}")
    _reject_plaintext_credentials(raw)
    return ProviderDefinition.model_validate(raw)


def load_provider_tree(root: Path) -> list[ProviderDefinition]:
    providers: list[ProviderDefinition] = []
    seen: set[str] = set()
    for path in sorted(root.rglob("*.yaml")):
        provider = load_provider_file(path)
        if provider.id in seen:
            raise ValueError(f"Duplicate provider id: {provider.id}")
        seen.add(provider.id)
        providers.append(provider)
    return providers
