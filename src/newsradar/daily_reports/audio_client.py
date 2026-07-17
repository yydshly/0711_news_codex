from __future__ import annotations

from dataclasses import dataclass

import httpx

from newsradar.daily_reports.audio_schema import (
    AUDIO_BITRATE,
    AUDIO_CHANNEL,
    AUDIO_FORMAT,
    AUDIO_MODEL,
    AUDIO_SAMPLE_RATE,
    AUDIO_VOICE_ID,
)
from newsradar.settings import Settings


@dataclass(frozen=True, slots=True)
class SpeechSynthesisResult:
    audio_bytes: bytes
    trace_id: str | None
    duration_ms: int | None
    usage_characters: int | None


class MiniMaxSpeechClient:
    _URL = "https://api.minimaxi.com/v1/t2a_v2"

    def __init__(self, settings: Settings, http: httpx.Client) -> None:
        self._api_key = settings.minimax_tts_api_key
        self._http = http

    def synthesize(self, text: str) -> SpeechSynthesisResult:
        if self._api_key is None:
            raise ValueError("minimax_tts_not_configured")
        response = self._http.post(
            self._URL,
            headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
            json={
                "model": AUDIO_MODEL,
                "text": text,
                "stream": False,
                "language_boost": "Chinese",
                "voice_setting": {
                    "voice_id": AUDIO_VOICE_ID,
                    "speed": 1.0,
                    "vol": 1.0,
                    "pitch": 0,
                },
                "audio_setting": {
                    "sample_rate": AUDIO_SAMPLE_RATE,
                    "bitrate": AUDIO_BITRATE,
                    "format": AUDIO_FORMAT,
                    "channel": AUDIO_CHANNEL,
                },
                "subtitle_enable": False,
            },
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        audio = data.get("audio") if isinstance(data, dict) else None
        if not isinstance(audio, str):
            raise ValueError("minimax_tts_invalid_audio")
        try:
            audio_bytes = bytes.fromhex(audio)
        except ValueError as error:
            raise ValueError("minimax_tts_invalid_audio") from error
        if not audio_bytes:
            raise ValueError("minimax_tts_invalid_audio")
        extra = payload.get("extra_info") if isinstance(payload, dict) else None
        return SpeechSynthesisResult(
            audio_bytes=audio_bytes,
            trace_id=payload.get("trace_id") if isinstance(payload, dict) else None,
            duration_ms=extra.get("audio_length") if isinstance(extra, dict) else None,
            usage_characters=(extra.get("usage_characters") if isinstance(extra, dict) else None),
        )
