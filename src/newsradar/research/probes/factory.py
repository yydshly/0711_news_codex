from __future__ import annotations

from typing import overload

import httpx

from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.sources.schema import AcquisitionCandidate, AcquisitionKind, SourceDefinition

from .api import ApiResearchProbe
from .feed import FeedResearchProbe
from .html import HtmlResearchProbe
from .library import LibraryResearchProbe
from .safe_http import new_safe_probe_client
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

    async def __aenter__(self) -> OwnedResearchProbe:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.aclose()


@overload
def research_probe_for(
    candidate: AcquisitionCandidate, policy: HttpPolicy | None = None
) -> OwnedResearchProbe: ...


@overload
def research_probe_for(
    source: SourceDefinition,
    candidate: AcquisitionCandidate,
    policy: HttpPolicy | None = None,
) -> OwnedResearchProbe: ...


def research_probe_for(
    source_or_candidate: SourceDefinition | AcquisitionCandidate,
    candidate: AcquisitionCandidate | None = None,
    policy: HttpPolicy | None = None,
) -> OwnedResearchProbe:
    """Select a bounded read-only probe; acquisition categories remain distinct."""
    if isinstance(source_or_candidate, AcquisitionCandidate):
        if candidate is not None:
            raise TypeError("candidate-only research_probe_for accepts no second candidate")
        source = None
        candidate = source_or_candidate
    else:
        source = source_or_candidate
        if candidate is None:
            raise TypeError("source-aware research_probe_for requires a candidate")
    owned = policy is None
    client = new_safe_probe_client() if owned else None
    resolved = policy or HttpPolicy(client)
    if source is not None and source.provider_id == "youtube":
        probe = YouTubeResearchProbe(resolved)
    elif candidate.kind in {AcquisitionKind.RSS, AcquisitionKind.ATOM, AcquisitionKind.WEBSUB}:
        probe = FeedResearchProbe(resolved)
    elif candidate.kind in {
        AcquisitionKind.PUBLIC_API,
        AcquisitionKind.API_KEY_API,
        AcquisitionKind.OAUTH_API,
    }:
        probe = ApiResearchProbe(resolved)
    elif candidate.kind is AcquisitionKind.SITEMAP:
        probe = SitemapResearchProbe(resolved)
    elif candidate.kind in {
        AcquisitionKind.HTML,
        AcquisitionKind.JSON_LD,
        AcquisitionKind.EMBEDDED_JSON,
    }:
        probe = HtmlResearchProbe(resolved)
    else:
        probe = LibraryResearchProbe(resolved)
    return OwnedResearchProbe(probe, client)
