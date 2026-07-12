from __future__ import annotations

import httpx

from newsradar.credentials import CredentialProvider
from newsradar.sources.schema import AccessKind, AccessMethod

from .base import BaseProbe, UnsupportedProbe
from .json_api import JsonApiProbe
from .protocols import BlueskyProbe, HackerNewsProbe, RedditProbe, YouTubeProbe
from .rss import RssProbe


class ProbeFactory:
    def __init__(self, client: httpx.AsyncClient, credentials: CredentialProvider | None = None):
        self.client, self.credentials = client, credentials

    def create(self, method: AccessMethod) -> BaseProbe:
        if method.kind in {AccessKind.RSS, AccessKind.ATOM}:
            return RssProbe(self.client, self.credentials)
        if method.kind in {AccessKind.REST_API, AccessKind.PUBLIC_API}:
            host = method.url.host or ""
            if host == "hacker-news.firebaseio.com":
                return HackerNewsProbe(self.client, self.credentials)
            if host == "www.googleapis.com" and "/youtube/" in method.url.path:
                return YouTubeProbe(self.client, self.credentials)
            if host == "public.api.bsky.app":
                return BlueskyProbe(self.client, self.credentials)
            if host == "oauth.reddit.com":
                return RedditProbe(self.client, self.credentials)
            return JsonApiProbe(self.client, self.credentials)
        return UnsupportedProbe(self.client, self.credentials)
