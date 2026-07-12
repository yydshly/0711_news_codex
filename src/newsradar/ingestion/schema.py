from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class FetchOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    NO_CHANGE = "no_change"
    BLOCKED = "blocked"


class NormalizedRawItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    external_id: str
    title: str
    canonical_url: AnyHttpUrl
    original_url: AnyHttpUrl | None = None
    authors: tuple[str, ...] = ()
    summary: str | None = None
    content: str | None = None
    language: str | None = None
    content_type: str = "article"
    published_at: datetime | None = None
    source_updated_at: datetime | None = None
    discussion_url: AnyHttpUrl | None = None
    engagement: dict[str, int | float] = Field(default_factory=dict)
    raw_payload: dict[str, Any]


class FetchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: FetchOutcome
    items: tuple[NormalizedRawItem, ...] = ()
    http_status: int | None = None
    final_url: AnyHttpUrl | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    etag: str | None = None
    last_modified: str | None = None
    next_cursor: str | None = None
    items_received: int = 0
    items_inserted: int = 0
    items_updated: int = 0
    items_unchanged: int = 0
    items_skipped: int = 0
    items_failed: int = 0
    warnings: tuple[str, ...] = ()
    error_category: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    completed_at: datetime | None = None
