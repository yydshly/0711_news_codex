from __future__ import annotations

from datetime import date
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    computed_field,
    field_validator,
    model_validator,
)

from newsradar.providers.schema import Availability, CoverageMode, TargetType


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    DEGRADED = "degraded"
    PAUSED = "paused"
    DISABLED = "disabled"


class SourceNature(StrEnum):
    FIRST_PARTY = "first_party"
    RESEARCH = "research"
    COMMUNITY = "community"
    PROFESSIONAL_MEDIA = "professional_media"
    AGGREGATOR = "aggregator"
    SOCIAL = "social"


class SourceRole(StrEnum):
    DISCOVERY = "discovery"
    EVIDENCE = "evidence"
    ENGAGEMENT = "engagement"
    CONTEXT = "context"


class AccessKind(StrEnum):
    RSS = "rss"
    ATOM = "atom"
    REST_API = "rest_api"
    PUBLIC_API = "public_api"
    HTML = "html"
    SITEMAP = "sitemap"


class ExpectedField(StrEnum):
    TITLE = "title"
    CANONICAL_URL = "canonical_url"
    PUBLISHED_AT = "published_at"
    UPDATED_AT = "updated_at"
    AUTHOR = "author"
    SUMMARY = "summary"
    CONTENT = "content"
    ENGAGEMENT = "engagement"
    DISCUSSION_URL = "discussion_url"


class AccessMethod(StrictModel):
    kind: AccessKind
    url: HttpUrl
    priority: int = Field(ge=1)
    requires_manual_approval: bool = False
    auth_env: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def validate_audited_url(cls, value: HttpUrl) -> HttpUrl:
        parsed = urlsplit(str(value))
        if parsed.scheme != "https":
            raise ValueError("Source URLs must use HTTPS")
        if parsed.username or parsed.password:
            raise ValueError("Credentials must not be embedded in source URLs")
        host = (parsed.hostname or "").lower()
        if host.endswith(".invalid") or host in {"example.com", "example.org", "example.net"}:
            raise ValueError("Placeholder and .invalid URLs are not audited sources")
        return value

    @field_validator("auth_env")
    @classmethod
    def validate_auth_env(cls, value: str | None) -> str | None:
        if value is not None and (not value.isupper() or not value.replace("_", "").isalnum()):
            raise ValueError("auth_env must be an uppercase environment variable name")
        return value

    @model_validator(mode="after")
    def require_manual_approval_for_html(self) -> AccessMethod:
        if self.kind == AccessKind.HTML and not self.requires_manual_approval:
            raise ValueError("HTML access requires manual approval")
        return self


class RiskAssessment(StrictModel):
    terms: int = Field(ge=0, le=5)
    authentication: int = Field(ge=0, le=5)
    stability: int = Field(ge=0, le=5)
    data_quality: int = Field(ge=0, le=5)
    operating_cost: int = Field(ge=0, le=5)
    evidence: list[HttpUrl] = Field(default_factory=list)
    hard_block_reason: str | None = None

    @computed_field
    @property
    def total(self) -> int:
        return (
            self.terms
            + self.authentication
            + self.stability
            + self.data_quality
            + self.operating_cost
        )


class IngestionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    approved_at: date | None = None
    max_items_per_run: int = Field(default=100, ge=1, le=500)


class SourceDefinition(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=120)
    provider_id: str = Field(default="independent", pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    target_type: TargetType = TargetType.PUBLISHER_FEED
    availability: Availability = Availability.READY
    coverage_mode: CoverageMode = CoverageMode.DIRECT
    official_identity_url: HttpUrl | None = None
    reviewed_at: date | None = None
    unlock_requirements: list[str] = Field(default_factory=list)
    status: SourceStatus
    nature: SourceNature
    roles: list[SourceRole] = Field(min_length=1)
    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    topics: list[str] = Field(min_length=1)
    authority_score: int = Field(ge=0, le=5)
    poll_interval_minutes: int = Field(ge=5, le=10080)
    access_methods: list[AccessMethod] = Field(min_length=1)
    expected_fields: list[ExpectedField] = Field(min_length=1)
    risk: RiskAssessment
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    notes: str | None = None

    @field_validator("access_methods")
    @classmethod
    def validate_priorities(cls, value: list[AccessMethod]) -> list[AccessMethod]:
        priorities = [method.priority for method in value]
        if len(priorities) != len(set(priorities)):
            raise ValueError("Access method priorities must be unique")
        return sorted(value, key=lambda method: method.priority)

    @model_validator(mode="after")
    def validate_social_role(self) -> SourceDefinition:
        if self.nature == SourceNature.SOCIAL and not {
            SourceRole.DISCOVERY,
            SourceRole.ENGAGEMENT,
        }.intersection(self.roles):
            raise ValueError("Social targets require a discovery or engagement role")
        return self

    @computed_field
    @property
    def total_risk(self) -> int:
        return self.risk.total
