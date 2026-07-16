from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import unquote, urlsplit, urlunsplit

from defusedxml.ElementTree import fromstring

from newsradar.ingestion.schema import FetchOutcome, NormalizedRawItem
from newsradar.sources.schema import AccessMethod, SourceDefinition

from .base import FetchState, HttpPolicy, response_result


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element, name: str) -> str | None:
    for child in element.iter():
        if _local_name(child.tag) == name and child.text and child.text.strip():
            return child.text.strip()
    return None


def _public_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("invalid_public_url")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credentialed_url")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))


def _slug_title(value: str) -> str:
    path = urlsplit(value).path.rstrip("/")
    slug = unquote(path.rsplit("/", 1)[-1]) if path else ""
    title = re.sub(r"\s+", " ", re.sub(r"[-_]+", " ", slug)).strip()
    if not title:
        raise ValueError("missing_title")
    return title.title()


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


class SitemapFetcher:
    def __init__(self, policy: HttpPolicy):
        self.policy = policy

    async def fetch(
        self, source: SourceDefinition, method: AccessMethod, state: FetchState, limit: int
    ):
        headers = {"User-Agent": "NewsRadarIngestion/0.1"}
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified
        response = await self.policy.get(
            str(method.url),
            headers=headers,
            params=method.params,
        )
        if response.status_code == 304:
            return response_result(response, outcome=FetchOutcome.NO_CHANGE)
        response.raise_for_status()
        root = fromstring(response.content)
        root_name = _local_name(root.tag)
        if root_name == "sitemapindex":
            raise ValueError("unsupported_sitemap_index")
        if root_name != "urlset":
            raise ValueError("unsupported_sitemap_root")

        items: list[NormalizedRawItem] = []
        warnings: list[str] = []
        for element in root:
            if _local_name(element.tag) != "url" or len(items) >= limit:
                continue
            try:
                loc = _child_text(element, "loc")
                if not loc:
                    raise ValueError("missing_url")
                canonical_url = _public_url(loc)
                official_title = _child_text(element, "title")
                title = official_title or _slug_title(canonical_url)
                lastmod = _date(_child_text(element, "lastmod"))
                publication_date = _date(_child_text(element, "publication_date"))
                items.append(
                    NormalizedRawItem(
                        external_id=hashlib.sha256(canonical_url.encode()).hexdigest(),
                        title=title,
                        canonical_url=canonical_url,
                        published_at=publication_date or lastmod,
                        source_updated_at=lastmod,
                        raw_payload={
                            "loc": canonical_url,
                            "lastmod": _child_text(element, "lastmod"),
                            "publication_date": _child_text(element, "publication_date"),
                            "title_source": "news_sitemap" if official_title else "url_slug",
                        },
                    )
                )
            except (TypeError, ValueError) as exc:
                warnings.append(f"malformed_sitemap_entry:{exc}")
        if not items:
            raise ValueError("sitemap_no_usable_entries")
        return response_result(
            response,
            items=tuple(items),
            items_received=len(items),
            warnings=tuple(warnings),
        )
