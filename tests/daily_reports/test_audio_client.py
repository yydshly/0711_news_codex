import json

import httpx

from newsradar.daily_reports.audio_client import MiniMaxSpeechClient
from newsradar.settings import Settings


def test_speech_client_posts_fixed_hd_payload_and_decodes_hex_mp3() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": {"audio": b"ID3mp3".hex(), "status": 2},
                "extra_info": {"audio_length": 1200, "usage_characters": 4},
                "trace_id": "trace-123",
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        )

    settings = Settings(minimax_tts_api_key="token-plan-secret")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = MiniMaxSpeechClient(settings, http).synthesize("中文日报")

    assert result.audio_bytes == b"ID3mp3"
    assert result.trace_id == "trace-123"
    assert captured["url"] == "https://api.minimaxi.com/v1/t2a_v2"
    assert captured["authorization"] == "Bearer token-plan-secret"
    assert captured["payload"] == {
        "model": "speech-2.8-hd",
        "text": "中文日报",
        "stream": False,
        "language_boost": "Chinese",
        "voice_setting": {"voice_id": "male-qn-qingse", "speed": 1.0, "vol": 1.0, "pitch": 0},
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
        "subtitle_enable": False,
    }


def test_speech_client_uses_async_api_for_long_text_and_downloads_complete_mp3() -> None:
    requests: list[tuple[str, str, dict[str, object] | None]] = []
    query_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal query_count
        payload = json.loads(request.content) if request.content else None
        requests.append((request.method, str(request.url), payload))
        if request.url.path == "/v1/t2a_async_v2":
            return httpx.Response(
                200,
                json={
                    "task_id": 95157322514444,
                    "file_id": 95157322514444,
                    "usage_characters": 12_000,
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                },
            )
        if request.url.path == "/v1/query/t2a_async_query_v2":
            query_count += 1
            status = "Processing" if query_count == 1 else "Success"
            return httpx.Response(
                200,
                json={
                    "task_id": 95157322514444,
                    "status": status,
                    "file_id": 95157322519999,
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                },
            )
        if request.url.path == "/v1/files/retrieve_content":
            return httpx.Response(200, content=b"ID3complete-long-report")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    settings = Settings(minimax_tts_api_key="token-plan-secret")
    sleeps: list[float] = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = MiniMaxSpeechClient(
            settings,
            http,
            sleep=sleeps.append,
            async_poll_interval_seconds=0.25,
        ).synthesize("长" * 12_000)

    assert result.audio_bytes == b"ID3complete-long-report"
    assert result.trace_id == "async-task:95157322514444"
    assert result.usage_characters == 12_000
    assert sleeps == [0.25, 0.25]
    assert requests[0][0:2] == (
        "POST",
        "https://api.minimaxi.com/v1/t2a_async_v2",
    )
    assert requests[0][2] == {
        "model": "speech-2.8-hd",
        "text": "长" * 12_000,
        "language_boost": "Chinese",
        "voice_setting": {
            "voice_id": "male-qn-qingse",
            "speed": 1.0,
            "vol": 1.0,
            "pitch": 0,
        },
        "audio_setting": {
            "audio_sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }
    assert requests[1][1].endswith(
        "/v1/query/t2a_async_query_v2?task_id=95157322514444"
    )
    assert requests[-1][1].endswith(
        "/v1/files/retrieve_content?file_id=95157322519999"
    )
