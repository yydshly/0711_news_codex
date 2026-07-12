from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from urllib.parse import urlsplit

from newsradar.ingestion.attribution import OriginResolutionStatus
from newsradar.ingestion.schema import NormalizedRawItem
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, response_result


class GdeltFetcher:
    """Fetch GDELT search results as discovery records, never article content."""

    def __init__(self, policy: HttpPolicy):
        self.policy = policy

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ):
        del source, state
        response = await self.policy.get(
            str(method.url),
            headers={"User-Agent": "NewsRadarIngestion/0.1", **method.headers},
            params={**method.params, "mode": "artlist", "format": "json", "maxrecords": str(limit)},
        )
        response.raise_for_status()
        payload = response.json()
        articles = payload.get("articles", []) if isinstance(payload, dict) else []
        items, warnings = [], []
        for article in articles[:limit]:
            try:
                if not isinstance(article, dict):
                    raise ValueError("invalid_article")
                url, title = article.get("url"), article.get("title")
                if not isinstance(url, str) or not isinstance(title, str) or not title.strip():
                    raise ValueError("missing_url_or_title")
                domain = article.get("domain")
                publisher_name = _publisher_name(domain) if isinstance(domain, str) else None
                items.append(
                    NormalizedRawItem(
                        external_id=hashlib.sha256(url.encode()).hexdigest(),
                        title=title.strip(),
                        canonical_url=url,
                        original_url=url,
                        summary=article.get("excerpt")
                        if isinstance(article.get("excerpt"), str)
                        else None,
                        language=_language_code(article.get("language")),
                        published_at=_gdelt_datetime(article.get("seendate")),
                        source_updated_at=_gdelt_datetime(article.get("seendate")),
                        publisher_name=publisher_name,
                        publisher_url=url if publisher_name else None,
                        discovery_url=url,
                        origin_resolution_status=(
                            OriginResolutionStatus.RESOLVED
                            if publisher_name
                            else OriginResolutionStatus.UNRESOLVED
                        ),
                        raw_payload=article,
                    )
                )
            except (TypeError, ValueError) as exc:
                warnings.append(f"malformed_article:{exc}")
        return response_result(
            response, items=tuple(items), items_received=len(items), warnings=tuple(warnings)
        )


def _publisher_name(domain: str) -> str | None:
    if any(separator in domain for separator in (",", ";", " ")):
        return None
    host = urlsplit(f"https://{domain}").hostname
    if not host:
        return None
    label = host.lower().removeprefix("www.").split(".")[0]
    return label.replace("-", " ").title() if label else None


def _language_code(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    values = {"english": "en", "french": "fr", "spanish": "es", "german": "de"}
    return values.get(value.lower(), value.lower()[:2])


def _gdelt_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=UTC)
        except ValueError:
            pass
    return None
