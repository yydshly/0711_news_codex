from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import feedparser
from requests import Session
from requests.cookies import RequestsCookieJar

from newsradar.credentials import CredentialProvider, SettingsCredentials
from newsradar.ingestion.fetchers.base import HttpPolicy
from newsradar.sources.schema import AcquisitionCandidate, SourceDefinition

from .schema import AcquisitionProbeOutcome, AcquisitionProbeResult, AcquisitionProbeSample

_TEXT_LIMIT = 4000
_SUMMARY_LIMIT = 2000


class _RejectingCookieJar(RequestsCookieJar):
    """Reject all response and library cookie writes for transcript research."""

    def set_cookie(self, cookie, *args: object, **kwargs: object) -> None:
        del cookie, args, kwargs


def _clip(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip()[:limit] or None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


class YouTubeResearchProbe:
    """Bounded research only; this class never invokes a browser or media downloader."""

    def __init__(self, policy: HttpPolicy, credentials: CredentialProvider | None = None) -> None:
        self.policy = policy
        self.credentials = credentials or SettingsCredentials()

    async def probe(
        self,
        source: SourceDefinition,
        candidate: AcquisitionCandidate,
        limit: int = 5,
        video_ids: tuple[str, ...] = (),
    ) -> AcquisitionProbeResult:
        if candidate.key == "youtube-atom":
            channel_id = next(
                (
                    str(value)
                    for method in source.access_methods
                    for key, value in method.params.items()
                    if key == "channelId"
                ),
                "",
            )
            return await self.probe_atom(source, candidate, channel_id=channel_id, limit=limit)
        if candidate.key == "youtube-data-api":
            return await self.probe_data_api(source, candidate, limit=limit, video_ids=video_ids)
        if candidate.key == "youtube-transcript-api":
            return await self.probe_transcript(
                source,
                candidate,
                video_id=video_ids[0] if video_ids else "",
                limit=limit,
            )
        return self.inspect_ytdlp_metadata(source, candidate, {})

    async def probe_atom(
        self,
        source: SourceDefinition,
        candidate: AcquisitionCandidate,
        *,
        channel_id: str,
        limit: int = 5,
    ) -> AcquisitionProbeResult:
        if not channel_id:
            return self._result(
                source,
                candidate,
                AcquisitionProbeOutcome.BLOCKED,
                "缺少已确认的频道 ID",
                "missing_channel_id",
            )
        try:
            response = await self.policy.get(
                "https://www.youtube.com/feeds/videos.xml", params={"channel_id": channel_id}
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except Exception as exc:  # bounded, scrubbed network failure
            return self._result(
                source,
                candidate,
                AcquisitionProbeOutcome.FAILED,
                "Atom 公开订阅源不可用",
                type(exc).__name__,
            )
        samples: list[AcquisitionProbeSample] = []
        for entry in feed.entries[: max(0, min(limit, 5))]:
            video_id = entry.get("yt_videoid") or entry.get("videoid")
            if not isinstance(video_id, str):
                continue
            samples.append(
                AcquisitionProbeSample(
                    external_id=video_id,
                    title=_clip(entry.get("title"), 500),
                    channel=_clip(entry.get("author"), 200),
                    canonical_url=f"https://www.youtube.com/watch?v={video_id}",
                    published_at=_timestamp(entry.get("published")),
                    summary=_clip(entry.get("summary"), _SUMMARY_LIMIT),
                )
            )
        outcome = AcquisitionProbeOutcome.SUCCEEDED if samples else AcquisitionProbeOutcome.PARTIAL
        return self._result(
            source, candidate, outcome, "已读取公开 Atom 视频元数据", samples=samples
        )

    async def probe_data_api(
        self,
        source: SourceDefinition,
        candidate: AcquisitionCandidate,
        *,
        video_ids: tuple[str, ...] = (),
        limit: int = 5,
    ) -> AcquisitionProbeResult:
        try:
            key = self.credentials.require("YOUTUBE_API_KEY")
        except (KeyError, ValueError):
            return self._result(
                source,
                candidate,
                AcquisitionProbeOutcome.BLOCKED,
                "缺少 YOUTUBE_API_KEY，未发起网页回退",
                "missing_credential",
            )
        ids = tuple(video_ids[:5])
        if not ids:
            return self._result(
                source,
                candidate,
                AcquisitionProbeOutcome.PARTIAL,
                "未提供视频 ID；Data API 未执行搜索回退",
                "missing_video_ids",
            )
        try:
            response = await self.policy.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "snippet,statistics", "id": ",".join(ids), "key": key},
            )
            if response.status_code in {401, 403, 429}:
                return self._result(
                    source,
                    candidate,
                    AcquisitionProbeOutcome.BLOCKED,
                    "YouTube Data API 拒绝访问或配额不可用",
                    f"http_{response.status_code}",
                )
            response.raise_for_status()
            rows = response.json().get("items", [])
        except Exception as exc:
            return self._result(
                source,
                candidate,
                AcquisitionProbeOutcome.FAILED,
                "YouTube Data API 请求失败",
                type(exc).__name__,
            )
        samples = [
            self._api_sample(row) for row in rows[: max(0, min(limit, 5))] if isinstance(row, dict)
        ]
        samples = [sample for sample in samples if sample is not None]
        return self._result(
            source,
            candidate,
            AcquisitionProbeOutcome.SUCCEEDED if samples else AcquisitionProbeOutcome.PARTIAL,
            "已读取官方视频详情与互动数据",
            samples=samples,
        )

    async def probe_transcript(
        self,
        source: SourceDefinition,
        candidate: AcquisitionCandidate,
        *,
        video_id: str,
        transcript_client: Callable[[str], Any] | None = None,
        limit: int = 5,
        timeout_seconds: float = 10.0,
    ) -> AcquisitionProbeResult:
        del limit
        if not video_id:
            return self._result(
                source,
                candidate,
                AcquisitionProbeOutcome.PARTIAL,
                "未提供视频 ID，未请求字幕库",
                "missing_video_id",
            )
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(transcript_client, video_id)
                if transcript_client
                else asyncio.to_thread(self._fetch_transcript, video_id),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return self._result(
                source,
                candidate,
                AcquisitionProbeOutcome.PARTIAL,
                "字幕研究超时，可稍后人工复核",
                "timeout",
            )
        except Exception as exc:
            name = type(exc).__name__
            if name == "FailedToCreateConsentCookie":
                return self._result(
                    source,
                    candidate,
                    AcquisitionProbeOutcome.BLOCKED,
                    "字幕受限：临时无 Cookie 会话无法通过 consent 页面，已停止且未绕过",
                    "consent_required",
                )
            if name in {"RequestBlocked", "IpBlocked", "TranscriptsDisabled", "NoTranscriptFound"}:
                return self._result(
                    source,
                    candidate,
                    AcquisitionProbeOutcome.PARTIAL,
                    "字幕暂不可用；临时无 Cookie 会话可降级为仅元数据研究",
                    name,
                )
            return self._result(
                source,
                candidate,
                AcquisitionProbeOutcome.PARTIAL,
                "字幕库不可用；临时无 Cookie 会话可降级为仅元数据研究",
                name,
            )
        if not isinstance(payload, dict):
            return self._result(
                source,
                candidate,
                AcquisitionProbeOutcome.PARTIAL,
                "字幕响应不可读",
                "invalid_payload",
            )
        segments = payload.get("segments", [])
        text = " ".join(str(row.get("text", "")) for row in segments if isinstance(row, dict))[
            :_TEXT_LIMIT
        ]
        sample = AcquisitionProbeSample(
            external_id=video_id,
            language=_clip(payload.get("language"), 32),
            transcript_kind="generated" if payload.get("is_generated") else "manual",
            text_available=bool(text),
            text=text or None,
        )
        return self._result(
            source,
            candidate,
            AcquisitionProbeOutcome.SUCCEEDED,
            "已读取有限字幕文本（临时无 Cookie 会话）",
            samples=[sample],
        )

    def _fetch_transcript(self, video_id: str) -> dict[str, Any]:
        from youtube_transcript_api import YouTubeTranscriptApi

        session = Session()
        session.trust_env = False
        session.cookies = _RejectingCookieJar()
        session.headers.pop("Cookie", None)
        try:
            transcript = YouTubeTranscriptApi(http_client=session).fetch(video_id)
        finally:
            session.close()
        return {
            "language": getattr(transcript, "language_code", None),
            "is_generated": getattr(transcript, "is_generated", False),
            "segments": [{"text": item.text} for item in transcript],
        }

    def inspect_ytdlp_metadata(
        self, source: SourceDefinition, candidate: AcquisitionCandidate, metadata: dict[str, Any]
    ) -> AcquisitionProbeResult:
        return self._result(
            source,
            candidate,
            AcquisitionProbeOutcome.PARTIAL,
            "yt-dlp 仅记录公开项目元数据；媒体下载必须人工处理",
            metadata={
                "version": _clip(metadata.get("version"), 64),
                "license": _clip(metadata.get("license"), 200),
                "maintenance": "metadata_only",
                "media_download": False,
            },
            decision="manual_only",
        )

    def _api_sample(self, row: dict[str, Any]) -> AcquisitionProbeSample | None:
        video_id, snippet = row.get("id"), row.get("snippet", {})
        if not isinstance(video_id, str) or not isinstance(snippet, dict):
            return None
        stats = row.get("statistics", {}) if isinstance(row.get("statistics"), dict) else {}
        return AcquisitionProbeSample(
            external_id=video_id,
            title=_clip(snippet.get("title"), 500),
            channel=_clip(snippet.get("channelTitle"), 200),
            canonical_url=f"https://www.youtube.com/watch?v={video_id}",
            published_at=_timestamp(snippet.get("publishedAt")),
            summary=_clip(snippet.get("description"), _SUMMARY_LIMIT),
            engagement={
                key: int(value)
                for key, value in {
                    "views": stats.get("viewCount"),
                    "likes": stats.get("likeCount"),
                    "comments": stats.get("commentCount"),
                }.items()
                if isinstance(value, str) and value.isdigit()
            },
        )

    def _result(
        self,
        source: SourceDefinition,
        candidate: AcquisitionCandidate,
        outcome: AcquisitionProbeOutcome,
        reason_zh: str,
        error_code: str | None = None,
        *,
        samples: list[AcquisitionProbeSample] | None = None,
        metadata: dict[str, str | int | bool | None] | None = None,
        decision: str | None = None,
    ) -> AcquisitionProbeResult:
        return AcquisitionProbeResult(
            source_id=source.id,
            candidate_key=candidate.key,
            outcome=outcome,
            decision=decision or candidate.decision.value,
            reason_zh=reason_zh,
            error_code=error_code,
            samples=(samples or [])[:5],
            metadata=metadata or {},
        )
