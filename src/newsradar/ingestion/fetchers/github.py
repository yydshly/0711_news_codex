from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

from newsradar.ingestion.schema import FetchOutcome, NormalizedRawItem
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, response_result


class GitHubFetcher:
    def __init__(self, policy: HttpPolicy):
        self.policy = policy

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ):
        request_url = state.cursor or str(method.url)
        parsed = urlsplit(request_url)
        if (
            parsed.hostname != "api.github.com"
            or not parsed.path.startswith("/repos/")
            or not parsed.path.endswith("/releases")
        ):
            raise ValueError("unaudited_github_repository")
        headers = {"Accept": "application/vnd.github+json", **method.headers}
        if state.etag:
            headers["If-None-Match"] = state.etag
        params = None if state.cursor else {**method.params, "per_page": min(limit, 100)}
        response = await self.policy.get(request_url, headers=headers, params=params)
        if response.status_code == 304:
            return response_result(response, outcome=FetchOutcome.NO_CHANGE)
        if (
            response.status_code == 429
            or response.status_code == 403
            and response.headers.get("x-ratelimit-remaining") == "0"
        ):
            return response_result(
                response,
                outcome=FetchOutcome.FAILED,
                error_code="rate_limited",
                retry_after_seconds=float(response.headers.get("retry-after", "0") or 0),
            )
        response.raise_for_status()
        releases = response.json()
        items = []
        for release in releases[:limit]:
            if release.get("draft"):
                continue
            url = release.get("html_url")
            if not url:
                continue
            published = release.get("published_at") or release.get("created_at")
            items.append(
                NormalizedRawItem(
                    external_id=str(release["id"]),
                    title=release.get("name") or release.get("tag_name") or "Release",
                    canonical_url=url,
                    summary=release.get("body"),
                    authors=(release.get("author", {}).get("login"),)
                    if release.get("author", {}).get("login")
                    else (),
                    published_at=datetime.fromisoformat(
                        published.replace("Z", "+00:00")
                    ).astimezone(UTC)
                    if published
                    else None,
                    source_updated_at=datetime.fromisoformat(
                        release["updated_at"].replace("Z", "+00:00")
                    ).astimezone(UTC)
                    if release.get("updated_at")
                    else None,
                    raw_payload={
                        **release,
                        "release_state": "prerelease" if release.get("prerelease") else "release",
                    },
                )
            )
        next_cursor = response.links.get("next", {}).get("url")
        return response_result(
            response, items=tuple(items), items_received=len(items), next_cursor=next_cursor
        )
