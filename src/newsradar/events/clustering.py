"""Bounded, deterministic candidate clustering rules."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from difflib import SequenceMatcher
from hashlib import sha256

from newsradar.events.schema import (
    CandidateCluster,
    ClusterDecision,
    ClusterItem,
    PairDecisionKind,
    PairFinalDecision,
    PairRuleDecision,
)

CLUSTER_RULE_VERSION = "cluster-v3"
TITLE_SIMILARITY_THRESHOLD = 0.58
MODEL_BOUNDARY_TITLE_THRESHOLD = 0.42
_CANDIDATE_WINDOW_SECONDS = 48 * 60 * 60
_GENERIC_ENTITIES = frozenset({"ai", "agent", "api", "benchmark", "llm", "model"})
_OBJECT_ENTITY_TYPES = frozenset({"product", "model", "paper", "dataset", "project"})
_ORGANIZATION_ENTITY_ACTIONS = frozenset({"acquire", "partner", "fund", "regulate"})
_STRONG_IDENTITY_REASONS = frozenset(
    {"same_evidence_root", "same_canonical_url", "same_repository_id", "same_paper_id"}
)
_STRONG_BLOCKING_KEY_PREFIXES = (
    "canonical_hash:",
    "canonical_url:",
    "discovery:",
    "url_identity:",
    "repository:",
    "paper:",
)
_ACTION_GROUPS = {
    "launch": frozenset(
        {
            "announce",
            "announced",
            "launch",
            "launches",
            "launched",
            "publish",
            "publishes",
            "published",
            "release",
            "releases",
            "released",
            "unveil",
            "unveils",
            "unveiled",
        }
    ),
    "acquire": frozenset({"acquire", "acquires", "acquired", "acquisition"}),
    "partner": frozenset({"partner", "partners", "partnership"}),
    "fund": frozenset({"funding", "raises", "raised", "investment"}),
    "regulate": frozenset(
        {
            "regulate",
            "regulates",
            "regulated",
            "regulation",
            "investigate",
            "investigates",
            "investigation",
            "ban",
            "bans",
            "banned",
        }
    ),
}


def compare_items(left: ClusterItem, right: ClusterItem) -> ClusterDecision:
    """Compare a pre-blocked pair using local, explainable evidence only."""
    reasons: list[str] = []
    if _immutable_identity_score(left, right, reasons):
        return _decision(True, 1.0, tuple(reasons))

    left_action, right_action = _action(left.title), _action(right.title)
    if left_action and right_action and left_action != right_action:
        return _decision(False, 0.0, ("conflicting_action",))

    if (
        left.title_fingerprint
        and left.title_fingerprint == right.title_fingerprint
        and _same_publisher_or_root(left, right)
        and _within_candidate_window(left, right)
    ):
        return _decision(
            True,
            1.0,
            ("same_title_fingerprint", "within_48_hours"),
        )

    left_objects = _object_entities(left.entities)
    right_objects = _object_entities(right.entities)
    if left_objects and right_objects and left_objects.isdisjoint(right_objects):
        return _decision(False, 0.0, ("disjoint_object_entities",))

    shared_entities = _non_generic_entities(left.entities) & _non_generic_entities(
        right.entities
    )
    if not shared_entities:
        return _decision(False, 0.0, ())
    reasons.append("shared_non_generic_entity")
    if any(_entity_type(entity) in _OBJECT_ENTITY_TYPES for entity in shared_entities):
        reasons.append("shared_object_entity")
    else:
        reasons.append("shared_organization")

    if not left_action or left_action != right_action:
        return _decision(False, 0.0, tuple(reasons))
    reasons.append("same_action")
    if "shared_organization" in reasons and left_action not in _ORGANIZATION_ENTITY_ACTIONS:
        reasons.append("organization_only_not_sufficient")
        return _decision(False, 0.0, tuple(reasons))

    if not _within_candidate_window(left, right):
        return _decision(False, 0.0, tuple(reasons))
    reasons.append("within_48_hours")

    title_similarity = _title_similarity(left, right)
    if title_similarity >= TITLE_SIMILARITY_THRESHOLD:
        reasons.append("safe_title_similarity")
        return _decision(True, title_similarity, tuple(reasons))
    if title_similarity >= MODEL_BOUNDARY_TITLE_THRESHOLD:
        reasons.append("model_boundary_title_similarity")
    else:
        reasons.append("low_title_similarity")
    return _decision(False, title_similarity, tuple(reasons))


def candidate_pairs(
    items: tuple[ClusterItem, ...],
) -> tuple[tuple[ClusterItem, ClusterItem], ...]:
    """Return only time-and-identity-blocked pairs, never a global cross product."""
    ordered = tuple(sorted(items, key=lambda item: item.raw_item_id))
    return tuple(
        (ordered[left_index], ordered[right_index])
        for left_index, right_index in _candidate_pairs(ordered)
    )


def evaluate_pair_rules(left: ClusterItem, right: ClusterItem) -> PairRuleDecision:
    """Classify a bounded pair into direct or model-boundary treatment."""
    compared = compare_items(left, right)
    reason_set = set(compared.reasons)
    strong_identity = bool(_STRONG_IDENTITY_REASONS & reason_set)
    semantic_anchor = {
        "shared_non_generic_entity",
        "same_action",
    } <= reason_set and "organization_only_not_sufficient" not in reason_set
    structural_anchor = strong_identity or semantic_anchor
    if compared.matched and (
        strong_identity
        or "same_title_fingerprint" in reason_set
        or (semantic_anchor and "safe_title_similarity" in reason_set)
    ):
        kind = PairDecisionKind.DIRECT_MERGE
    elif semantic_anchor and "model_boundary_title_similarity" in reason_set:
        kind = PairDecisionKind.MODEL_BOUNDARY
    else:
        kind = PairDecisionKind.DIRECT_SEPARATE
    return PairRuleDecision(
        left_raw_item_id=min(left.raw_item_id, right.raw_item_id),
        right_raw_item_id=max(left.raw_item_id, right.raw_item_id),
        score=compared.score,
        reasons=compared.reasons,
        structural_anchor=structural_anchor,
        kind=kind,
    )


def cluster_candidates(
    items: tuple[ClusterItem, ...],
    pair_decisions: Mapping[tuple[int, int], PairFinalDecision] | None = None,
) -> tuple[CandidateCluster, ...]:
    """Union matching pairs only when a blocking key and 48-hour window permit it."""
    ordered = tuple(sorted(items, key=lambda item: item.raw_item_id))
    parents = list(range(len(ordered)))
    component_min = [item.published_at for item in ordered]
    component_max = [item.published_at for item in ordered]
    reasons_by_index: list[set[str]] = [set() for _ in ordered]
    for left_index, right_index in _candidate_pairs(ordered):
        left, right = ordered[left_index], ordered[right_index]
        if pair_decisions is None:
            compared = compare_items(left, right)
            should_merge = compared.matched
            reasons = compared.reasons
        else:
            pair = pair_decisions.get(
                (min(left.raw_item_id, right.raw_item_id), max(left.raw_item_id, right.raw_item_id))
            )
            should_merge = pair is not None and pair.decision == "merge"
            reasons = pair.rule_reasons if pair is not None else ()
        within_window = _can_union_within_window(
            parents, component_min, component_max, left_index, right_index
        )
        strong_identity = bool(_STRONG_IDENTITY_REASONS & set(reasons))
        if should_merge and (within_window or strong_identity):
            _union(
                parents,
                component_min,
                component_max,
                left_index,
                right_index,
            )
            reasons_by_index[left_index].update(reasons)
            reasons_by_index[right_index].update(reasons)

    grouped: dict[int, list[int]] = {}
    for index in range(len(ordered)):
        grouped.setdefault(_find(parents, index), []).append(index)
    clusters = []
    for indexes in grouped.values():
        members = tuple(ordered[index] for index in indexes)
        cluster_reasons = tuple(
            sorted({reason for index in indexes for reason in reasons_by_index[index]})
        )
        ids = tuple(member.raw_item_id for member in members)
        clusters.append(
            CandidateCluster(
                candidate_key=_candidate_key(members),
                title=members[0].title,
                items=members,
                raw_item_ids=ids,
                reasons=cluster_reasons,
                metadata={"_core_identity": _core_identity(members)},
                occurred_at=min(
                    (member.published_at for member in members if member.published_at is not None),
                    default=datetime(1970, 1, 1, tzinfo=UTC),
                ),
            )
        )
    return tuple(clusters)


def _decision(matched: bool, score: float, reasons: tuple[str, ...]) -> ClusterDecision:
    bounded_score = min(score, 1.0)
    return ClusterDecision(
        matched=matched,
        score=bounded_score,
        should_merge=matched,
        confidence=bounded_score,
        reasons=reasons,
    )


def _immutable_identity_score(left: ClusterItem, right: ClusterItem, reasons: list[str]) -> float:
    score = 0.0
    same_canonical_url = bool(
        (left.canonical_url_hash and left.canonical_url_hash == right.canonical_url_hash)
        or (left.canonical_url and left.canonical_url == right.canonical_url)
    )
    if same_canonical_url:
        reasons.append("same_canonical_url")
        score += 1.0
    elif _url_identities(left) & _url_identities(right):
        reasons.append("same_evidence_root")
        score += 1.0
    if left.repository_id and left.repository_id == right.repository_id:
        reasons.append("same_repository_id")
        score += 1.0
    if left.paper_id and left.paper_id == right.paper_id:
        reasons.append("same_paper_id")
        score += 1.0
    return score


def _candidate_pairs(items: tuple[ClusterItem, ...]) -> tuple[tuple[int, int], ...]:
    buckets: dict[str, list[int]] = {}
    for index, item in enumerate(items):
        for key in _blocking_keys(item):
            if item.published_at is None and not _strong_blocking_key(key):
                continue
            buckets.setdefault(key, []).append(index)
    pairs: set[tuple[int, int]] = set()
    for key, indexes in buckets.items():
        if _strong_blocking_key(key):
            pairs.update(
                (min(left, right), max(left, right))
                for offset, left in enumerate(indexes)
                for right in indexes[offset + 1 :]
            )
            continue
        time_ordered = sorted(indexes, key=lambda index: (items[index].published_at, index))
        for offset, left_index in enumerate(time_ordered):
            for right_index in time_ordered[offset + 1 :]:
                if not _within_candidate_window(items[left_index], items[right_index]):
                    break
                pairs.add((min(left_index, right_index), max(left_index, right_index)))
    return tuple(sorted(pairs))


def _blocking_keys(item: ClusterItem) -> tuple[str, ...]:
    keys = set()
    if item.canonical_url_hash:
        keys.add(f"canonical_hash:{item.canonical_url_hash}")
    if item.canonical_url:
        keys.add(f"canonical_url:{item.canonical_url}")
        keys.add(f"url_identity:{item.canonical_url}")
    if item.title_fingerprint:
        keys.add(f"title:{item.title_fingerprint}")
    keys.update(f"entity:{entity}" for entity in _non_generic_entities(item.entities))
    if item.repository_id:
        keys.add(f"repository:{item.repository_id}")
    if item.paper_id:
        keys.add(f"paper:{item.paper_id}")
    if item.original_url:
        keys.add(f"discovery:{item.original_url}")
        keys.add(f"url_identity:{item.original_url}")
    return tuple(sorted(keys))


def _strong_blocking_key(key: str) -> bool:
    return key.startswith(_STRONG_BLOCKING_KEY_PREFIXES)


def _within_candidate_window(left: ClusterItem, right: ClusterItem) -> bool:
    return (
        left.published_at is not None
        and right.published_at is not None
        and abs((left.published_at - right.published_at).total_seconds())
        <= _CANDIDATE_WINDOW_SECONDS
    )


def _non_generic_entities(entities: tuple[str, ...]) -> set[str]:
    return {
        entity
        for entity in entities
        if entity.rsplit(":", 1)[-1].casefold().replace("-", "") not in _GENERIC_ENTITIES
    }


def _object_entities(entities: tuple[str, ...]) -> set[str]:
    return {
        entity
        for entity in _non_generic_entities(entities)
        if _entity_type(entity) in _OBJECT_ENTITY_TYPES
    }


def _entity_type(entity: str) -> str:
    return entity.split(":", 1)[0].casefold() if ":" in entity else ""


def _url_identities(item: ClusterItem) -> set[str]:
    return {value for value in (item.canonical_url, item.original_url) if value}


def _same_publisher_or_root(left: ClusterItem, right: ClusterItem) -> bool:
    same_publisher = bool(
        left.publisher_name
        and right.publisher_name
        and left.publisher_name.casefold().strip() == right.publisher_name.casefold().strip()
    )
    return same_publisher or bool(_url_identities(left) & _url_identities(right))


def _normalized_title(item: ClusterItem) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", item.title.casefold()).strip()
    publisher = re.sub(
        r"[^a-z0-9]+", " ", (item.publisher_name or "").casefold()
    ).strip()
    if publisher and text.endswith(f" {publisher}"):
        text = text[: -(len(publisher) + 1)].strip()
    return " ".join(
        token for token in text.split() if token not in {"the", "a", "an", "new", "report"}
    )


def _title_similarity(left: ClusterItem, right: ClusterItem) -> float:
    return SequenceMatcher(None, _normalized_title(left), _normalized_title(right)).ratio()


def _action(title: str) -> str | None:
    normalized = title.casefold()
    if re.search(r"\bopen(?:-|\s)+sourc(?:e|es|ed)\b", normalized):
        return "launch"
    tokens = set(re.findall(r"[a-z0-9]+", normalized.replace("-", " ")))
    return next((name for name, words in _ACTION_GROUPS.items() if tokens & words), None)


def _candidate_key(items: tuple[ClusterItem, ...]) -> str:
    """Durable identity: canonical/root entity + action + source-time bucket.

    Member ids deliberately do not participate: later independent reporting changes a
    version's memberships, not the identity of the underlying event.
    """
    anchor = min(items, key=lambda item: item.raw_item_id)
    anchor_entities = _non_generic_entities(anchor.entities)
    primary = next(
        (
            value
            for value in (
                f"repository:{anchor.repository_id}" if anchor.repository_id else None,
                f"paper:{anchor.paper_id}" if anchor.paper_id else None,
                f"root:{anchor.original_url}" if anchor.original_url else None,
                f"url:{anchor.canonical_url}" if anchor.canonical_url else None,
                min(
                    (
                        entity
                        for entity in anchor_entities
                        if _entity_type(entity) in _OBJECT_ENTITY_TYPES
                    ),
                    default=None,
                ),
                f"title:{anchor.title_fingerprint or anchor.title.casefold()}",
            )
            if value
        ),
        "title:",
    )
    action = _action(anchor.title) or "report"
    occurred = anchor.published_at or datetime(1970, 1, 1, tzinfo=UTC)
    if primary.startswith(("repository:", "paper:", "root:", "url:")):
        value = f"{CLUSTER_RULE_VERSION}|{primary}"
    else:
        value = f"{CLUSTER_RULE_VERSION}|{primary}|{action}|{occurred.date().isoformat()}"
    return f"event-v2:{sha256(value.encode()).hexdigest()[:16]}"


def _core_identity(items: tuple[ClusterItem, ...]) -> str | None:
    object_sets = tuple(
        {
            entity
            for entity in _non_generic_entities(item.entities)
            if _entity_type(entity) in _OBJECT_ENTITY_TYPES
        }
        for item in items
    )
    shared_objects = set.intersection(*object_sets) if object_sets else set()
    if not shared_objects:
        shared_objects = set().union(*object_sets) if object_sets else set()
    if not shared_objects:
        return None
    primary = min(shared_objects)
    actions = {_action(item.title) for item in items}
    actions.discard(None)
    action = min(actions, default="report")
    return f"{primary}|{action}"


def _find(parents: list[int], index: int) -> int:
    if parents[index] != index:
        parents[index] = _find(parents, parents[index])
    return parents[index]


def _union(
    parents: list[int],
    component_min: list[datetime | None],
    component_max: list[datetime | None],
    left: int,
    right: int,
) -> None:
    left_root, right_root = _find(parents, left), _find(parents, right)
    if left_root != right_root:
        parents[right_root] = left_root
        left_min, right_min = component_min[left_root], component_min[right_root]
        left_max, right_max = component_max[left_root], component_max[right_root]
        minimums = [value for value in (left_min, right_min) if value is not None]
        maximums = [value for value in (left_max, right_max) if value is not None]
        component_min[left_root] = min(minimums) if minimums else None
        component_max[left_root] = max(maximums) if maximums else None


def _can_union_within_window(
    parents: list[int],
    component_min: list[datetime | None],
    component_max: list[datetime | None],
    left: int,
    right: int,
) -> bool:
    left_root, right_root = _find(parents, left), _find(parents, right)
    if left_root == right_root:
        return True
    timestamps = (
        component_min[left_root],
        component_min[right_root],
        component_max[left_root],
        component_max[right_root],
    )
    if any(value is None for value in timestamps):
        return False
    return (max(timestamps) - min(timestamps)).total_seconds() <= (
        _CANDIDATE_WINDOW_SECONDS
    )
