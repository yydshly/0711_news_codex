from __future__ import annotations

MIXED_WAVE_GROUPS: dict[str, tuple[str, ...]] = {
    "reddit": ("reddit-localllama", "reddit-machinelearning", "reddit-artificial"),
    "youtube": (
        "openai-youtube",
        "anthropic-youtube",
        "google-deepmind-youtube",
        "nvidia-developer-youtube",
        "huggingface-youtube",
        "no-priors-youtube",
        "latent-space-youtube",
        "cognitive-revolution-youtube",
    ),
    "bluesky": (
        "anthropic-bluesky",
        "huggingface-bluesky",
        "simon-willison-bluesky",
        "techcrunch-bluesky",
        "the-verge-bluesky",
        "mit-tech-review-bluesky",
    ),
    "mastodon": (
        "mastodon-ai-tag",
        "mastodon-machinelearning-tag",
        "mastodon-llm-tag",
        "mastodon-artificialintelligence-tag",
    ),
    "hackernews": ("hackernews-top", "hackernews-new", "hackernews-best"),
    "techmeme": ("techmeme-feed",),
    "gdelt": ("gdelt-ai",),
    "google_news": (
        "google-news-ai",
        "google-news-research",
        "google-news-chips-compute",
        "google-news-business",
        "google-news-policy-safety",
    ),
    "professional_media": (
        "universe-bbc-1",
        "universe-ars-technica-1",
        "universe-cnbc-1",
        "universe-techcrunch-1",
        "universe-the-verge-1",
        "universe-wired-1",
        "universe-guardian-1",
        "universe-mit-tech-review-1",
        "universe-venturebeat-1",
        "universe-reuters-2",
        "universe-ap-2",
        "universe-bloomberg-2",
        "universe-financial-times-2",
        "universe-wsj-2",
    ),
}

MIXED_WAVE_SOURCE_IDS = frozenset(
    source_id for source_ids in MIXED_WAVE_GROUPS.values() for source_id in source_ids
)


def is_mixed_wave_source(source_id: str) -> bool:
    return source_id in MIXED_WAVE_SOURCE_IDS
