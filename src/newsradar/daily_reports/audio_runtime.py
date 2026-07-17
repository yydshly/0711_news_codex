"""Durable worker handler for archived daily-report audio artifacts."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from newsradar.daily_reports.audio_client import (
    MiniMaxSpeechClient,
    SpeechSynthesisResult,
)
from newsradar.daily_reports.audio_schema import DailyReportAudioRequest
from newsradar.db.models import DailyReportAudioArtifactRecord, DailyReportRecord
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus
from newsradar.operations.worker import OperationCancelled, OperationResult
from newsradar.settings import Settings, get_settings
from newsradar.web.daily_report_queries import DailyReportQueryService

Synthesize = Callable[[str], SpeechSynthesisResult]


class DailyReportAudioHandler:
    """Create an append-only MP3 artifact from one archived report snapshot."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        audio_root: Path = Path(".local/daily-report-audio"),
        synthesize: Synthesize | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._audio_root = audio_root
        self._synthesize = synthesize or self._production_synthesize(settings or get_settings())

    def __call__(self, lease: OperationLease, checkpoint: Callable[[str], None]) -> OperationResult:
        if lease.operation_type != "daily_report_audio":
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code="unsupported_operation_type",
                error_message="不支持的日报语音任务类型。",
                retryable=False,
            )
        try:
            request = DailyReportAudioRequest.create(
                report_id=lease.requested_scope.get("daily_report_id"),
                rendition=lease.requested_scope.get("rendition"),
            )
        except ValueError as error:
            return OperationResult(
                status=OperationStatus.FAILED,
                error_code=str(error),
                error_message="日报语音任务参数无效。",
                retryable=False,
            )
        checkpoint("before_daily_report_audio")
        session = self._session_factory()
        try:
            report = session.get(DailyReportRecord, request.report_id)
            if report is None:
                return self._result("daily_report_not_found", "日报不存在。", retryable=False)
            if report.status != "archived":
                return self._result(
                    "daily_report_must_be_archived_for_audio",
                    "仅已归档的日报可以生成语音。",
                    retryable=False,
                )
            detail = DailyReportQueryService(session).detail(report.id)
            if detail is None:
                return self._result("daily_report_not_found", "日报不存在。", retryable=False)
            script = (
                detail.decision_script
                if request.rendition == "decision"
                else detail.overview.script
            )
            artifact = DailyReportAudioArtifactRecord(
                daily_report_id=report.id,
                rendition=request.rendition,
                status="running",
                script=script,
                script_sha256=sha256(script.encode("utf-8")).hexdigest(),
                model=request.model,
                voice_id=request.voice_id,
                audio_format=request.audio_format,
                sample_rate=request.sample_rate,
                bitrate=request.bitrate,
                channel=request.channel,
                operation_run_id=lease.operation_id,
            )
            session.add(artifact)
            session.commit()
            artifact_id = artifact.id
        finally:
            session.close()
        target: Path | None = None
        try:
            result = self._synthesize(script)
            checkpoint("before_audio_write")
            target = self._target(request.report_id, artifact_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(result.audio_bytes)
            checkpoint("after_audio_write")
        except OperationCancelled:
            if target is not None:
                target.unlink(missing_ok=True)
            self._fail(
                artifact_id,
                "operation_cancelled",
                "语音任务已取消，未发布音频。",
                False,
            )
            raise
        except httpx.HTTPStatusError as error:
            code, message, retryable = _http_failure(error)
            return self._fail(artifact_id, code, message, retryable, error)
        except httpx.HTTPError as error:
            return self._fail(
                artifact_id,
                "minimax_tts_request_failed",
                "MiniMax 语音服务请求失败。",
                True,
                error,
            )
        except ValueError as error:
            return self._fail(
                artifact_id,
                str(error),
                _configuration_message(error),
                False,
                error,
            )
        except OSError as error:
            return self._fail(
                artifact_id,
                "daily_report_audio_write_failed",
                "音频文件写入失败。",
                True,
                error,
            )
        return self._succeed(artifact_id, request, result)

    def _succeed(
        self,
        artifact_id: int,
        request: DailyReportAudioRequest,
        result: SpeechSynthesisResult,
    ) -> OperationResult:
        session = self._session_factory()
        try:
            artifact = session.get(DailyReportAudioArtifactRecord, artifact_id)
            if artifact is None:
                return self._result(
                    "daily_report_audio_artifact_not_found",
                    "语音记录不存在。",
                    False,
                )
            artifact.status = "succeeded"
            artifact.trace_id = result.trace_id
            artifact.audio_duration_ms = result.duration_ms
            artifact.audio_size_bytes = len(result.audio_bytes)
            artifact.relative_audio_path = f"{request.report_id}/{artifact_id}.mp3"
            artifact.audio_sha256 = sha256(result.audio_bytes).hexdigest()
            session.commit()
            return OperationResult(
                status=OperationStatus.SUCCEEDED,
                result_summary={"artifact_id": artifact_id, "rendition": request.rendition},
            )
        finally:
            session.close()

    def _fail(
        self,
        artifact_id: int,
        code: str,
        message: str,
        retryable: bool,
        error: Exception | None = None,
    ) -> OperationResult:
        session = self._session_factory()
        try:
            artifact = session.get(DailyReportAudioArtifactRecord, artifact_id)
            if artifact is not None:
                artifact.status = "failed"
                artifact.error_code = code
                artifact.error_message = message
                session.commit()
        finally:
            session.close()
        return self._result(code, message, retryable=retryable, error=error)

    @staticmethod
    def _result(
        code: str, message: str, retryable: bool, error: Exception | None = None
    ) -> OperationResult:
        return OperationResult(
            status=OperationStatus.FAILED,
            error_code=code,
            error_message=message if error is None else f"{message} {error}",
            retryable=retryable,
        )

    def _target(self, report_id: int, artifact_id: int) -> Path:
        root = self._audio_root.resolve()
        target = (root / str(report_id) / f"{artifact_id}.mp3").resolve()
        if root not in target.parents:
            raise OSError("daily_report_audio_path_outside_root")
        return target

    @staticmethod
    def _production_synthesize(settings: Settings) -> Synthesize:
        def synthesize(script: str) -> SpeechSynthesisResult:
            with httpx.Client(timeout=httpx.Timeout(30.0), follow_redirects=False) as http:
                return MiniMaxSpeechClient(settings, http).synthesize(script)

        return synthesize


def _configuration_message(error: ValueError) -> str:
    if str(error) == "minimax_tts_not_configured":
        return "MiniMax 语音凭据未配置，请在服务端配置后重试。"
    return "MiniMax 语音配置或音频响应无效。"


def _http_failure(error: httpx.HTTPStatusError) -> tuple[str, str, bool]:
    status_code = error.response.status_code
    if status_code in {401, 403}:
        return (
            "minimax_tts_auth_rejected",
            "MiniMax 语音凭据无效或没有语音权限，请检查后重试。",
            False,
        )
    if 400 <= status_code < 500 and status_code != 429:
        return "minimax_tts_request_rejected", "MiniMax 拒绝了语音请求，请检查文稿和配置。", False
    return "minimax_tts_request_failed", "MiniMax 语音服务请求失败。", True
