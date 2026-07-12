from __future__ import annotations

import re
from datetime import UTC, datetime
from html import unescape
from urllib.parse import urlsplit

from newsradar.ingestion.schema import FetchOutcome, NormalizedRawItem
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, public_headers, response_result


class MastodonFetcher:
    def __init__(self, policy: HttpPolicy):
        self.policy = policy

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ):
        configured_url = str(method.url)
        host = self._require_registered_instance(configured_url, method.params)
        request_url = state.cursor or configured_url
        self._validate_cursor(request_url, configured_url)
        response = await self.policy.get(
            request_url,
            headers={"Accept": "application/json", **public_headers(method.headers)},
            params=None if state.cursor else {**method.params, "limit": str(min(limit, 40))},
        )
        if response.status_code == 429:
            return response_result(
                response,
                outcome=FetchOutcome.FAILED,
                error_code="rate_limited",
                retry_after_seconds=float(response.headers.get("retry-after", "0") or 0),
            )
        response.raise_for_status()
        payload = response.json()
        items = tuple(
            item for row in payload[:limit] if (item := self._item(row, host)) is not None
        )
        return response_result(
            response,
            items=items,
            items_received=len(items),
            next_cursor=response.links.get("next", {}).get("url"),
        )

    @staticmethod
    def _require_registered_instance(url: str, params: dict[str, str]) -> str:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("unregistered_mastodon_instance")
        is_account_timeline = re.fullmatch(r"/api/v1/accounts/[^/]+/statuses", parsed.path)
        is_local_timeline = (
            parsed.path == "/api/v1/timelines/public" and params.get("local", "").lower() == "true"
        )
        if not is_account_timeline and not is_local_timeline:
            raise ValueError("unbounded_mastodon_discovery")
        return parsed.hostname.lower()

    @staticmethod
    def _validate_cursor(cursor: str, configured_url: str) -> None:
        candidate, configured = urlsplit(cursor), urlsplit(configured_url)
        if _origin(candidate) != _origin(configured) or candidate.path != configured.path:
            raise ValueError("unregistered_mastodon_instance")

    @staticmethod
    def _item(row: object, host: str) -> NormalizedRawItem | None:
        if not isinstance(row, dict) or row.get("deleted"):
            return None
        status_id, url, account = row.get("id"), row.get("url"), row.get("account")
        if not status_id or not url or not isinstance(account, dict):
            return None
        content = _text(row.get("content", ""))
        warning = _text(row.get("spoiler_text", ""))
        title = warning or content.splitlines()[0] if content or warning else "Mastodon status"
        acct = account.get("acct")
        metrics = {
            "favourites": row.get("favourites_count", 0),
            "reblogs": row.get("reblogs_count", 0),
            "replies": row.get("replies_count", 0),
        }
        return NormalizedRawItem(
            external_id=f"{host}:{status_id}",
            title=title[:500],
            canonical_url=url,
            authors=(account.get("display_name") or acct,)
            if (account.get("display_name") or acct)
            else (),
            content=content or None,
            published_at=_timestamp(row.get("created_at")),
            engagement={key: value for key, value in metrics.items() if isinstance(value, int)},
            item_kind="social_post",
            author_account_id=f"{host}:{account.get('id')}" if account.get("id") else None,
            author_handle=f"{acct}@{host}" if acct and "@" not in acct else acct,
            raw_payload=row,
        )


def _text(value: object) -> str:
    return (
        " ".join(unescape(re.sub(r"<[^>]*>", " ", value)).split()) if isinstance(value, str) else ""
    )


def _timestamp(value: object) -> datetime | None:
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        if isinstance(value, str)
        else None
    )


def _origin(parts: object) -> tuple[str, str, int]:
    parsed = parts if hasattr(parts, "hostname") else urlsplit(str(parts))
    scheme = parsed.scheme.lower()
    port = parsed.port or (443 if scheme == "https" else 80)
    return scheme, (parsed.hostname or "").lower(), port
