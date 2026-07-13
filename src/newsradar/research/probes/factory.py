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


class OwnedResearchProbe:
    """Research-only probe wrapper; it supports HTTP but never JS or a browser."""

    def __init__(self, probe: ResearchProbe, client: httpx.AsyncClient | None = None) -> None:
        self._probe, self._client = probe, client

    async def probe(self, *args, **kwargs):
        return await self._probe.probe(*args, **kwargs)

    async def aclose(self) -> None:
        if self._client:
            await self._client.aclose()


def research_probe_for(
    source: SourceDefinition, candidate: AcquisitionCandidate, policy: HttpPolicy | None = None
) -> ResearchProbe:
    """Select a bounded read-only probe; acquisition categories remain distinct."""
    owned = policy is None
    client = httpx.AsyncClient(timeout=httpx.Timeout(20), trust_env=False) if owned else None
    resolved = policy or HttpPolicy(client)
    if source.provider_id == "youtube":
        probe = YouTubeResearchProbe(resolved)
    if candidate.kind in {AcquisitionKind.RSS, AcquisitionKind.ATOM, AcquisitionKind.WEBSUB}:
        probe = FeedResearchProbe(resolved)
    if candidate.kind in {
        AcquisitionKind.PUBLIC_API,
        AcquisitionKind.API_KEY_API,
        AcquisitionKind.OAUTH_API,
    }:
        probe = ApiResearchProbe(resolved)
    if candidate.kind is AcquisitionKind.SITEMAP:
        probe = SitemapResearchProbe(resolved)
    if candidate.kind in {
        AcquisitionKind.HTML,
        AcquisitionKind.JSON_LD,
        AcquisitionKind.EMBEDDED_JSON,
    }:
        probe = HtmlResearchProbe(resolved)
    else:
        probe = LibraryResearchProbe(resolved)
    return OwnedResearchProbe(probe, client)
