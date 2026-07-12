from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class SourceDefinitionRecord(Base):
    __tablename__ = "source_definitions"

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
    access_method_id: Mapped[int | None] = mapped_column(ForeignKey("source_access_methods.id"))
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
