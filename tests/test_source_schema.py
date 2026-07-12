from pathlib import Path

import pytest
from pydantic import ValidationError

from newsradar.sources.schema import SourceDefinition
from newsradar.sources.yaml_loader import load_source_file, load_source_tree


def valid_source() -> dict:
    return {
        "id": "anthropic-news",
        "name": "Anthropic News",
        "status": "candidate",
        "nature": "first_party",
        "roles": ["discovery", "evidence"],
        "language": "en",
        "topics": ["foundation_models", "agents"],
        "authority_score": 5,
        "poll_interval_minutes": 60,
        "access_methods": [
            {
                "kind": "rss",
                "url": "https://www.anthropic.com/news/rss.xml",
                "priority": 1,
            }
        ],
        "expected_fields": ["title", "canonical_url", "published_at", "summary"],
        "risk": {
            "terms": 1,
            "authentication": 0,
            "stability": 2,
            "data_quality": 1,
            "operating_cost": 0,
        },
    }


def test_source_definition_accepts_audited_https_source() -> None:
    source = SourceDefinition.model_validate(valid_source())
    assert source.id == "anthropic-news"
    assert source.total_risk == 4
    assert source.provider_id == "independent"
    assert source.target_type.value == "publisher_feed"
    assert source.availability.value == "ready"
    assert source.coverage_mode.value == "direct"


def test_ingestion_defaults_disabled_for_legacy_source_definition() -> None:
    source = SourceDefinition.model_validate(valid_source())

    assert source.ingestion.enabled is False
    assert source.ingestion.approved_at is None
    assert source.ingestion.max_items_per_run == 100


def test_ingestion_rejects_unknown_and_secret_fields() -> None:
    data = valid_source()
    data["ingestion"] = {"enabled": True, "api_key": "secret"}

    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(data)


@pytest.mark.parametrize(
    "url",
    ["http://example.com/feed", "https://example.invalid/feed", "", "not-a-url"],
)
def test_source_definition_rejects_unreviewed_urls(url: str) -> None:
    data = valid_source()
    data["access_methods"][0]["url"] = url
    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(data)


def test_source_definition_rejects_embedded_credentials() -> None:
    data = valid_source()
    data["access_methods"][0]["url"] = "https://user:secret@example.com/feed"
    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(data)


def test_source_definition_rejects_unknown_fields() -> None:
    data = valid_source()
    data["cookie"] = "secret"
    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(data)


def test_load_source_tree_rejects_duplicate_ids(tmp_path: Path) -> None:
    import yaml

    for name in ("one.yaml", "two.yaml"):
        (tmp_path / name).write_text(yaml.safe_dump(valid_source()), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate source id"):
        load_source_tree(tmp_path)


def test_load_source_file_rejects_plaintext_secrets(tmp_path: Path) -> None:
    import yaml

    data = valid_source()
    data["api_key"] = "sk-secret"
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ValueError, match="credential-like key"):
        load_source_file(path)


def test_social_target_cannot_be_evidence_only() -> None:
    data = valid_source()
    data.update(
        {
            "nature": "social",
            "roles": ["evidence"],
            "provider_id": "x",
            "target_type": "account",
            "availability": "requires_payment",
            "coverage_mode": "catalog_only",
            "official_identity_url": "https://x.com/openai",
            "reviewed_at": "2026-07-11",
            "unlock_requirements": ["Purchase X API credits"],
        }
    )

    with pytest.raises(ValidationError, match="Social targets"):
        SourceDefinition.model_validate(data)
