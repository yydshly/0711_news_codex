from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlsplit

from newsradar.ingestion.schema import FetchOutcome, NormalizedRawItem
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, response_result


class GitHubFetcher:
    def __init__(self, policy: HttpPolicy):
        self.policy = policy

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ):
        audited_url = str(method.url)
        audited = urlsplit(audited_url)
        if (
            not _is_safe_github_endpoint(audited)
            or not audited.path.startswith("/repos/")
            or not audited.path.endswith("/releases")
            or audited.query
            or audited.fragment
        ):
            raise ValueError("unaudited_github_repository")
        cursor = urlsplit(state.cursor) if state.cursor else None
        request_url = (
            state.cursor
            if cursor is not None
            and _is_safe_github_endpoint(cursor)
            and cursor.path == audited.path
            and not cursor.fragment
            and _is_safe_pagination_query(cursor.query)
            else audited_url
        )
        headers = {"Accept": "application/vnd.github+json", **method.headers}
        if state.etag:
            headers["If-None-Match"] = state.etag
        params = (
            None
            if request_url != audited_url
            else {
                **method.params,
                "per_page": min(limit, 100),
            }
        )
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


def _is_safe_github_endpoint(parsed) -> bool:
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "api.github.com"
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
    )


def _is_safe_pagination_query(query: str) -> bool:
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    return bool(pairs) and all(
        key in {"page", "per_page"} and value.isdigit() and int(value) > 0 for key, value in pairs
    )
