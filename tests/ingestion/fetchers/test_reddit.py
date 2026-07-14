import httpx
import pytest
import respx

from newsradar.ingestion.fetchers.base import FetchState, HttpPolicy
from newsradar.ingestion.fetchers.reddit import RedditFetcher
from newsradar.ingestion.schema import FetchOutcome
from newsradar.sources.schema import SourceDefinition

from ...test_source_schema import valid_source


class Credentials:
    def __init__(self, values: dict[str, str]):
        self.values = values

    def require(self, name: str) -> str:
        return self.values[name]


@pytest.mark.asyncio
@respx.mock
async def test_reddit_uses_official_oauth_and_never_keeps_token_in_payload() -> None:
    data = valid_source()
    data["access_methods"][0].update(
        {"kind": "rest_api", "url": "https://oauth.reddit.com/r/LocalLLaMA/new"}
    )
    source = SourceDefinition.model_validate(data)
    token = respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "secret-token"})
    )
    listing = respx.get("https://oauth.reddit.com/r/LocalLLaMA/new").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "after": "t3_next",
                    "children": [
                        {
                            "data": {
                                "name": "t3_1",
                                "id": "1",
                                "title": "Model release",
                                "permalink": "/r/LocalLLaMA/comments/1/model/",
                                "selftext": "details",
                                "author": "alice",
                                "created_utc": 1,
                                "score": 5,
                                "num_comments": 2,
                            }
                        }
                    ],
                }
            },
        )
    )
    async with httpx.AsyncClient() as client:
        result = await RedditFetcher(
            HttpPolicy(client),
            Credentials({"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "secret"}),
        ).fetch(source, source.access_methods[0], FetchState(), 5)
    assert result.outcome is FetchOutcome.SUCCEEDED
    assert result.items[0].external_id == "t3_1"
    assert result.items[0].engagement == {"score": 5, "comments": 2}
    assert (
        token.called and listing.calls[0].request.headers["authorization"] == "Bearer secret-token"
    )
    assert "secret-token" not in str(result.items[0].raw_payload)


@pytest.mark.asyncio
async def test_reddit_missing_credentials_is_blocked() -> None:
    data = valid_source()
    data["access_methods"][0].update(
        {"kind": "rest_api", "url": "https://oauth.reddit.com/r/LocalLLaMA/new"}
    )
    source = SourceDefinition.model_validate(data)
    async with httpx.AsyncClient() as client:
        result = await RedditFetcher(HttpPolicy(client), Credentials({})).fetch(
            source, source.access_methods[0], FetchState(), 5
        )
    assert result.outcome is FetchOutcome.BLOCKED and result.error_code == "missing_credential"


def test_reddit_does_not_retain_deleted_author_or_body() -> None:
    item = RedditFetcher._item(
        {
            "name": "t3_1",
            "title": "Deleted post",
            "permalink": "/r/test/comments/1/deleted/",
            "author": "[deleted]",
            "selftext": "[deleted]",
            "created_utc": 1,
            "score": 0,
            "num_comments": 0,
        }
    )

    assert item is not None
    assert item.authors == ()
    assert item.content is None
    assert "[deleted]" not in str(item.raw_payload)


def test_reddit_does_not_retain_removed_body() -> None:
    item = RedditFetcher._item(
        {
            "name": "t3_2",
            "title": "Removed post",
            "permalink": "/r/test/comments/2/removed/",
            "author": "alice",
            "selftext": "[removed]",
            "created_utc": 1,
            "score": 0,
            "num_comments": 0,
        }
    )

    assert item is not None
    assert item.authors == ("alice",)
    assert item.content is None
    assert "[removed]" not in str(item.raw_payload)
