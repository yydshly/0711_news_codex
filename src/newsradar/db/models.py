from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class SourceDefinitionRecord(Base):
    __tablename__ = "source_definitions"
    __table_args__ = (
        CheckConstraint(
            "catalog_state IN ('current', 'archived')",
            name="ck_source_definitions_catalog_state",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(120), nullable=False, default="independent")
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, default="publisher_feed")
    availability: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    coverage_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="direct")
    official_identity_url: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[date | None] = mapped_column(Date)
    unlock_requirements: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    nature: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    topics: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    authority_score: Mapped[int] = mapped_column(Integer, nullable=False)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    catalog_state: Mapped[str] = mapped_column(String(16), nullable=False, default="current")
    catalog_archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    catalog_archive_reason: Mapped[str | None] = mapped_column(String(120))
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    access_methods: Mapped[list[SourceAccessMethodRecord]] = relationship(
        cascade="all, delete-orphan", back_populates="source"
    )
    versions: Mapped[list[SourceDefinitionVersion]] = relationship(
        cascade="all, delete-orphan", back_populates="source"
    )
    risks: Mapped[list[SourceRiskAssessmentRecord]] = relationship(
        cascade="all, delete-orphan", back_populates="source"
    )
    research_profile: Mapped[SourceResearchProfileRecord | None] = relationship(
        cascade="all, delete-orphan", back_populates="source", uselist=False
    )
    acquisition_candidates: Mapped[list[SourceAcquisitionCandidateRecord]] = relationship(
        cascade="all, delete-orphan", back_populates="source"
    )


class ProviderDefinitionRecord(Base):
    __tablename__ = "source_providers"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    homepage: Mapped[str] = mapped_column(Text, nullable=False)
    docs_url: Mapped[str] = mapped_column(Text, nullable=False)
    terms_url: Mapped[str] = mapped_column(Text, nullable=False)
    auth_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    cost_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    availability: Mapped[str] = mapped_column(String(32), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    required_env: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reviewed_at: Mapped[date] = mapped_column(Date, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    unlock_requirements: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderDefinitionVersion(Base):
    __tablename__ = "source_provider_versions"
    __table_args__ = (UniqueConstraint("provider_id", "definition_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("source_providers.id"), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderProbeRunRecord(Base):
    __tablename__ = "source_provider_probe_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    operation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="SET NULL"), index=True
    )
    provider_id: Mapped[str] = mapped_column(ForeignKey("source_providers.id"), nullable=False)
    probe_type: Mapped[str] = mapped_column(String(32), nullable=False, default="capability")
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    availability: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    http_status: Mapped[int | None] = mapped_column(Integer)
    evidence_url: Mapped[str] = mapped_column(Text, nullable=False)


class SourceDefinitionVersion(Base):
    __tablename__ = "source_definition_versions"
    __table_args__ = (UniqueConstraint("source_id", "definition_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_definitions.id"), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source: Mapped[SourceDefinitionRecord] = relationship(back_populates="versions")


class SourceResearchProfileRecord(Base):
    __tablename__ = "source_research_profiles"

    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_definitions.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    wanted_information: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    conclusion: Mapped[str | None] = mapped_column(Text)
    no_fallback_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[date | None] = mapped_column(Date)

    source: Mapped[SourceDefinitionRecord] = relationship(back_populates="research_profile")


class SourceAcquisitionCandidateRecord(Base):
    __tablename__ = "source_acquisition_candidates"
    __table_args__ = (
        UniqueConstraint("source_id", "candidate_key"),
        Index("ix_source_acquisition_candidates_current", "source_id", "is_current"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_key: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    implementation: Mapped[str] = mapped_column(String(64), nullable=False)
    officiality: Mapped[str] = mapped_column(String(32), nullable=False)
    authentication: Mapped[str] = mapped_column(String(32), nullable=False)
    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    fields: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    sample_status: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewed_at: Mapped[date] = mapped_column(Date, nullable=False)
    selector: Mapped[str | None] = mapped_column(String(128))
    allowed_redirect_hosts: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped[SourceDefinitionRecord] = relationship(back_populates="acquisition_candidates")
    probe_runs: Mapped[list[SourceAcquisitionProbeRunRecord]] = relationship(
        back_populates="candidate"
    )


class SourceAcquisitionProbeRunRecord(Base):
    __tablename__ = "source_acquisition_probe_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("source_acquisition_candidates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    operation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="SET NULL"), index=True
    )
    original_probe_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_probe_runs.id", ondelete="SET NULL"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    fields_present: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sample_count: Mapped[int | None] = mapped_column(Integer)
    latest_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    retry_after_seconds: Mapped[float | None] = mapped_column(Float)
    earliest_recheck_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    candidate: Mapped[SourceAcquisitionCandidateRecord] = relationship(back_populates="probe_runs")


class SourceAccessMethodRecord(Base):
    __tablename__ = "source_access_methods"
    __table_args__ = (UniqueConstraint("source_id", "priority"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_definitions.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    requires_manual_approval: Mapped[bool] = mapped_column(default=False)
    auth_env: Mapped[str | None] = mapped_column(String(120))
    auth_envs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    headers: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    params: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)

    source: Mapped[SourceDefinitionRecord] = relationship(back_populates="access_methods")


class SourceRiskAssessmentRecord(Base):
    __tablename__ = "source_risk_assessments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_definitions.id"), nullable=False)
    terms: Mapped[int] = mapped_column(Integer, nullable=False)
    authentication: Mapped[int] = mapped_column(Integer, nullable=False)
    stability: Mapped[int] = mapped_column(Integer, nullable=False)
    data_quality: Mapped[int] = mapped_column(Integer, nullable=False)
    operating_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    hard_block_reason: Mapped[str | None] = mapped_column(Text)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source: Mapped[SourceDefinitionRecord] = relationship(back_populates="risks")


class SourceProbeRunRecord(Base):
    __tablename__ = "source_probe_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    operation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="SET NULL"), index=True
    )
    remediation_acquisition_probe_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_acquisition_probe_runs.id", ondelete="SET NULL"), index=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("source_definitions.id"), nullable=False)
    access_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    access_url: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    http_status: Mapped[int | None] = mapped_column(Integer)
    final_url: Mapped[str | None] = mapped_column(Text)
    response_headers: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64))
    suggested_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))


class SourceProbeSampleRecord(Base):
    __tablename__ = "source_probe_samples"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    probe_run_id: Mapped[int] = mapped_column(ForeignKey("source_probe_runs.id"), nullable=False)
    sample_index: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fields_present: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    sample_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class SourceRemediationBatchRecord(Base):
    __tablename__ = "source_remediation_batches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    baseline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, unique=True
    )
    before_trial_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceRemediationMemberRecord(Base):
    __tablename__ = "source_remediation_members"
    __table_args__ = (
        UniqueConstraint("batch_id", "source_id"),
        UniqueConstraint("batch_id", "original_probe_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("source_remediation_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(120), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    original_probe_id: Mapped[int] = mapped_column(
        ForeignKey("source_probe_runs.id", ondelete="RESTRICT"), nullable=False
    )
    original_finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_zh: Mapped[str] = mapped_column(Text, nullable=False)
    next_action_zh: Mapped[str] = mapped_column(Text, nullable=False)
    access_url: Mapped[str | None] = mapped_column(Text)


class FetchRunRecord(Base):
    __tablename__ = "fetch_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_definitions.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(32), default="pending")
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    operation_run_id: Mapped[int | None] = mapped_column(ForeignKey("operation_runs.id"))
    operation_attempt_id: Mapped[int | None] = mapped_column(ForeignKey("operation_attempts.id"))
    access_method_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_access_methods.id", ondelete="SET NULL")
    )
    http_status: Mapped[int | None] = mapped_column(Integer)
    final_url: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(String(512))
    last_modified: Mapped[str | None] = mapped_column(String(512))
    items_received: Mapped[int | None] = mapped_column(Integer)
    items_inserted: Mapped[int | None] = mapped_column(Integer)
    items_updated: Mapped[int | None] = mapped_column(Integer)
    items_unchanged: Mapped[int | None] = mapped_column(Integer)
    items_skipped: Mapped[int | None] = mapped_column(Integer)
    items_failed: Mapped[int | None] = mapped_column(Integer)
    next_cursor: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)


class RawItemRecord(Base):
    __tablename__ = "raw_items"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id"),
        Index("ix_raw_items_source_published_at", "source_id", "published_at"),
        Index("ix_raw_items_canonical_url_hash", "canonical_url_hash"),
        Index("ix_raw_items_title_fingerprint", "title_fingerprint"),
        Index(
            "ix_raw_items_title_fingerprint_published_at",
            "title_fingerprint",
            "published_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_definitions.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    original_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list[str] | None] = mapped_column(JSON)
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    content_type: Mapped[str | None] = mapped_column(String(64))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discussion_url: Mapped[str | None] = mapped_column(Text)
    engagement: Mapped[dict | None] = mapped_column(JSON)
    item_kind: Mapped[str | None] = mapped_column(String(64))
    publisher_name: Mapped[str | None] = mapped_column(String(255))
    publisher_url: Mapped[str | None] = mapped_column(Text)
    discovery_url: Mapped[str | None] = mapped_column(Text)
    origin_resolution_status: Mapped[str | None] = mapped_column(String(32))
    author_account_id: Mapped[str | None] = mapped_column(String(255))
    author_handle: Mapped[str | None] = mapped_column(String(255))
    thread_root_id: Mapped[str | None] = mapped_column(String(255))
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    title_fingerprint: Mapped[str | None] = mapped_column(String(64))
    canonical_url_hash: Mapped[str | None] = mapped_column(String(64))
    first_seen_run_id: Mapped[int | None] = mapped_column(ForeignKey("fetch_runs.id"))
    last_seen_run_id: Mapped[int | None] = mapped_column(ForeignKey("fetch_runs.id"))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkerRecord(Base):
    __tablename__ = "workers"

    worker_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    process_id: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_operation_run_id: Mapped[int | None] = mapped_column(Integer)


class OperationRunRecord(Base):
    __tablename__ = "operation_runs"
    __table_args__ = (
        Index("ix_operation_runs_queue", "status", "next_attempt_at"),
        Index("ix_operation_runs_lease_expires_at", "lease_expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int | None] = mapped_column(Integer)
    result_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workers.worker_id"))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyAutopilotRunRecord(Base):
    __tablename__ = "daily_autopilot_runs"
    __table_args__ = (
        CheckConstraint("window_hours IN (24, 48, 72)", name="ck_daily_autopilot_window"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_daily_autopilot_status",
        ),
        Index("ix_daily_autopilot_runs_created_at", "created_at"),
        Index("ix_daily_autopilot_runs_source_operation", "source_operation_id"),
        Index("ix_daily_autopilot_runs_event_operation", "event_operation_id"),
        Index("ix_daily_autopilot_runs_decision_audio", "decision_audio_operation_id"),
        Index("ix_daily_autopilot_runs_overview_audio", "overview_audio_operation_id"),
        Index("ix_daily_autopilot_runs_daily_report", "daily_report_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(48), nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="RESTRICT")
    )
    event_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="RESTRICT")
    )
    decision_audio_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="RESTRICT")
    )
    overview_audio_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="RESTRICT")
    )
    daily_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="RESTRICT")
    )
    result_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(96))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailyAutomationConfigRecord(Base):
    __tablename__ = "daily_automation_config"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_daily_automation_singleton"),
        CheckConstraint("window_hours = 24", name="ck_daily_automation_window"),
        CheckConstraint(
            "resource_profile IN ('standard', 'power_saver')",
            name="ck_daily_automation_resource_profile",
        ),
        Index("ix_daily_automation_next_run", "enabled", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    daily_time: Mapped[str] = mapped_column(String(5), nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    resource_profile: Mapped[str] = mapped_column(String(16), nullable=False)
    last_scheduled_date: Mapped[date | None] = mapped_column(Date)
    last_retention_date: Mapped[date | None] = mapped_column(Date)
    last_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_autopilot_runs.id", ondelete="SET NULL")
    )
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceCatalogRefreshMemberRecord(Base):
    __tablename__ = "source_catalog_refresh_members"
    __table_args__ = (
        UniqueConstraint("operation_run_id", "source_id"),
        Index("ix_source_catalog_refresh_members_operation_state", "operation_run_id", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    operation_run_id: Mapped[int] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(String(120), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_definition_hash: Mapped[str | None] = mapped_column(String(64))
    availability_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage_mode_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    access_kind_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    lane: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    result_code: Mapped[str | None] = mapped_column(String(64))
    conclusion: Mapped[str | None] = mapped_column(Text)
    content_probe_run_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    provider_probe_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_provider_probe_runs.id", ondelete="SET NULL")
    )
    claim_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_attempts.id", ondelete="SET NULL")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HighValueWaveMemberRecord(Base):
    __tablename__ = "high_value_wave_members"
    __table_args__ = (
        UniqueConstraint("operation_run_id", "source_id"),
        Index("ix_high_value_wave_member_state", "operation_run_id", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    operation_run_id: Mapped[int] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(String(120), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Evidence attribution must survive a later catalog edit.  The wave event
    # manifest reads this value, never the live source definition.
    nature_snapshot: Mapped[str] = mapped_column(
        String(32), nullable=False, default="community"
    )
    roles_snapshot: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    availability_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    access_kind_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    fetchable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    fetch_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("fetch_runs.id", ondelete="SET NULL")
    )
    result_code: Mapped[str | None] = mapped_column(String(64))
    conclusion: Mapped[str | None] = mapped_column(Text)
    claim_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_attempts.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationAttemptRecord(Base):
    __tablename__ = "operation_attempts"
    __table_args__ = (UniqueConstraint("operation_run_id", "attempt_number"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    operation_run_id: Mapped[int] = mapped_column(ForeignKey("operation_runs.id"), nullable=False)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.worker_id"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)


class OperationEventRecord(Base):
    __tablename__ = "operation_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    operation_run_id: Mapped[int] = mapped_column(ForeignKey("operation_runs.id"), nullable=False)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("operation_attempts.id"))
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    phase: Mapped[str | None] = mapped_column(String(64))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("source_definitions.id"))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RawItemSnapshotRecord(Base):
    __tablename__ = "raw_item_snapshots"
    __table_args__ = (UniqueConstraint("raw_item_id", "content_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    fetch_run_id: Mapped[int | None] = mapped_column(ForeignKey("fetch_runs.id"))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FetchRunItemRecord(Base):
    __tablename__ = "fetch_run_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fetch_run_id: Mapped[int] = mapped_column(ForeignKey("fetch_runs.id"), nullable=False)
    raw_item_id: Mapped[int | None] = mapped_column(ForeignKey("raw_items.id"))
    external_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DuplicateCandidateRecord(Base):
    __tablename__ = "duplicate_candidates"
    __table_args__ = (UniqueConstraint("raw_item_id", "candidate_raw_item_id", "match_type"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    candidate_raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    match_type: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceFetchStateRecord(Base):
    __tablename__ = "source_fetch_states"
    __table_args__ = (UniqueConstraint("source_id", "access_method_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_definitions.id"), nullable=False)
    access_method_id: Mapped[int] = mapped_column(
        ForeignKey("source_access_methods.id"), nullable=False
    )
    etag: Mapped[str | None] = mapped_column(String(512))
    last_modified: Mapped[str | None] = mapped_column(String(512))
    cursor: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelUsageRecord(Base):
    __tablename__ = "model_usage"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RawItemProcessingRecord(Base):
    __tablename__ = "raw_item_processing"
    __table_args__ = (UniqueConstraint("raw_item_id", "stage", "algorithm_version"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(120), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(16))
    score: Mapped[int | None] = mapped_column(Integer)
    reason_codes: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    details: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventCandidateRecord(Base):
    __tablename__ = "event_candidates"
    __table_args__ = (
        UniqueConstraint("candidate_key", "algorithm_version"),
        Index("ix_event_candidates_state", "state", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    candidate_key: Mapped[str] = mapped_column(String(255), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventCandidateItemRecord(Base):
    __tablename__ = "event_candidate_items"
    __table_args__ = (
        UniqueConstraint("candidate_id", "raw_item_id"),
        Index("ix_event_candidate_items_active", "candidate_id", "raw_item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("event_candidates.id"), nullable=False)
    raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventRecord(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_status_occurred_at", "status", "occurred_at"),
        Index(
            "ix_events_visibility_status_occurred_at",
            "visibility",
            "status",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    canonical_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="current", server_default="current"
    )
    display_tier: Mapped[str] = mapped_column(
        String(16), nullable=False, default="signal", server_default="signal"
    )
    rank_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str | None] = mapped_column(String(32))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_operation_id: Mapped[int | None] = mapped_column(ForeignKey("operation_runs.id"))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventMergeCandidateRecord(Base):
    __tablename__ = "event_merge_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["left_event_id", "left_version_number"],
            ["event_versions.event_id", "event_versions.version_number"],
            name="fk_event_merge_left_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["right_event_id", "right_version_number"],
            ["event_versions.event_id", "event_versions.version_number"],
            name="fk_event_merge_right_version",
            ondelete="RESTRICT",
        ),
        CheckConstraint("left_event_id < right_event_id", name="ck_event_merge_pair_order"),
        CheckConstraint("left_version_number > 0", name="ck_event_merge_left_version"),
        CheckConstraint("right_version_number > 0", name="ck_event_merge_right_version"),
        CheckConstraint("revision > 0", name="ck_event_merge_candidate_revision"),
        CheckConstraint(
            "candidate_type IN ('legacy_identity','deterministic_merge','manual_review')",
            name="ck_event_merge_candidate_type",
        ),
        CheckConstraint(
            "status IN ('pending','confirmed','dismissed','applied','expired','failed')",
            name="ck_event_merge_candidate_status",
        ),
        UniqueConstraint(
            "left_event_id",
            "left_version_number",
            "right_event_id",
            "right_version_number",
            "algorithm_version",
            "input_fingerprint",
            "revision",
            name="uq_event_merge_candidate_input",
        ),
        UniqueConstraint(
            "supersedes_candidate_id", name="uq_event_merge_candidate_supersedes"
        ),
        Index(
            "uq_event_merge_candidate_root",
            "left_event_id",
            "left_version_number",
            "right_event_id",
            "right_version_number",
            "algorithm_version",
            unique=True,
            sqlite_where=text("supersedes_candidate_id IS NULL"),
            postgresql_where=text("supersedes_candidate_id IS NULL"),
        ),
        Index("ix_event_merge_candidates_status_type", "status", "candidate_type", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    supersedes_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "event_merge_candidates.id",
            name="fk_event_merge_supersedes",
            ondelete="RESTRICT",
        )
    )
    left_event_id: Mapped[int] = mapped_column(Integer, nullable=False)
    left_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    right_event_id: Mapped[int] = mapped_column(Integer, nullable=False)
    right_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    algorithm_version: Mapped[str] = mapped_column(String(120), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    facts_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    zh_reason: Mapped[str] = mapped_column(Text, nullable=False)
    zh_next_action: Mapped[str] = mapped_column(Text, nullable=False)
    generated_operation_id: Mapped[int] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="RESTRICT")
    )
    applied_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_summary: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyReportRecord(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (
        CheckConstraint("window_hours IN (24, 48, 72)", name="ck_daily_report_window"),
        CheckConstraint("status IN ('draft', 'archived')", name="ck_daily_report_status"),
        CheckConstraint("revision > 0", name="ck_daily_report_revision"),
        UniqueConstraint(
            "report_date", "window_hours", "revision", name="uq_daily_report_revision"
        ),
        Index("ix_daily_reports_date_status", "report_date", "status"),
        Index("ix_daily_reports_deleted_purge", "deleted_at", "purge_after"),
        Index("ix_daily_reports_pinned_date", "pinned_at", "report_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_operation_id: Mapped[int] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="RESTRICT")
    )
    generation_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailyReportItemRecord(Base):
    __tablename__ = "daily_report_items"
    __table_args__ = (
        CheckConstraint(
            "section IN ('confirmed', 'emerging')", name="ck_daily_report_item_section"
        ),
        CheckConstraint("position > 0", name="ck_daily_report_item_position"),
        UniqueConstraint(
            "daily_report_id",
            "event_id",
            "event_version_number",
            name="uq_daily_report_event_version",
        ),
        UniqueConstraint(
            "daily_report_id", "section", "position", name="uq_daily_report_position"
        ),
        Index(
            "ix_daily_report_items_report_section",
            "daily_report_id",
            "section",
            "position",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    daily_report_id: Mapped[int] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )
    event_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    included: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)


class DailyReportOverviewItemRecord(Base):
    __tablename__ = "daily_report_overview_items"
    __table_args__ = (
        CheckConstraint("position > 0", name="ck_daily_report_overview_position"),
        UniqueConstraint(
            "daily_report_id",
            "event_id",
            "event_version_number",
            name="uq_daily_report_overview_event_version",
        ),
        UniqueConstraint(
            "daily_report_id",
            "position",
            name="uq_daily_report_overview_position",
        ),
        Index(
            "ix_daily_report_overview_report_position",
            "daily_report_id",
            "position",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    daily_report_id: Mapped[int] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )
    event_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    decision_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_report_items.id", ondelete="SET NULL")
    )


class DailyReportItemEditorialReviewRecord(Base):
    __tablename__ = "daily_report_item_editorial_reviews"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_daily_report_editorial_revision"),
        CheckConstraint(
            "decision IN ('keep', 'needs_evidence', 'exclude', 'duplicate')",
            name="ck_daily_report_editorial_decision",
        ),
        UniqueConstraint(
            "daily_report_item_id",
            "revision",
            name="uq_daily_report_editorial_item_revision",
        ),
        Index(
            "ix_daily_report_editorial_reviews_item_revision",
            "daily_report_item_id",
            "revision",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    daily_report_item_id: Mapped[int] = mapped_column(
        ForeignKey("daily_report_items.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    zh_title: Mapped[str] = mapped_column(Text, nullable=False)
    zh_summary: Mapped[str] = mapped_column(Text, nullable=False)
    review_recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    copied_from_editorial_review_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_report_item_editorial_reviews.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DailyReportOverviewEditorialReviewRecord(Base):
    __tablename__ = "daily_report_overview_editorial_reviews"
    __table_args__ = (
        CheckConstraint(
            "revision > 0", name="ck_daily_report_overview_review_revision"
        ),
        CheckConstraint(
            "decision IN ('keep', 'needs_evidence', 'exclude', 'duplicate')",
            name="ck_daily_report_overview_review_decision",
        ),
        UniqueConstraint(
            "daily_report_overview_item_id",
            "revision",
            name="uq_daily_report_overview_review_item_revision",
        ),
        Index(
            "ix_daily_report_overview_reviews_item_revision",
            "daily_report_overview_item_id",
            "revision",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    daily_report_overview_item_id: Mapped[int] = mapped_column(
        ForeignKey("daily_report_overview_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    zh_title: Mapped[str] = mapped_column(Text, nullable=False)
    zh_summary: Mapped[str] = mapped_column(Text, nullable=False)
    review_recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    duplicate_of_overview_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_report_overview_items.id", ondelete="RESTRICT")
    )
    copied_from_editorial_review_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_report_overview_editorial_reviews.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DailyReportAudioArtifactRecord(Base):
    __tablename__ = "daily_report_audio_artifacts"
    __table_args__ = (
        CheckConstraint(
            "rendition IN ('decision', 'overview')",
            name="ck_daily_report_audio_artifact_rendition",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_daily_report_audio_artifact_status",
        ),
        Index(
            "ix_daily_report_audio_artifacts_report_rendition",
            "daily_report_id",
            "rendition",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    daily_report_id: Mapped[int] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False
    )
    rendition: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    script: Mapped[str] = mapped_column(Text, nullable=False)
    script_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    voice_id: Mapped[str] = mapped_column(String(120), nullable=False)
    audio_format: Mapped[str] = mapped_column(String(16), nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    bitrate: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("operation_runs.id", ondelete="RESTRICT")
    )
    trace_id: Mapped[str | None] = mapped_column(String(128))
    audio_duration_ms: Mapped[int | None] = mapped_column(Integer)
    audio_size_bytes: Mapped[int | None] = mapped_column(Integer)
    relative_audio_path: Mapped[str | None] = mapped_column(String(512))
    audio_sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class EventVersionRecord(Base):
    __tablename__ = "event_versions"
    __table_args__ = (UniqueConstraint("event_id", "version_number"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    zh_title: Mapped[str | None] = mapped_column(Text)
    zh_summary: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventItemRecord(Base):
    __tablename__ = "event_items"
    __table_args__ = (
        UniqueConstraint("event_id", "raw_item_id", "added_version_number"),
        Index(
            "ix_event_items_active_membership",
            "event_id",
            "removed_version_number",
            "raw_item_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    added_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    removed_version_number: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EntityRecord(Base):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("canonical_key", "entity_type"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    canonical_key: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventEntityRecord(Base):
    __tablename__ = "event_entities"
    __table_args__ = (UniqueConstraint("event_id", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventScoreRecord(Base):
    __tablename__ = "event_scores"
    __table_args__ = (Index("ix_event_scores_ranking", "heat", "event_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    heat: Mapped[float] = mapped_column(Float, nullable=False)
    breakdown: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # This is the immutable logical event snapshot clock.  It deliberately differs
    # from created_at, which only records when a retry reached the database.
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventModelRunRecord(Base):
    __tablename__ = "event_model_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"))
    raw_item_id: Mapped[int | None] = mapped_column(ForeignKey("raw_items.id"))
    model_usage_id: Mapped[int | None] = mapped_column(ForeignKey("model_usage.id"))
    pair_decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("event_pair_decisions.id")
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventPairDecisionRecord(Base):
    __tablename__ = "event_pair_decisions"
    __table_args__ = (
        UniqueConstraint(
            "left_raw_item_id",
            "right_raw_item_id",
            "algorithm_version",
            "input_fingerprint",
            name="uq_event_pair_decision_input",
        ),
        Index(
            "ix_event_pair_decisions_lookup",
            "left_raw_item_id",
            "right_raw_item_id",
            "algorithm_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    left_raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    right_raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(120), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_score: Mapped[float] = mapped_column(Float, nullable=False)
    rule_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    model_same_event: Mapped[bool | None] = mapped_column(Boolean)
    model_confidence: Mapped[float | None] = mapped_column(Float)
    final_decision: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
