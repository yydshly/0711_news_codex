from pathlib import Path

from newsradar.sources.yaml_loader import load_source_tree

CREDENTIAL_SOURCE_IDS = {
    "openai-youtube",
    "anthropic-sdk-releases",
    "cuda-python-releases",
    "deepseek-v3-releases",
    "gemini-cli-releases",
    "mistral-common-releases",
    "openai-python-releases",
    "transformers-releases",
}


def test_credential_sources_are_explicitly_approved_for_ingestion() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}

    enabled = {
        source_id
        for source_id in CREDENTIAL_SOURCE_IDS
        if sources[source_id].ingestion.enabled
    }

    assert enabled == CREDENTIAL_SOURCE_IDS
    assert all(
        sources[source_id].ingestion.approved_at is not None
        for source_id in CREDENTIAL_SOURCE_IDS
    )


def test_credential_sources_keep_official_authentication_requirements() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    youtube = sources["openai-youtube"]
    github_sources = [
        sources[source_id] for source_id in CREDENTIAL_SOURCE_IDS - {"openai-youtube"}
    ]

    assert youtube.availability.value == "requires_credentials"
    youtube_api = next(
        method for method in youtube.access_methods if method.kind.value == "rest_api"
    )
    assert youtube_api.auth_envs == ("YOUTUBE_API_KEY",)
    assert all(source.availability.value == "requires_credentials" for source in github_sources)
    assert all(
        source.access_methods[0].auth_envs == ("GITHUB_TOKEN",)
        for source in github_sources
    )
