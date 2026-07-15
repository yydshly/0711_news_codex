from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Schema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EventVisibility(StrEnum):
    CURRENT = "current"
    LEGACY = "legacy"


class EventTier(StrEnum):
    HOTSPOT = "hotspot"
    SIGNAL = "signal"
    AUDIT_ONLY = "audit_only"


class EventStatus(StrEnum):
    EMERGING = "emerging"
    CONFIRMED = "confirmed"
    DEVELOPING = "developing"
    DISPUTED = "disputed"
    STALE = "stale"
    REJECTED = "rejected"


class EvidenceRole(StrEnum):
    OFFICIAL = "official"
    PROFESSIONAL_MEDIA = "professional_media"
    RESEARCH = "research"
    COMMUNITY = "community"
    SOCIAL = "social"
    AGGREGATOR = "aggregator"


class ProcessingStage(StrEnum):
    RELEVANCE = "relevance"
    NEWSWORTHINESS = "newsworthiness"
    ENTITIES = "entities"
    CLUSTER = "cluster"
    ENRICH = "enrich"
    SCORE = "score"
    PUBLISH = "publish"


class PairDecisionKind(StrEnum):
    DIRECT_MERGE = "direct_merge"
    DIRECT_SEPARATE = "direct_separate"
    MODEL_BOUNDARY = "model_boundary"


class EventCategory(StrEnum):
    PRODUCT_MODEL = "product_model"
    RESEARCH = "research"
    DEVELOPER_TOOL = "developer_tool"
    COMPANY = "company"


class EntityType(StrEnum):
    ORGANIZATION = "organization"
    PERSON = "person"
    PRODUCT = "product"
    MODEL = "model"
    PAPER = "paper"
    DATASET = "dataset"
    PROJECT = "project"


class RawItemText(_Schema):
    raw_item_id: int | None = None
    title: str = ""
    summary: str = ""
    content: str = ""
    item_kind: str | None = None
    publisher_name: str | None = None
    source_topics: tuple[str, ...] = ()


class RelevanceDecision(_Schema):
    is_relevant: bool
    outcome: Literal["included", "excluded"]
    score: int = Field(ge=0, le=100)
    topics: tuple[str, ...]
    reasons: tuple[str, ...]


class NewsworthinessDecision(_Schema):
    outcome: Literal["included", "excluded"]
    score: int = Field(ge=0, le=100)
    action: str | None = None
    reason_codes: tuple[str, ...]


class ExtractedEntity(_Schema):
    canonical_key: str
    name: str
    entity_type: EntityType
    aliases: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)


class ClusterItem(_Schema):
    raw_item_id: int
    evidence_role: EvidenceRole | None = None
    similarity: float = Field(default=0, ge=0, le=1)
    title: str = ""
    canonical_url: str | None = None
    canonical_url_hash: str | None = None
    original_url: str | None = None
    title_fingerprint: str | None = None
    entities: tuple[str, ...] = ()
    repository_id: str | None = None
    paper_id: str | None = None
    published_at: datetime | None = None
    source_nature: str | None = None
    source_roles: tuple[str, ...] = ()
    provider_category: str | None = None
    publisher_name: str | None = None


class ClusterDecision(_Schema):
    candidate_key: str = ""
    should_merge: bool = False
    confidence: float = Field(default=0, ge=0, le=1)
    matched: bool = False
    score: float = Field(default=0, ge=0, le=1)
    reasons: tuple[str, ...] = ()


class PairRuleDecision(_Schema):
    left_raw_item_id: int
    right_raw_item_id: int
    score: float = Field(ge=0, le=1)
    reasons: tuple[str, ...]
    structural_anchor: bool
    kind: PairDecisionKind


class PairFinalDecision(_Schema):
    left_raw_item_id: int
    right_raw_item_id: int
    input_fingerprint: str = Field(min_length=64, max_length=64)
    rule_score: float = Field(ge=0, le=1)
    rule_reasons: tuple[str, ...]
    decision: Literal["merge", "separate", "undetermined"]
    model_same_event: bool | None = None
    model_confidence: float | None = Field(default=None, ge=0, le=1)


class CandidateCluster(_Schema):
    candidate_key: str
    title: str = ""
    category: EventCategory | None = None
    items: tuple[ClusterItem, ...] = ()
    raw_item_ids: tuple[int, ...] = ()
    reasons: tuple[str, ...] = ()
    state: str = "active"
    metadata: dict = Field(default_factory=dict)
    # Source publication time is the event clock.  If a legacy item has no timestamp,
    # clustering supplies the fixed Unix-epoch fallback rather than processing time.
    occurred_at: datetime | None = None


class EvidenceAssessment(_Schema):
    raw_item_id: int | None = None
    role: EvidenceRole
    credibility: float = Field(default=0, ge=0, le=100)
    rationale: tuple[str, ...] = ()
    root_evidence_key: str = ""
    independent: bool = False
    limitations: tuple[str, ...] = ()


class EventScoreInput(_Schema):
    ai_relevance: float = Field(ge=0, le=100)
    source_coverage: float = Field(ge=0, le=100)
    source_authority: float = Field(ge=0, le=100)
    recency: float = Field(ge=0, le=100)
    engagement_velocity: float = Field(ge=0, le=100)
    novelty: float = Field(ge=0, le=100)
    evidence: tuple[EvidenceAssessment, ...] = ()
    reasons: tuple[str, ...] = ()


class ScoreBreakdown(_Schema):
    ai_relevance: float = Field(ge=0, le=100)
    source_coverage: float = Field(ge=0, le=100)
    source_authority: float = Field(ge=0, le=100)
    recency: float = Field(ge=0, le=100)
    engagement_velocity: float = Field(ge=0, le=100)
    novelty: float = Field(ge=0, le=100)
    importance: float = Field(ge=0, le=100)
    credibility: float = Field(ge=0, le=100)
    heat: float = Field(ge=0, le=100)
    rule_version: str
    reasons: tuple[str, ...]


class TierDecision(_Schema):
    tier: EventTier
    rank_score: float = Field(ge=0, le=100)
    reasons: tuple[str, ...]


class PublicationDecision(_Schema):
    status: EventStatus
    publish_to_top: bool
    reasons: tuple[str, ...] = ()

    @property
    def should_publish(self) -> bool:
        """Compatibility alias for callers that only need a publish gate."""
        return self.publish_to_top


class EventEnrichment(_Schema):
    zh_title: str
    zh_summary: str
    why_it_matters: str
    limitations: tuple[str, ...] = ()
    origin: Literal["model", "previous_version", "rule_fallback"]
    confidence: float = Field(ge=0, le=1)


class PairSemanticDecision(_Schema):
    """Advisory semantic comparison; deterministic clustering remains authoritative."""

    same_event: bool
    confidence: float = Field(ge=0, le=1)
    rationale: str
    origin: Literal["model", "rule_fallback"] = "rule_fallback"


class EntitySuggestions(_Schema):
    """Advisory entity candidates; deterministic entity validation remains authoritative."""

    entities: tuple[ExtractedEntity, ...] = ()
    confidence: float = Field(default=0, ge=0, le=1)
    origin: Literal["model", "rule_fallback"] = "rule_fallback"


class ConflictExplanation(_Schema):
    """Explanatory output only; it cannot alter evidence or publication decisions."""

    summary: str
    possible_causes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    origin: Literal["model", "rule_fallback"] = "rule_fallback"


class PublishedEvent(_Schema):
    event_id: int | None = None
    canonical_key: str
    status: EventStatus
    category: EventCategory | None = None
    occurred_at: datetime | None = None
    enrichment: EventEnrichment | None = None
    score: ScoreBreakdown | None = None
    evidence: tuple[EvidenceAssessment, ...] = ()
    source_item_ids: tuple[int, ...] = ()
