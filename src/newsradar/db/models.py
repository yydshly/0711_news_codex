from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class SourceDefinitionRecord(Base):
    __tablename__ = "source_definitions"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
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


class RawItemRecord(Base):
    __tablename__ = "raw_items"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_definitions.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
