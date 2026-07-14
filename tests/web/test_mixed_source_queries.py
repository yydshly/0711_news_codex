from datetime import UTC, datetime, timedelta

from newsradar.db.models import (
    FetchRunRecord,
    RawItemRecord,
    SourceAccessMethodRecord,
    SourceDefinitionRecord,
)
from newsradar.web.mixed_source_queries import MixedSourceQueryService

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def _source(
    source_id: str,
    *,
    coverage: str = "direct",
    availability: str = "ready",
    status: str = "candidate",
) -> SourceDefinitionRecord:
    return SourceDefinitionRecord(
        id=source_id,
        name=source_id,
        provider_id=source_id.split("-")[0],
        target_type="search_query",
        availability=availability,
        coverage_mode=coverage,
        status=status,
        nature="community",
        language="en",
        roles=["discovery"],
        topics=["ai"],
        authority_score=2,
        poll_interval_minutes=30,
        expected_fields=["title", "canonical_url"],
        definition_hash=f"{source_id}-hash",
    )


def _seed_mixed_sources(db_session) -> None:
    sources = (
        _source("openai-youtube", availability="requires_credentials"),
        _source("universe-reuters-2", coverage="indirect"),
        _source("reddit-localllama", availability="requires_credentials"),
        _source("gdelt-ai", status="degraded"),
        _source("hackernews-top"),
        _source("hackernews-new"),
    )
    db_session.add_all(sources)
    db_session.flush()
    for source in sources:
        db_session.add(
            SourceAccessMethodRecord(
                source_id=source.id,
                kind="rss",
                url=f"https://example.test/{source.id}",
                priority=1,
                requires_manual_approval=False,
                auth_envs=[],
                headers={},
                params={},
            )
        )
    for offset, outcome in enumerate(("succeeded", "no_change", "succeeded")):
        db_session.add(
            FetchRunRecord(
                source_id="openai-youtube",
                started_at=NOW - timedelta(hours=offset, minutes=1),
                finished_at=NOW - timedelta(hours=offset),
                outcome=outcome,
                item_count=1,
            )
        )
    db_session.add_all(
        [
            FetchRunRecord(
                source_id="universe-reuters-2",
                started_at=NOW - timedelta(minutes=2),
                finished_at=NOW - timedelta(minutes=1),
                outcome="succeeded",
                item_count=2,
            ),
            FetchRunRecord(
                source_id="gdelt-ai",
                started_at=NOW - timedelta(minutes=2),
                finished_at=NOW - timedelta(minutes=1),
                outcome="partial",
                error_code="schema_drift",
            ),
            FetchRunRecord(
                source_id="hackernews-top",
                started_at=NOW - timedelta(minutes=2),
                finished_at=NOW - timedelta(minutes=1),
                outcome="failed",
                error_code="timeout",
            ),
        ]
    )
    db_session.add_all(
        [
            RawItemRecord(
                source_id="openai-youtube",
                external_id="video-1",
                canonical_url="https://youtube.test/watch?v=video-1",
                payload={},
                title="Video",
                published_at=NOW,
                fetched_at=NOW,
            ),
            RawItemRecord(
                source_id="universe-reuters-2",
                external_id="reuters-1",
                canonical_url="https://reuters.test/article/reuters-1",
                payload={},
                title="Reuters item",
                published_at=NOW,
                fetched_at=NOW,
            ),
        ]
    )
    db_session.commit()


def test_mixed_wave_query_distinguishes_real_content_states(db_session) -> None:
    _seed_mixed_sources(db_session)

    dashboard = MixedSourceQueryService(db_session).build()
    rows = {row.source_id: row for row in dashboard.targets}

    assert rows["openai-youtube"].state == "direct_ready"
    assert rows["universe-reuters-2"].state == "indirect_ready"
    assert rows["reddit-localllama"].state == "blocked"
    assert rows["gdelt-ai"].state == "degraded"
    assert rows["hackernews-top"].state == "failed"
    assert rows["hackernews-new"].state == "not_run"
    assert rows["openai-youtube"].three_run_outcomes == (
        "succeeded",
        "no_change",
        "succeeded",
    )
    assert rows["openai-youtube"].three_run_stable is True
    assert rows["openai-youtube"].raw_item_count == 1
    assert rows["openai-youtube"].latest_content_at == NOW


def test_mixed_wave_summary_and_groups_use_the_same_45_member_scope(db_session) -> None:
    _seed_mixed_sources(db_session)

    dashboard = MixedSourceQueryService(db_session).build()

    assert dashboard.summary.catalog_target_count == 45
    assert dashboard.summary.synced_target_count == 6
    assert dashboard.summary.direct_ready_count == 1
    assert dashboard.summary.indirect_ready_count == 1
    assert dashboard.summary.blocked_count == 1
    assert dashboard.summary.degraded_count == 1
    assert dashboard.summary.failed_count == 1
    assert dashboard.summary.empty_count == 0
    assert dashboard.summary.not_run_count == 1
    assert dashboard.summary.three_run_stable_count == 1
    assert {group.key for group in dashboard.groups} == {
        "reddit",
        "youtube",
        "bluesky",
        "mastodon",
        "hackernews",
        "techmeme",
        "gdelt",
        "google_news",
        "professional_media",
    }


def test_mixed_wave_query_never_exposes_method_credentials(db_session) -> None:
    _seed_mixed_sources(db_session)
    method = db_session.query(SourceAccessMethodRecord).filter_by(source_id="openai-youtube").one()
    method.headers = {"Authorization": "Bearer secret", "Cookie": "session=secret"}
    method.auth_envs = ["YOUTUBE_API_KEY"]
    db_session.commit()

    serialized = repr(MixedSourceQueryService(db_session).build())

    assert "Bearer secret" not in serialized
    assert "session=secret" not in serialized
    assert "YOUTUBE_API_KEY" not in serialized


def test_successful_empty_feed_is_not_claimed_as_content_coverage(db_session) -> None:
    source = _source("anthropic-bluesky")
    db_session.add(source)
    db_session.flush()
    db_session.add(
        SourceAccessMethodRecord(
            source_id=source.id,
            kind="public_api",
            url="https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
            priority=1,
            requires_manual_approval=False,
            auth_envs=[],
            headers={},
            params={},
        )
    )
    for offset in range(3):
        db_session.add(
            FetchRunRecord(
                source_id=source.id,
                started_at=NOW - timedelta(hours=offset, minutes=1),
                finished_at=NOW - timedelta(hours=offset),
                outcome="succeeded",
                items_received=0,
                item_count=0,
            )
        )
    db_session.commit()

    dashboard = MixedSourceQueryService(db_session).build()
    row = next(target for target in dashboard.targets if target.source_id == source.id)

    assert row.state == "empty"
    assert row.state_label == "入口可用，暂无样本"
    assert "尚无内容样本" in row.conclusion_zh
    assert dashboard.summary.empty_count == 1
    assert dashboard.summary.direct_ready_count == 0


def test_mixed_wave_query_returns_only_the_latest_five_samples(db_session) -> None:
    source = _source("techmeme-feed")
    db_session.add(source)
    db_session.flush()
    db_session.add(
        SourceAccessMethodRecord(
            source_id=source.id,
            kind="rss",
            url="https://www.techmeme.com/feed.xml",
            priority=1,
            requires_manual_approval=False,
            auth_envs=[],
            headers={},
            params={},
        )
    )
    for index in range(6):
        db_session.add(
            RawItemRecord(
                source_id=source.id,
                external_id=f"item-{index}",
                canonical_url=f"https://example.test/{index}",
                payload={},
                title=f"Sample {index}",
                published_at=NOW - timedelta(minutes=index),
                fetched_at=NOW,
            )
        )
    db_session.commit()

    dashboard = MixedSourceQueryService(db_session).build()
    row = next(target for target in dashboard.targets if target.source_id == source.id)

    assert [sample.title for sample in row.recent_items] == [
        "Sample 0",
        "Sample 1",
        "Sample 2",
        "Sample 3",
        "Sample 4",
    ]
