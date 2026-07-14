"""Bounded, deterministic candidate clustering rules."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from hashlib import sha256

from newsradar.events.schema import CandidateCluster, ClusterDecision, ClusterItem

CLUSTER_RULE_VERSION = "cluster-v2"
_CANDIDATE_WINDOW_SECONDS = 48 * 60 * 60
_GENERIC_ENTITIES = frozenset({"ai", "agent", "api", "benchmark", "llm", "model"})
_OBJECT_ENTITY_TYPES = frozenset({"product", "model", "paper", "dataset", "project"})
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
}


def compare_items(left: ClusterItem, right: ClusterItem) -> ClusterDecision:
    """Compare a pre-blocked pair using local, explainable evidence only."""
    reasons: list[str] = []
    score = _immutable_identity_score(left, right, reasons)
    left_action, right_action = _action(left.title), _action(right.title)
    if score == 0 and left_action and right_action and left_action != right_action:
        return _decision(False, 0.0, ("conflicting_action",))
    if (
        left.title_fingerprint
        and left.title_fingerprint == right.title_fingerprint
        and _same_publisher_or_root(left, right)
    ):
        reasons.append("same_title_fingerprint")
        score += 0.8
    score += _entity_action_similarity(left, right, left_action, right_action, reasons)
    score += _time_similarity(left.published_at, right.published_at, reasons)
    return _decision(score >= 1.0, score, tuple(reasons))


def cluster_candidates(items: tuple[ClusterItem, ...]) -> tuple[CandidateCluster, ...]:
    """Union matching pairs only when a blocking key and 48-hour window permit it."""
    ordered = tuple(sorted(items, key=lambda item: item.raw_item_id))
    parents = list(range(len(ordered)))
    component_min = [item.published_at for item in ordered]
    component_max = [item.published_at for item in ordered]
    reasons_by_index: list[set[str]] = [set() for _ in ordered]
    for left_index, right_index in _candidate_pairs(ordered):
        decision = compare_items(ordered[left_index], ordered[right_index])
        if decision.matched and _can_union_within_window(
            parents,
            component_min,
            component_max,
            left_index,
            right_index,
        ):
            _union(
                parents,
                component_min,
                component_max,
                left_index,
                right_index,
            )
            reasons_by_index[left_index].update(decision.reasons)
            reasons_by_index[right_index].update(decision.reasons)

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


def _entity_action_similarity(
    left: ClusterItem,
    right: ClusterItem,
    left_action: str | None,
    right_action: str | None,
    reasons: list[str],
) -> float:
    shared_entities = _non_generic_entities(left.entities) & _non_generic_entities(right.entities)
    if not shared_entities:
        return 0.0
    shared_objects = {
        entity
        for entity in shared_entities
        if _entity_type(entity) in _OBJECT_ENTITY_TYPES
    }
    if shared_objects:
        reasons.append("shared_object_entity")
    else:
        reasons.append("shared_organization")
    if shared_objects and left_action and left_action == right_action:
        reasons.append("same_action")
        return 0.8
    return 0.4


def _time_similarity(left: datetime | None, right: datetime | None, reasons: list[str]) -> float:
    if left is None or right is None:
        return 0.0
    if abs((left - right).total_seconds()) <= _CANDIDATE_WINDOW_SECONDS:
        reasons.append("within_48_hours")
        return 0.2
    return 0.0


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
        if item.published_at is None:
            continue
        for key in _blocking_keys(item):
            buckets.setdefault(key, []).append(index)
    pairs: set[tuple[int, int]] = set()
    for indexes in buckets.values():
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
    if item.title_fingerprint:
        keys.add(f"title:{item.title_fingerprint}")
    keys.update(f"entity:{entity}" for entity in _non_generic_entities(item.entities))
    if item.repository_id:
        keys.add(f"repository:{item.repository_id}")
    if item.paper_id:
        keys.add(f"paper:{item.paper_id}")
    if item.original_url:
        keys.add(f"discovery:{item.original_url}")
    return tuple(sorted(keys))


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
        component_min[left_root] = min(
            value for value in (left_min, right_min) if value is not None
        )
        component_max[left_root] = max(
            value for value in (left_max, right_max) if value is not None
        )


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
