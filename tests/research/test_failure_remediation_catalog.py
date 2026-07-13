from pathlib import Path

from newsradar.sources.yaml_loader import load_source_tree

FAILED_BASELINE_IDS = frozenset(
    """
    anthropic-sdk-releases arxiv-cs-ai arxiv-cs-dc arxiv-cs-se bluesky-bsky
    deepmind-blog deepseek-v3-releases gdelt-ai google-ai-blog google-news-ai
    hackernews-best hackernews-new hackernews-top huggingface-blog mastodon-mastodon
    mistral-common-releases nvidia-developer-blog openai-news openai-python-releases
    openai-youtube qwen3-releases techmeme-feed universe-ai-snake-oil-1
    universe-ars-technica-1 universe-latent-space-1 universe-techcrunch-1
    universe-the-verge-1
    """.split()
)


def test_every_failed_baseline_source_has_an_audited_acquisition_candidate() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}

    assert FAILED_BASELINE_IDS <= sources.keys()
    for source_id in FAILED_BASELINE_IDS:
        candidates = sources[source_id].research.candidates
        assert candidates, f"{source_id} has no acquisition candidate"
        assert all(candidate.evidence for candidate in candidates)
        assert all(
            candidate.authentication.value != "login_cookie"
            or candidate.decision.value == "rejected"
            for candidate in candidates
        )
