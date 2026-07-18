from __future__ import annotations

from enum import StrEnum


class DailyAutopilotStage(StrEnum):
    ENQUEUE_SOURCE_REFRESH = "enqueue_source_refresh"
    WAIT_SOURCE_REFRESH = "wait_source_refresh"
    ENQUEUE_EVENT_PIPELINE = "enqueue_event_pipeline"
    WAIT_EVENT_PIPELINE = "wait_event_pipeline"
    GENERATE_REPORT = "generate_report"
    WRITE_REVIEWS = "write_reviews"
    ARCHIVE_AND_ENQUEUE_AUDIO = "archive_and_enqueue_audio"
    WAIT_AUDIO = "wait_audio"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_AUTOPILOT_STAGES = frozenset(
    {
        DailyAutopilotStage.COMPLETED,
        DailyAutopilotStage.FAILED,
        DailyAutopilotStage.CANCELLED,
    }
)
