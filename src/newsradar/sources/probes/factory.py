from __future__ import annotations

import httpx

from newsradar.sources.schema import AccessKind, AccessMethod

from .base import BaseProbe, UnsupportedProbe
from .json_api import JsonApiProbe
from .protocols import BlueskyProbe, HackerNewsProbe, RedditProbe, YouTubeProbe
from .rss import RssProbe


class ProbeFactory:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    def create(self, method: AccessMethod) -> BaseProbe:
        if method.kind in {AccessKind.RSS, AccessKind.ATOM}:
            return RssProbe(self.client)
        if method.kind in {AccessKind.REST_API, AccessKind.PUBLIC_API}:
            host = method.url.host or ""
            if host == "hacker-news.firebaseio.com":
                return HackerNewsProbe(self.client)
            if host == "www.googleapis.com" and "/youtube/" in method.url.path:
                return YouTubeProbe(self.client)
            if host == "public.api.bsky.app":
                return BlueskyProbe(self.client)
            if host == "oauth.reddit.com":
                return RedditProbe(self.client)
            return JsonApiProbe(self.client)
        return UnsupportedProbe(self.client)
