from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from newsradar.daily_reports.audio_client import SpeechSynthesisResult
from newsradar.daily_reports.audio_runtime import DailyReportAudioHandler
from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.db.models import (
    Base,
    DailyReportAudioArtifactRecord,
    DailyReportItemEditorialReviewRecord,
)
from newsradar.operations.repository import OperationLease
from newsradar.operations.schema import OperationStatus
from newsradar.operations.worker import OperationCancelled
from tests.web.test_daily_report_pages import (
    NOW,
    review_overview_for_audio,
    seed_daily_report,
)


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _lease(report_id: int, rendition: str = "decision") -> OperationLease:
    return OperationLease(
        901,
        902,
        1,
        "test-worker",
        {"daily_report_id": report_id, "rendition": rendition},
        "daily_report_audio",
    )


def test_audio_handler_persists_decision_artifact_and_writes_mp3(
    db_session, tmp_path: Path
) -> None:
    report = seed_daily_report(db_session)
    DailyReportRepository(db_session).archive(report.id)
    report_id = report.id
    checkpoints: list[str] = []

    result = DailyReportAudioHandler(
        lambda: db_session,
        audio_root=tmp_path,
        synthesize=lambda script: SpeechSynthesisResult(
            audio_bytes=b"ID3-test-mp3",
            trace_id="trace-test",
            duration_ms=1234,
            usage_characters=len(script),
        ),
    )(_lease(report_id), checkpoints.append)

    artifact = db_session.scalar(select(DailyReportAudioArtifactRecord))
    assert result.status is OperationStatus.SUCCEEDED
    assert result.result_summary == {"artifact_id": artifact.id, "rendition": "decision"}
    assert artifact is not None
    assert artifact.status == "succeeded"
    assert artifact.script.startswith("2026-07-16 News Codex")
    assert artifact.trace_id == "trace-test"
    assert artifact.audio_duration_ms == 1234
    assert artifact.audio_size_bytes == len(b"ID3-test-mp3")
    assert artifact.relative_audio_path == f"{report_id}/{artifact.id}.mp3"
    assert (tmp_path / artifact.relative_audio_path).read_bytes() == b"ID3-test-mp3"
    assert checkpoints == ["before_daily_report_audio", "before_audio_write", "after_audio_write"]


def test_audio_handler_uses_overview_script_for_overview_rendition(
    db_session, tmp_path: Path
) -> None:
    report = seed_daily_report(db_session)
    review_overview_for_audio(db_session, report.id)
    DailyReportRepository(db_session).archive(report.id)
    scripts: list[str] = []

    result = DailyReportAudioHandler(
        lambda: db_session,
        audio_root=tmp_path,
        synthesize=lambda script: (
            scripts.append(script) or SpeechSynthesisResult(b"ID3", None, None, len(script))
        ),
    )(_lease(report.id, "overview"), lambda _boundary: None)

    assert result.status is OperationStatus.SUCCEEDED
    assert scripts and "News Codex 情报全览" in scripts[0]
    assert "News Codex 决策日报" not in scripts[0]
    assert "已审核全览标题 1" in scripts[0]
    assert "已审核全览标题 2" in scripts[0]


def test_overview_audio_omits_stale_model_unavailable_snapshot_copy(
    db_session, tmp_path: Path
) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session)
    model_item, fallback_item = repository.items(report.id)
    model_overview, fallback_overview = repository.overview_items(report.id)
    stale_reason = "已按可追溯规则汇总；中文增强暂不可用。"
    stale_limitation = "中文模型不可用，当前使用规则回退"
    model_item.snapshot = {
        **model_item.snapshot,
        "why_it_matters": stale_reason,
        "limitations": [stale_limitation],
    }
    model_overview.snapshot = {
        **model_overview.snapshot,
        "why_it_matters": stale_reason,
        "limitations": [stale_limitation],
    }
    fallback_item.snapshot = {
        **fallback_item.snapshot,
        "why_it_matters": "规则回退原因必须保留",
    }
    fallback_overview.snapshot = {
        **fallback_overview.snapshot,
        "why_it_matters": "规则回退原因必须保留",
    }
    report.generation_summary = {
        **report.generation_summary,
        "daily_chinese_enrichment": {
            "candidate_total": 2,
            "processed": 2,
            "model_success": 1,
            "rule_fallback": 1,
            "budget_fallback": 0,
            "error_counts": {"no_api_key": 1},
            "items": {
                f"{model_item.event_id}:{model_item.event_version_number}": {
                    "origin": "model",
                    "error_code": None,
                },
                f"{fallback_item.event_id}:{fallback_item.event_version_number}": {
                    "origin": "rule_fallback",
                    "error_code": "no_api_key",
                },
            },
        },
    }
    db_session.commit()
    review_overview_for_audio(db_session, report.id)
    DailyReportRepository(db_session).archive(report.id)
    scripts: list[str] = []

    result = DailyReportAudioHandler(
        lambda: db_session,
        audio_root=tmp_path,
        synthesize=lambda script: (
            scripts.append(script) or SpeechSynthesisResult(b"ID3", None, None, len(script))
        ),
    )(_lease(report.id, "overview"), lambda _boundary: None)

    assert result.status is OperationStatus.SUCCEEDED
    assert scripts
    assert stale_reason not in scripts[0]
    assert stale_limitation not in scripts[0]
    assert (
        "本条中文标题和概述已完成日报增强；确认状态、证据与收录范围仍以固定快照为准。"
        in scripts[0]
    )
    assert "规则回退原因必须保留" in scripts[0]


def test_audio_handler_rejects_corrupted_script_before_synthesis(
    db_session, tmp_path: Path
) -> None:
    report = seed_daily_report(db_session)
    repository = DailyReportRepository(db_session)
    repository.archive(report.id)
    item = repository.items(report.id)[0]
    db_session.add(
        DailyReportItemEditorialReviewRecord(
            daily_report_item_id=item.id,
            revision=1,
            decision="keep",
            zh_title="????",
            zh_summary="中文概述。",
            review_recommendation="继续关注。",
            evidence_assessment="当前证据可供审核。",
            created_at=NOW,
        )
    )
    db_session.commit()
    synthesized: list[str] = []

    result = DailyReportAudioHandler(
        lambda: db_session,
        audio_root=tmp_path,
        synthesize=lambda script: (
            synthesized.append(script)
            or SpeechSynthesisResult(b"ID3", None, None, len(script))
        ),
    )(_lease(report.id), lambda _boundary: None)

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "daily_report_text_corrupted"
    assert result.error_message == "检测到疑似编码损坏的连续问号，请修正中文内容后再继续。"
    assert result.retryable is False
    assert synthesized == []
    assert db_session.scalar(select(DailyReportAudioArtifactRecord)) is None


def test_audio_handler_rejects_unreviewed_overview_before_synthesis(
    db_session, tmp_path: Path
) -> None:
    report = seed_daily_report(db_session)
    DailyReportRepository(db_session).archive(report.id)
    synthesized: list[str] = []

    result = DailyReportAudioHandler(
        lambda: db_session,
        audio_root=tmp_path,
        synthesize=lambda script: (
            synthesized.append(script)
            or SpeechSynthesisResult(b"ID3", None, None, len(script))
        ),
    )(_lease(report.id, "overview"), lambda _boundary: None)

    assert result.status is OperationStatus.FAILED
    assert result.error_code == "daily_report_overview_review_incomplete"
    assert result.error_message == "情报全览仍有未审核条目，暂不能生成全览语音。"
    assert result.retryable is False
    assert synthesized == []
    assert db_session.scalar(select(DailyReportAudioArtifactRecord)) is None


def test_audio_handler_records_safe_chinese_failure_for_missing_tts_configuration(
    db_session, tmp_path: Path
) -> None:
    report = seed_daily_report(db_session)
    DailyReportRepository(db_session).archive(report.id)

    result = DailyReportAudioHandler(
        lambda: db_session,
        audio_root=tmp_path,
        synthesize=lambda _script: (_ for _ in ()).throw(ValueError("minimax_tts_not_configured")),
    )(_lease(report.id), lambda _boundary: None)

    artifact = db_session.scalar(select(DailyReportAudioArtifactRecord))
    assert result.status is OperationStatus.FAILED
    assert result.error_code == "minimax_tts_not_configured"
    assert result.retryable is False
    assert artifact is not None
    assert artifact.status == "failed"
    assert artifact.error_code == "minimax_tts_not_configured"
    assert artifact.error_message == "MiniMax 语音凭据未配置，请在服务端配置后重试。"


def test_audio_handler_marks_auth_rejection_nonretryable_with_chinese_diagnosis(
    db_session, tmp_path: Path
) -> None:
    report = seed_daily_report(db_session)
    DailyReportRepository(db_session).archive(report.id)
    request = httpx.Request("POST", "https://api.minimaxi.com/v1/t2a_v2")
    response = httpx.Response(401, request=request)

    result = DailyReportAudioHandler(
        lambda: db_session,
        audio_root=tmp_path,
        synthesize=lambda _script: (_ for _ in ()).throw(
            httpx.HTTPStatusError("unauthorized", request=request, response=response)
        ),
    )(_lease(report.id), lambda _boundary: None)

    artifact = db_session.scalar(select(DailyReportAudioArtifactRecord))
    assert result.status is OperationStatus.FAILED
    assert result.error_code == "minimax_tts_auth_rejected"
    assert result.retryable is False
    assert artifact is not None
    assert artifact.error_code == "minimax_tts_auth_rejected"
    assert artifact.error_message == "MiniMax 语音凭据无效或没有语音权限，请检查后重试。"


def test_audio_handler_marks_artifact_failed_and_removes_file_when_cancelled(
    db_session, tmp_path: Path
) -> None:
    report = seed_daily_report(db_session)
    report_id = report.id
    DailyReportRepository(db_session).archive(report_id)

    def cancel_after_write(boundary: str) -> None:
        if boundary == "after_audio_write":
            raise OperationCancelled()

    with pytest.raises(OperationCancelled):
        DailyReportAudioHandler(
            lambda: db_session,
            audio_root=tmp_path,
            synthesize=lambda script: SpeechSynthesisResult(
                audio_bytes=b"ID3-cancelled",
                trace_id=None,
                duration_ms=None,
                usage_characters=len(script),
            ),
        )(_lease(report_id), cancel_after_write)

    artifact = db_session.scalar(select(DailyReportAudioArtifactRecord))
    assert artifact is not None
    assert artifact.status == "failed"
    assert artifact.error_code == "operation_cancelled"
    assert artifact.error_message == "语音任务已取消，未发布音频。"
    assert not (tmp_path / str(report_id) / f"{artifact.id}.mp3").exists()
