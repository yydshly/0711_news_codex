from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import sleep as time_sleep

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
    _ASYNC_URL = "https://api.minimaxi.com/v1/t2a_async_v2"
    _ASYNC_QUERY_URL = "https://api.minimaxi.com/v1/query/t2a_async_query_v2"
    _FILE_CONTENT_URL = "https://api.minimaxi.com/v1/files/retrieve_content"
    _SYNC_TEXT_LIMIT = 10_000
    _ASYNC_TEXT_LIMIT = 50_000

    def __init__(
        self,
        settings: Settings,
        http: httpx.Client,
        *,
        sleep: Callable[[float], None] = time_sleep,
        async_poll_interval_seconds: float = 2.0,
        max_async_polls: int = 150,
    ) -> None:
        self._api_key = settings.minimax_tts_api_key
        self._http = http
        self._sleep = sleep
        self._async_poll_interval_seconds = async_poll_interval_seconds
        self._max_async_polls = max_async_polls

    def synthesize(self, text: str) -> SpeechSynthesisResult:
        if self._api_key is None:
            raise ValueError("minimax_tts_not_configured")
        if len(text) >= self._SYNC_TEXT_LIMIT:
            return self._synthesize_async(text)
        return self._synthesize_sync(text)

    def _synthesize_sync(self, text: str) -> SpeechSynthesisResult:
        response = self._http.post(
            self._URL,
            headers=self._headers(),
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

    def _synthesize_async(self, text: str) -> SpeechSynthesisResult:
        if len(text) > self._ASYNC_TEXT_LIMIT:
            raise ValueError("minimax_tts_text_too_long")
        response = self._http.post(
            self._ASYNC_URL,
            headers=self._headers(),
            json={
                "model": AUDIO_MODEL,
                "text": text,
                "language_boost": "Chinese",
                "voice_setting": {
                    "voice_id": AUDIO_VOICE_ID,
                    "speed": 1.0,
                    "vol": 1.0,
                    "pitch": 0,
                },
                "audio_setting": {
                    "audio_sample_rate": AUDIO_SAMPLE_RATE,
                    "bitrate": AUDIO_BITRATE,
                    "format": AUDIO_FORMAT,
                    "channel": AUDIO_CHANNEL,
                },
            },
        )
        payload = self._json_payload(response)
        task_id = payload.get("task_id")
        if not isinstance(task_id, int):
            raise ValueError("minimax_tts_async_invalid_response")
        usage_characters = payload.get("usage_characters")

        file_id: int | None = None
        for _poll in range(self._max_async_polls):
            self._sleep(self._async_poll_interval_seconds)
            query = self._http.get(
                self._ASYNC_QUERY_URL,
                headers=self._headers(),
                params={"task_id": task_id},
            )
            query_payload = self._json_payload(query)
            status = str(query_payload.get("status", "")).lower()
            if status == "processing":
                continue
            if status != "success":
                raise ValueError("minimax_tts_async_failed")
            candidate_file_id = query_payload.get("file_id")
            if not isinstance(candidate_file_id, int):
                raise ValueError("minimax_tts_async_invalid_response")
            file_id = candidate_file_id
            break
        if file_id is None:
            raise httpx.TimeoutException("minimax_tts_async_timeout")

        download = self._http.get(
            self._FILE_CONTENT_URL,
            headers=self._headers(),
            params={"file_id": file_id},
        )
        download.raise_for_status()
        if not download.content:
            raise ValueError("minimax_tts_invalid_audio")
        return SpeechSynthesisResult(
            audio_bytes=download.content,
            trace_id=f"async-task:{task_id}",
            duration_ms=None,
            usage_characters=(usage_characters if isinstance(usage_characters, int) else None),
        )

    def _headers(self) -> dict[str, str]:
        assert self._api_key is not None
        return {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}

    @staticmethod
    def _json_payload(response: httpx.Response) -> dict[str, object]:
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("minimax_tts_async_invalid_response")
        base_response = payload.get("base_resp")
        if not isinstance(base_response, dict) or base_response.get("status_code") != 0:
            raise ValueError("minimax_tts_async_failed")
        return payload
