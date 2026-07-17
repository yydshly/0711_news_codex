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
