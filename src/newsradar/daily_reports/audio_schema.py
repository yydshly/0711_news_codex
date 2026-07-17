from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

AUDIO_MODEL = "speech-2.8-hd"
AUDIO_VOICE_ID = "male-qn-qingse"
AUDIO_FORMAT = "mp3"
AUDIO_SAMPLE_RATE = 32000
AUDIO_BITRATE = 128000
AUDIO_CHANNEL = 1


class AudioRendition(StrEnum):
    DECISION = "decision"
    OVERVIEW = "overview"


class AudioArtifactStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DailyReportAudioRequest:
    report_id: int
    rendition: str
    model: str
    voice_id: str
    audio_format: str
    sample_rate: int
    bitrate: int
    channel: int

    @classmethod
    def create(
        cls,
        *,
        report_id: int,
        rendition: str,
    ) -> DailyReportAudioRequest:
        if isinstance(report_id, bool) or not isinstance(report_id, int) or report_id <= 0:
            raise ValueError("invalid_daily_report_audio_report_id")
        try:
            normalized_rendition = AudioRendition(rendition).value
        except (TypeError, ValueError) as error:
            raise ValueError("invalid_daily_report_audio_rendition") from error
        return cls(
            report_id=report_id,
            rendition=normalized_rendition,
            model=AUDIO_MODEL,
            voice_id=AUDIO_VOICE_ID,
            audio_format=AUDIO_FORMAT,
            sample_rate=AUDIO_SAMPLE_RATE,
            bitrate=AUDIO_BITRATE,
            channel=AUDIO_CHANNEL,
        )
