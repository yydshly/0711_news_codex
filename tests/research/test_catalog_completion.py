from __future__ import annotations

from pathlib import Path

import yaml

from newsradar.research.audit import audit_source_catalog
from newsradar.sources.yaml_loader import load_source_tree

SOURCE_ROOT = Path("sources")


def _source_yaml_documents() -> list[dict[str, object]]:
    return [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(SOURCE_ROOT.rglob("*.yaml"))
    ]


def test_every_catalog_target_has_explicit_research_status() -> None:
    documents = _source_yaml_documents()

    assert documents
    assert all("research" in document for document in documents)
    assert all(
        isinstance(document["research"], dict) and "status" in document["research"]
        for document in documents
    )


def test_placeholder_targets_do_not_count_as_real_coverage() -> None:
    report = audit_source_catalog((), tuple(load_source_tree(SOURCE_ROOT)))

    assert report.target_count == sum(
        count
        for status, count in report.status_counts.items()
        if status in {"verified", "needs_research"}
    )
