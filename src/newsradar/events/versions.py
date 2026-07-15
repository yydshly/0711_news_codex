"""Immutable algorithm versions shared by event producers and consumers."""

from types import MappingProxyType

EVENT_ALGORITHM_VERSIONS = MappingProxyType(
    {
        "relevance": "relevance-v2",
        "newsworthiness": "newsworthiness-v2",
        "entities": "entities-v2",
        "cluster": "cluster-v2",
        "score": "score-v2",
    }
)
