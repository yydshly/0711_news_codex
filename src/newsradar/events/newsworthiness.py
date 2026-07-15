"""Deterministic, explainable rules for deciding whether an item is newsworthy."""

from __future__ import annotations

import re

from newsradar.events.relevance import normalize_text
from newsradar.events.schema import NewsworthinessDecision, RawItemText

NEWSWORTHINESS_RULE_VERSION = "newsworthiness-v1"

ACTION_GROUPS = {
    "release": frozenset(
        {
            "announce",
            "announced",
            "launch",
            "launched",
            "launches",
            "debut",
            "debuts",
            "introduce",
            "introduces",
            "release",
            "released",
            "releases",
            "publish",
            "published",
            "unveil",
            "unveiled",
            "unveils",
            "open source",
        }
    ),
    "funding": frozenset({"funding", "raises", "raised", "investment"}),
    "acquisition": frozenset({"acquire", "acquires", "acquired", "acquisition"}),
    "research_result": frozenset(
        {"benchmark", "study", "paper", "finds", "achieves", "disclosed"}
    ),
    "security": frozenset({"breach", "vulnerability", "exploit", "incident"}),
    "policy": frozenset({"regulation", "policy", "ban", "law", "executive order"}),
    "pricing": frozenset({"price", "pricing", "cost", "subscription"}),
    "outage": frozenset({"outage", "downtime", "disruption"}),
    "partnership": frozenset({"partner", "partnership", "collaboration"}),
}

_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


def evaluate_newsworthiness(item: RawItemText) -> NewsworthinessDecision:
    """Return a stable event-action decision from bounded, untrusted item text."""
    source = " ".join((item.title, item.summary, item.content[:1_000]))
    text = normalize_text(source)
    if not text:
        return NewsworthinessDecision(
            outcome="excluded", score=0, reason_codes=("insufficient_text",)
        )
    if _looks_like_link_only_repost(source):
        return NewsworthinessDecision(
            outcome="excluded",
            score=10,
            reason_codes=("auto_repost_without_claim",),
        )
    action = _event_action(text)
    if action is None:
        return NewsworthinessDecision(
            outcome="excluded", score=35, reason_codes=("no_event_action",)
        )
    return NewsworthinessDecision(
        outcome="included",
        score=80,
        action=action,
        reason_codes=("event_action", action),
    )


def _event_action(text: str) -> str | None:
    for action, terms in ACTION_GROUPS.items():
        if any(_contains_term(text, term) for term in terms):
            return action
    return None


def _looks_like_link_only_repost(source: str) -> bool:
    """Identify a short social repost that only adds tags around a URL."""
    if not _URL_PATTERN.search(source):
        return False
    remainder = _URL_PATTERN.sub(" ", source)
    remainder = re.sub(r"#[\w-]+", " ", remainder)
    text = normalize_text(remainder)
    return bool(text) and len(text.split()) <= 4 and _event_action(text) is None


def _contains_term(text: str, term: str) -> bool:
    return f" {term} " in f" {text} "
