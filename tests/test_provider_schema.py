from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from newsradar.providers.schema import ProviderDefinition
from newsradar.providers.yaml_loader import load_provider_file, load_provider_tree


def valid_provider() -> dict:
    return {
        "id": "bluesky",
        "name": "Bluesky",
        "category": "social_community",
        "homepage": "https://bsky.app/",
        "docs_url": "https://docs.bsky.app/",
        "terms_url": "https://bsky.social/about/support/tos",
        "auth_mode": "none",
        "cost_tier": "free",
        "availability": "ready",
        "capabilities": ["account", "keyword", "engagement"],
        "required_env": [],
        "reviewed_at": "2026-07-11",
        "evidence": ["https://docs.bsky.app/docs/api/app-bsky-feed-search-posts"],
        "unlock_requirements": [],
    }


def test_provider_definition_is_strict_and_audited() -> None:
    provider = ProviderDefinition.model_validate(valid_provider())

    assert provider.reviewed_at == date(2026, 7, 11)
    assert provider.capabilities == ["account", "keyword", "engagement"]


def test_provider_rejects_unknown_fields() -> None:
    data = valid_provider()
    data["cookie"] = "value"

    with pytest.raises(ValidationError):
        ProviderDefinition.model_validate(data)


def test_provider_rejects_non_https_evidence() -> None:
    data = valid_provider()
    data["evidence"] = ["http://docs.example.test/api"]

    with pytest.raises(ValidationError):
        ProviderDefinition.model_validate(data)


@pytest.mark.parametrize("field", ["homepage", "docs_url", "terms_url", "evidence"])
def test_provider_rejects_embedded_url_credentials(field: str) -> None:
    data = valid_provider()
    if field == "evidence":
        data[field] = ["https://user:secret@docs.example.test/api"]
    else:
        data[field] = "https://user:secret@docs.example.test/"

    with pytest.raises(ValidationError):
        ProviderDefinition.model_validate(data)


def test_provider_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    for filename in ("one.yaml", "two.yaml"):
        (tmp_path / filename).write_text(yaml.safe_dump(valid_provider()), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate provider id"):
        load_provider_tree(tmp_path)


def test_provider_loader_rejects_plaintext_credentials(tmp_path: Path) -> None:
    data = valid_provider()
    data["access_token"] = "secret"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ValueError, match="credential-like key"):
        load_provider_file(path)
