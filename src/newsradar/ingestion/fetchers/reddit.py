from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

from newsradar.ingestion.schema import FetchOutcome, FetchResult, NormalizedRawItem
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, response_result
from .credentials import CredentialProvider


class RedditFetcher:
    def __init__(self, policy: HttpPolicy, credentials: CredentialProvider):
        self.policy, self.credentials = policy, credentials

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ) -> FetchResult:
        del source
        if urlsplit(str(method.url)).hostname != "oauth.reddit.com":
            raise ValueError("unaudited_reddit_target")
        try:
            client_id = self.credentials.require("REDDIT_CLIENT_ID")
            client_secret = self.credentials.require("REDDIT_CLIENT_SECRET")
        except (KeyError, ValueError):
            return FetchResult(
                outcome=FetchOutcome.BLOCKED,
                error_code="missing_credential",
                error_message="Reddit OAuth credentials are not configured",
            )
        token_response = await self.policy.client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": "NewsRadarIngestion/0.1"},
        )
        if token_response.status_code in {401, 403}:
            return response_result(
                token_response, outcome=FetchOutcome.BLOCKED, error_code="permission_required"
            )
        if token_response.status_code == 429:
            return response_result(
                token_response, outcome=FetchOutcome.FAILED, error_code="quota_exhausted"
            )
        token_response.raise_for_status()
        token = token_response.json().get("access_token")
        if not isinstance(token, str) or not token:
            return FetchResult(outcome=FetchOutcome.BLOCKED, error_code="permission_required")
        response = await self.policy.get(
            str(method.url),
            headers={"Authorization": f"Bearer {token}", "User-Agent": "NewsRadarIngestion/0.1"},
            params={
                **method.params,
                "limit": str(min(limit, 100)),
                **({"after": state.cursor} if state.cursor else {}),
            },
        )
        if response.status_code in {401, 403}:
            return response_result(
                response, outcome=FetchOutcome.BLOCKED, error_code="permission_required"
            )
        if response.status_code == 429:
            return response_result(
                response, outcome=FetchOutcome.FAILED, error_code="quota_exhausted"
            )
        response.raise_for_status()
        data = response.json().get("data", {})
        items = tuple(
            item
            for row in data.get("children", [])[:limit]
            if (item := self._item(row.get("data", {}))) is not None
        )
        return response_result(
            response, items=items, items_received=len(items), next_cursor=data.get("after")
        )

    @staticmethod
    def _item(row: object) -> NormalizedRawItem | None:
        if (
            not isinstance(row, dict)
            or not row.get("name")
            or not row.get("title")
            or not row.get("permalink")
        ):
            return None
        permalink = "https://www.reddit.com" + str(row["permalink"])
        deleted_author = row.get("author") in {None, "[deleted]"}
        body = row.get("selftext")
        content = None if body in {None, "", "[deleted]", "[removed]"} else str(body)
        safe_payload = {
            key: value
            for key, value in row.items()
            if key not in {"access_token", "token", "selftext", "author"}
        }
        return NormalizedRawItem(
            external_id=str(row["name"]),
            title=str(row["title"]),
            canonical_url=permalink,
            authors=() if deleted_author else (str(row["author"]),),
            content=content,
            published_at=datetime.fromtimestamp(float(row["created_utc"]), UTC)
            if row.get("created_utc")
            else None,
            engagement={
                "score": int(row.get("score", 0)),
                "comments": int(row.get("num_comments", 0)),
            },
            item_kind="community_post",
            discussion_url=permalink,
            raw_payload=safe_payload,
        )
