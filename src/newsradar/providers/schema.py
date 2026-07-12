from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderCategory(StrEnum):
    SOCIAL_COMMUNITY = "social_community"
    PROFESSIONAL_MEDIA = "professional_media"
    FIRST_PARTY = "first_party"
    AGGREGATOR_SEARCH = "aggregator_search"
    RESEARCH_DEVELOPER = "research_developer"
    NEWSLETTER_PODCAST = "newsletter_podcast"
    TREND_BUSINESS = "trend_business"


class TargetType(StrEnum):
    PUBLISHER_FEED = "publisher_feed"
    ACCOUNT = "account"
    CHANNEL = "channel"
    KEYWORD = "keyword"
    TOPIC = "topic"
    COMMUNITY = "community"
    SEARCH_QUERY = "search_query"
    TREND = "trend"
    MARKET = "market"


class Availability(StrEnum):
    READY = "ready"
    REQUIRES_CREDENTIALS = "requires_credentials"
    REQUIRES_APPROVAL = "requires_approval"
    REQUIRES_PAYMENT = "requires_payment"
    MANUAL_ONLY = "manual_only"
    UNAVAILABLE = "unavailable"


class CoverageMode(StrEnum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    CATALOG_ONLY = "catalog_only"


class AuthMode(StrEnum):
    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"
    APPROVAL = "approval"
    PAID = "paid"
    MANUAL = "manual"


class CostTier(StrEnum):
    FREE = "free"
    FREE_QUOTA = "free_quota"
    FREEMIUM = "freemium"
    PAID = "paid"
    ENTERPRISE = "enterprise"
    UNKNOWN = "unknown"


class ProviderDefinition(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=120)
    category: ProviderCategory
    homepage: HttpUrl
    docs_url: HttpUrl
    terms_url: HttpUrl
    auth_mode: AuthMode
    cost_tier: CostTier
    availability: Availability
    capabilities: list[str] = Field(min_length=1)
    required_env: list[str] = Field(default_factory=list)
    reviewed_at: date
    evidence: list[HttpUrl] = Field(min_length=1)
    unlock_requirements: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("homepage", "docs_url", "terms_url")
    @classmethod
    def require_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("Provider URLs must use HTTPS")
        return value

    @field_validator("evidence")
    @classmethod
    def require_https_evidence(cls, values: list[HttpUrl]) -> list[HttpUrl]:
        if any(value.scheme != "https" for value in values):
            raise ValueError("Provider evidence URLs must use HTTPS")
        return values

    @field_validator("required_env")
    @classmethod
    def validate_required_env(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.isupper() or not value.replace("_", "").isalnum():
                raise ValueError("required_env values must be uppercase environment names")
        return values
