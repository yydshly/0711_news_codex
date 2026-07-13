import json
import time
from pathlib import Path

import httpx
import pytest
import youtube_transcript_api
from requests import Request

from newsradar.credentials import SettingsCredentials
from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.research.probes.youtube import YouTubeResearchProbe
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from ...test_source_schema import valid_source

FIXTURES = Path(__file__).parents[2] / "fixtures" / "research"


def source() -> SourceDefinition:
    data = valid_source()
    data["id"] = "openai-youtube"
    data["name"] = "OpenAI YouTube"
    return SourceDefinition.model_validate(data)


def candidate(key: str) -> AcquisitionCandidate:
    return AcquisitionCandidate.model_validate(
        {
            "key": key,
            "kind": "atom" if key == "youtube-atom" else "api_key_api",
            "implementation": {
                "youtube-atom": "youtube-channel-feed",
                "youtube-data-api": "youtube-data-api",
                "youtube-transcript-api": "youtube-transcript-api",
                "yt-dlp-metadata": "manual-review",
            }[key],
            "officiality": "official"
            if key in {"youtube-atom", "youtube-data-api"}
            else "unofficial_library",
            "authentication": "api_key" if key == "youtube-data-api" else "none",
            "roles": ["discovery"],
            "fields": ["title"],
            "limitations": [],
            "evidence": ["https://developers.google.com/youtube/v3"],
            "reviewed_at": "2026-07-12",
            "sample_status": "not_run",
            "decision": "supplement",
        }
    )


@pytest.mark.asyncio
async def test_atom_extracts_bounded_public_video_metadata() -> None:
    xml = (FIXTURES / "youtube_atom.xml").read_text(encoding="utf-8")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=xml))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await YouTubeResearchProbe(HttpPolicy(client)).probe_atom(
            source(), candidate("youtube-atom"), channel_id="UCXZCJLdBC09xxGZ6gcdrc6A"
        )
    assert result.outcome.value == "succeeded"
    assert result.samples[0].external_id == "video-1"
    assert result.samples[0].title == "安全的标题"
    assert result.samples[0].channel == "OpenAI"
    assert result.samples[0].published_at.isoformat().startswith("2026-07-11")


@pytest.mark.asyncio
async def test_data_api_without_key_is_explicitly_blocked_without_network(monkeypatch) -> None:
    async with httpx.AsyncClient() as client:
        probe = YouTubeResearchProbe(HttpPolicy(client), credentials=SettingsCredentials())
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        result = await probe.probe_data_api(source(), candidate("youtube-data-api"))
    assert result.outcome.value == "blocked"
    assert result.error_code == "missing_credential"


@pytest.mark.asyncio
async def test_data_api_extracts_details_and_engagement_without_exposing_key() -> None:
    payload = json.loads((FIXTURES / "youtube_api.json").read_text(encoding="utf-8"))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    class Credentials:
        def require(self, name: str) -> str:
            assert name == "YOUTUBE_API_KEY"
            return "secret-key"

    async with httpx.AsyncClient(transport=transport) as client:
        result = await YouTubeResearchProbe(
            HttpPolicy(client), credentials=Credentials()
        ).probe_data_api(source(), candidate("youtube-data-api"), video_ids=("video-1",))
    assert result.outcome.value == "succeeded"
    assert result.samples[0].summary == "短描述"
    assert result.samples[0].engagement == {"views": 7, "likes": 2, "comments": 1}
    assert "secret-key" not in str(result.model_dump())


@pytest.mark.asyncio
async def test_transcript_records_language_kind_and_bounded_text() -> None:
    transcript = json.loads((FIXTURES / "youtube_transcript.json").read_text(encoding="utf-8"))
    result = await YouTubeResearchProbe(HttpPolicy(httpx.AsyncClient())).probe_transcript(
        source(),
        candidate("youtube-transcript-api"),
        video_id="video-1",
        transcript_client=lambda _: transcript,
    )
    assert result.outcome.value == "succeeded"
    assert result.samples[0].language == "en"
    assert result.samples[0].transcript_kind == "generated"
    assert result.samples[0].text_available is True
    assert len(result.samples[0].text or "") <= 4000


@pytest.mark.asyncio
async def test_default_transcript_fetch_runs_in_a_thread_and_respects_total_timeout(
    monkeypatch,
) -> None:
    probe = YouTubeResearchProbe(HttpPolicy(httpx.AsyncClient()))

    def blocking_fetch(_: str) -> dict:
        time.sleep(0.2)
        return {"language": "en", "is_generated": False, "segments": []}

    monkeypatch.setattr(probe, "_fetch_transcript", blocking_fetch)
    started = time.perf_counter()
    result = await probe.probe_transcript(
        source(),
        candidate("youtube-transcript-api"),
        video_id="abcdefghijk",
        timeout_seconds=0.01,
    )

    assert result.error_code == "timeout"
    assert time.perf_counter() - started < 0.15


def test_default_transcript_uses_temporary_cookie_free_session_without_env_proxy(
    monkeypatch,
) -> None:
    received: dict[str, object] = {}

    class Transcript(list):
        language_code = "en"
        is_generated = False

    class Segment:
        text = "短文本"

    class Api:
        def __init__(self, *, http_client) -> None:
            received["session"] = http_client

        def fetch(self, video_id: str) -> Transcript:
            assert video_id == "abcdefghijk"
            received["session"].cookies.set("CONSENT", "YES+consent", domain=".youtube.com")
            prepared = received["session"].prepare_request(
                Request("GET", "https://www.youtube.com/watch?v=abcdefghijk")
            )
            received["outbound_cookie"] = prepared.headers.get("Cookie")
            return Transcript([Segment()])

    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", Api)
    payload = YouTubeResearchProbe(HttpPolicy(httpx.AsyncClient()))._fetch_transcript("abcdefghijk")

    session = received["session"]
    assert session.trust_env is False
    assert not session.cookies
    assert "Cookie" not in session.headers
    assert received["outbound_cookie"] is None
    assert payload["segments"] == [{"text": "短文本"}]


@pytest.mark.asyncio
async def test_consent_requirement_is_blocked_without_cookie_bypass() -> None:
    FailedToCreateConsentCookie = type("FailedToCreateConsentCookie", (Exception,), {})

    def consent_page(_: str) -> dict:
        raise FailedToCreateConsentCookie()

    result = await YouTubeResearchProbe(HttpPolicy(httpx.AsyncClient())).probe_transcript(
        source(),
        candidate("youtube-transcript-api"),
        video_id="abcdefghijk",
        transcript_client=consent_page,
    )

    assert result.outcome.value == "blocked"
    assert result.error_code == "consent_required"
    assert "Cookie" in result.reason_zh


def test_ytdlp_metadata_is_manual_only_and_never_executes_download() -> None:
    result = YouTubeResearchProbe(HttpPolicy(httpx.AsyncClient())).inspect_ytdlp_metadata(
        source(), candidate("yt-dlp-metadata"), {"version": "2026.7.1", "license": "Unlicense"}
    )
    assert result.outcome.value == "partial"
    assert result.decision == "manual_only"
    assert result.metadata["media_download"] is False
