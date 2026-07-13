from __future__ import annotations

import httpx

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.sources.schema import AcquisitionCandidate, AcquisitionKind, SourceDefinition

from .api import ApiResearchProbe
from .feed import FeedResearchProbe
from .html import HtmlResearchProbe
from .library import LibraryResearchProbe
from .schema import ResearchProbe
from .sitemap import SitemapResearchProbe
from .youtube import YouTubeResearchProbe


def research_probe_for(
    source: SourceDefinition, candidate: AcquisitionCandidate, policy: HttpPolicy | None = None
) -> ResearchProbe:
    """Select a bounded read-only probe; acquisition categories remain distinct."""
    resolved = policy or HttpPolicy(httpx.AsyncClient(timeout=httpx.Timeout(20), trust_env=False))
    if source.provider_id == "youtube":
        return YouTubeResearchProbe(resolved)
    if candidate.kind in {AcquisitionKind.RSS, AcquisitionKind.ATOM, AcquisitionKind.WEBSUB}:
        return FeedResearchProbe(resolved)
    if candidate.kind in {
        AcquisitionKind.PUBLIC_API,
        AcquisitionKind.API_KEY_API,
        AcquisitionKind.OAUTH_API,
    }:
        return ApiResearchProbe(resolved)
    if candidate.kind is AcquisitionKind.SITEMAP:
        return SitemapResearchProbe(resolved)
    if candidate.kind in {
        AcquisitionKind.HTML,
        AcquisitionKind.JSON_LD,
        AcquisitionKind.EMBEDDED_JSON,
    }:
        return HtmlResearchProbe()
    return LibraryResearchProbe(resolved)
