import pytest

from newsradar.daily_reports.audio_schema import (
    AUDIO_FORMAT,
    AUDIO_MODEL,
    AUDIO_VOICE_ID,
    DailyReportAudioRequest,
)


def test_decision_audio_request_uses_fixed_hd_defaults() -> None:
    request = DailyReportAudioRequest.create(report_id=12, rendition="decision")

    assert request.report_id == 12
    assert request.rendition == "decision"
    assert request.model == AUDIO_MODEL == "speech-2.8-hd"
    assert request.voice_id == AUDIO_VOICE_ID == "male-qn-qingse"
    assert request.audio_format == AUDIO_FORMAT == "mp3"
    assert request.sample_rate == 32000
    assert request.bitrate == 128000
    assert request.channel == 1


@pytest.mark.parametrize("report_id", (0, -1, True, "12"))
def test_audio_request_rejects_invalid_report_identifier(report_id: object) -> None:
    with pytest.raises(ValueError, match="invalid_daily_report_audio_report_id"):
        DailyReportAudioRequest.create(report_id=report_id, rendition="decision")  # type: ignore[arg-type]


@pytest.mark.parametrize("rendition", ("", "draft", "full", True))
def test_audio_request_rejects_unknown_rendition(rendition: object) -> None:
    with pytest.raises(ValueError, match="invalid_daily_report_audio_rendition"):
        DailyReportAudioRequest.create(report_id=12, rendition=rendition)  # type: ignore[arg-type]
