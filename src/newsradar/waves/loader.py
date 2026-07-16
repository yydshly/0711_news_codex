from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from newsradar.sources.yaml_loader import load_source_tree

from .schema import WaveProfile


class _StrictLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_wave_profile(path: Path) -> WaveProfile:
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)
    if not isinstance(raw, Mapping):
        raise ValueError(f"Wave profile must contain a YAML mapping: {path}")
    profile = WaveProfile.model_validate(raw)
    existing_ids = {source.id for source in load_source_tree(Path("sources"))}
    unknown_ids = sorted(set(profile.source_ids) - existing_ids)
    if unknown_ids:
        raise ValueError(f"Unknown source id: {', '.join(unknown_ids)}")
    return profile
