from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Schema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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
    ENTITIES = "entities"
    CLUSTER = "cluster"
    ENRICH = "enrich"
    SCORE = "score"
    PUBLISH = "publish"


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


class RelevanceDecision(_Schema):
    is_relevant: bool
    score: int = Field(ge=0, le=100)
    topics: tuple[str, ...]
    reasons: tuple[str, ...]


class ExtractedEntity(_Schema):
    canonical_key: str
    name: str
    entity_type: EntityType
    aliases: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)


class ClusterItem(_Schema):
    raw_item_id: int
    evidence_role: EvidenceRole | None = None
    similarity: float = Field(ge=0, le=1)


class ClusterDecision(_Schema):
    candidate_key: str
    should_merge: bool
    confidence: float = Field(ge=0, le=1)
    reasons: tuple[str, ...] = ()


class CandidateCluster(_Schema):
    candidate_key: str
    title: str = ""
    category: EventCategory | None = None
    items: tuple[ClusterItem, ...] = ()
    state: str = "active"
    metadata: dict = Field(default_factory=dict)


class EvidenceAssessment(_Schema):
    raw_item_id: int
    role: EvidenceRole
    credibility: float = Field(ge=0, le=100)
    rationale: tuple[str, ...] = ()


class EventScoreInput(_Schema):
    ai_relevance: float = Field(ge=0, le=100)
    source_coverage: float = Field(ge=0, le=100)
    source_authority: float = Field(ge=0, le=100)
    recency: float = Field(ge=0, le=100)
    engagement_velocity: float = Field(ge=0, le=100)
    novelty: float = Field(ge=0, le=100)
    importance: float = Field(ge=0, le=100)
    credibility: float = Field(ge=0, le=100)


class ScoreBreakdown(EventScoreInput):
    heat: float = Field(ge=0, le=100)
    reasons: tuple[str, ...]


class PublicationDecision(_Schema):
    should_publish: bool
    status: EventStatus
    reasons: tuple[str, ...] = ()


class EventEnrichment(_Schema):
    zh_title: str
    zh_summary: str
    why_it_matters: str
    limitations: tuple[str, ...] = ()
    origin: Literal["model", "previous_version", "rule_fallback"]
    confidence: float = Field(ge=0, le=1)


class PublishedEvent(_Schema):
    event_id: int | None = None
    canonical_key: str
    status: EventStatus
    category: EventCategory | None = None
    occurred_at: datetime | None = None
    enrichment: EventEnrichment | None = None
    score: ScoreBreakdown | None = None
    source_item_ids: tuple[int, ...] = ()
