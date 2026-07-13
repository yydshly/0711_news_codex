from __future__ import annotations

import re
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


def reject_embedded_url_credentials(value: HttpUrl) -> HttpUrl:
    parsed = urlsplit(str(value))
    if parsed.username or parsed.password:
        raise ValueError("URL 不得内嵌凭据")
    return value


class ResearchStatus(StrEnum):
    VERIFIED = "verified"
    NEEDS_RESEARCH = "needs_research"
    PLACEHOLDER = "placeholder"
    DUPLICATE = "duplicate"
    RETIRED = "retired"


class AcquisitionKind(StrEnum):
    RSS = "rss"
    ATOM = "atom"
    WEBSUB = "websub"
    PUBLIC_API = "public_api"
    API_KEY_API = "api_key_api"
    OAUTH_API = "oauth_api"
    SITEMAP = "sitemap"
    HTML = "html"
    JSON_LD = "json_ld"
    EMBEDDED_JSON = "embedded_json"
    LIBRARY = "library"
    AGGREGATOR = "aggregator"
    MANUAL = "manual"


class Officiality(StrEnum):
    OFFICIAL = "official"
    DOCUMENTED_PUBLIC = "documented_public"
    UNOFFICIAL_LIBRARY = "unofficial_library"
    THIRD_PARTY_SERVICE = "third_party_service"


class AcquisitionAuth(StrEnum):
    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"
    APPROVAL = "approval"
    PAYMENT = "payment"
    LOGIN_COOKIE = "login_cookie"


class AcquisitionRole(StrEnum):
    DISCOVERY = "discovery"
    METADATA = "metadata"
    CONTENT = "content"
    ENGAGEMENT = "engagement"
    TRANSCRIPT = "transcript"
    EVIDENCE = "evidence"


class AcquisitionDecision(StrEnum):
    PRIMARY = "primary"
    SUPPLEMENT = "supplement"
    FALLBACK = "fallback"
    MANUAL_ONLY = "manual_only"
    REJECTED = "rejected"


class SampleStatus(StrEnum):
    NOT_RUN = "not_run"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class AcquisitionImplementation(StrEnum):
    FEEDPARSER = "feedparser"
    HTTPX = "httpx"
    YOUTUBE_CHANNEL_FEED = "youtube-channel-feed"
    YOUTUBE_DATA_API = "youtube-data-api"
    YOUTUBE_TRANSCRIPT_API = "youtube-transcript-api"
    MANUAL_REVIEW = "manual-review"


class AcquisitionCandidate(StrictModel):
    key: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    kind: AcquisitionKind
    implementation: AcquisitionImplementation
    officiality: Officiality
    authentication: AcquisitionAuth
    roles: tuple[AcquisitionRole, ...] = Field(min_length=1)
    fields: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...]
    evidence: tuple[HttpUrl, ...] = Field(min_length=1)
    reviewed_at: date
    sample_status: SampleStatus
    decision: AcquisitionDecision
    selector: str | None = Field(default=None, max_length=128)
    allowed_redirect_hosts: tuple[str, ...] = ()

    @field_validator("selector")
    @classmethod
    def validate_static_html_selector(cls, value: str | None) -> str | None:
        """Allow only an auditable, single static CSS selector token."""
        if value is None:
            return value
        if not re.fullmatch(
            r"(?:[A-Za-z][A-Za-z0-9-]*|#[A-Za-z][A-Za-z0-9_-]*|\.[A-Za-z][A-Za-z0-9_-]*)",
            value,
        ):
            raise ValueError("selector must be one simple CSS tag, #id, or .class")
        return value

    @field_validator("allowed_redirect_hosts")
    @classmethod
    def validate_allowed_redirect_hosts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.rstrip(".").lower() for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed_redirect_hosts must not contain duplicates")
        for value in normalized:
            if not re.fullmatch(r"[a-z0-9.-]+", value) or ".." in value:
                raise ValueError("allowed_redirect_hosts must contain hostnames only")
        return normalized

    @field_validator("evidence")
    @classmethod
    def validate_evidence_urls(cls, values: tuple[HttpUrl, ...]) -> tuple[HttpUrl, ...]:
        for value in values:
            parsed = urlsplit(str(value))
            if parsed.scheme != "https":
                raise ValueError("研究证据 URL 必须使用 HTTPS")
            if parsed.username or parsed.password:
                raise ValueError("研究证据 URL 不得内嵌凭据")
        return values

    @model_validator(mode="after")
    def reject_login_cookie_candidate(self) -> AcquisitionCandidate:
        if (
            self.authentication == AcquisitionAuth.LOGIN_COOKIE
            and self.decision != AcquisitionDecision.REJECTED
        ):
            raise ValueError("使用登录 Cookie 的候选方案只能标记为 rejected")
        return self


class SourceResearchProfile(StrictModel):
    status: ResearchStatus = ResearchStatus.NEEDS_RESEARCH
    purpose: str | None = None
    wanted_information: tuple[str, ...] = ()
    candidates: tuple[AcquisitionCandidate, ...] = ()
    conclusion: str | None = None
    risk_conclusion: str | None = None
    no_fallback_reason: str | None = None
    reviewed_at: date | None = None

    @model_validator(mode="after")
    def validate_verified_profile(self) -> SourceResearchProfile:
        if self.status != ResearchStatus.VERIFIED:
            return self
        if not self.purpose or not self.purpose.strip():
            raise ValueError("已验证研究档案必须说明用途")
        if not self.risk_conclusion or not self.risk_conclusion.strip():
            raise ValueError("已验证研究档案必须包含风险结论")
        if not self.wanted_information:
            raise ValueError("已验证研究档案必须说明所需信息")
        primary_candidates = tuple(
            candidate
            for candidate in self.candidates
            if candidate.decision == AcquisitionDecision.PRIMARY
        )
        if not primary_candidates:
            raise ValueError("已验证研究档案必须包含 primary 候选方案")
        if not all(
            candidate.sample_status in {SampleStatus.SUCCEEDED, SampleStatus.PARTIAL}
            and candidate.evidence
            for candidate in primary_candidates
        ):
            raise ValueError("primary 候选方案必须各自包含成功样本和证据 URL")
        if not any(
            candidate.decision == AcquisitionDecision.FALLBACK for candidate in self.candidates
        ):
            if not self.no_fallback_reason or not self.no_fallback_reason.strip():
                raise ValueError("缺少 fallback 候选方案时必须说明原因")
        return self


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
    auth_envs: tuple[str, ...] = Field(default_factory=tuple)
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_auth_env(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        legacy = data.pop("auth_env", None)
        if "auth_envs" not in data and legacy is not None:
            data["auth_envs"] = [legacy]
        if isinstance(data.get("auth_envs"), str):
            data["auth_envs"] = [data["auth_envs"]]
        return data

    @field_validator("url")
    @classmethod
    def validate_audited_url(cls, value: HttpUrl) -> HttpUrl:
        parsed = urlsplit(str(value))
        if parsed.scheme != "https":
            raise ValueError("Source URLs must use HTTPS")
        reject_embedded_url_credentials(value)
        host = (parsed.hostname or "").lower()
        if host.endswith(".invalid") or host in {"example.com", "example.org", "example.net"}:
            raise ValueError("Placeholder and .invalid URLs are not audited sources")
        return value

    @field_validator("auth_envs")
    @classmethod
    def validate_auth_envs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("auth_envs must not contain duplicates")
        for name in value:
            if not name.isupper() or not name.replace("_", "").isalnum():
                raise ValueError("auth_envs must contain uppercase environment variable names")
        return value

    @property
    def auth_env(self) -> str | None:
        """Compatibility view for one-credential callers during the v1.1 migration."""
        return self.auth_envs[0] if len(self.auth_envs) == 1 else None

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

    @field_validator("evidence")
    @classmethod
    def validate_evidence_urls(cls, values: list[HttpUrl]) -> list[HttpUrl]:
        return [reject_embedded_url_credentials(value) for value in values]

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

    @model_validator(mode="after")
    def require_approval_for_enabled_ingestion(self) -> IngestionConfig:
        if self.enabled and self.approved_at is None:
            raise ValueError("enabled ingestion requires approved_at")
        return self


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
    research: SourceResearchProfile = Field(default_factory=SourceResearchProfile)
    notes: str | None = None

    @field_validator("official_identity_url")
    @classmethod
    def validate_official_identity_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is None:
            return value
        return reject_embedded_url_credentials(value)

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
