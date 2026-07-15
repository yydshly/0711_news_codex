"""Safe, auditable final decisions for bounded event-candidate pairs."""

from __future__ import annotations

import json
from hashlib import sha256
from urllib.parse import urlsplit

from newsradar.events.schema import (
    CandidateCluster,
    ClusterItem,
    PairDecisionKind,
    PairFinalDecision,
    PairRuleDecision,
    PairSemanticDecision,
)


def pair_input_fingerprint(left: ClusterItem, right: ClusterItem) -> str:
    """Hash only normalized, bounded candidate fields for cache-safe model reuse."""
    payload = [
        {
            "id": item.raw_item_id,
            "title": item.title[:500],
            "entities": sorted(item.entities),
            "published_hour": (
                item.published_at.isoformat(timespec="hours")
                if item.published_at is not None
                else None
            ),
            "root": safe_root_identity(item),
        }
        for item in sorted((left, right), key=lambda value: value.raw_item_id)
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode()).hexdigest()


def safe_root_identity(item: ClusterItem) -> str | None:
    """Return a bounded URL identity without query, fragment, or credentials."""
    for value in (item.original_url, item.canonical_url):
        if not value:
            continue
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.hostname.casefold()}{port}{parsed.path or '/'}"[:1_000]
    return None


def pair_candidate(item: ClusterItem) -> CandidateCluster:
    return CandidateCluster(
        candidate_key=f"pair-item:{item.raw_item_id}",
        title=item.title,
        items=(item,),
        raw_item_ids=(item.raw_item_id,),
        occurred_at=item.published_at,
    )


def finalize_pair_decision(
    rule: PairRuleDecision,
    semantic: PairSemanticDecision | None,
    input_fingerprint: str,
) -> PairFinalDecision:
    """Allow model-assisted merging only for anchored, high-confidence boundaries."""
    if rule.kind is PairDecisionKind.DIRECT_MERGE:
        decision = "merge"
    elif rule.kind is PairDecisionKind.DIRECT_SEPARATE:
        decision = "separate"
    elif (
        rule.structural_anchor
        and semantic is not None
        and semantic.origin == "model"
        and semantic.same_event
        and semantic.confidence >= 0.85
    ):
        decision = "merge"
    else:
        decision = "separate"
    return PairFinalDecision(
        left_raw_item_id=rule.left_raw_item_id,
        right_raw_item_id=rule.right_raw_item_id,
        input_fingerprint=input_fingerprint,
        rule_score=rule.score,
        rule_reasons=rule.reasons,
        decision=decision,
        model_same_event=semantic.same_event if semantic else None,
        model_confidence=semantic.confidence if semantic else None,
    )
