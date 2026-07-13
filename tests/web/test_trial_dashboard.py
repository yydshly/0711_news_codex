from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from newsradar.db.models import (
    SourceDefinitionRecord,
    SourceProbeRunRecord,
    SourceProbeSampleRecord,
)
from newsradar.sources.repository import SourceRepository
from newsradar.web import create_app
from newsradar.web.queries import DashboardQueryService


def test_dashboard_and_target_catalog_distinguish_trial_coverage(db_session) -> None:
    direct_run = db_session.scalar(
        select(SourceProbeRunRecord)
        .where(SourceProbeRunRecord.source_id == "github-openai-python")
        .order_by(SourceProbeRunRecord.finished_at.desc())
    )
    assert direct_run is not None
    direct_run.metrics = {"sample_count": 1, "field_completeness": 1.0}
    db_session.add(
        SourceProbeSampleRecord(
            probe_run_id=direct_run.id,
            sample_index=0,
            canonical_url="https://github.example/openai-python",
            published_at=direct_run.finished_at,
            fields_present=["title", "canonical_url"],
            sample_hash="direct-trial-sample",
        )
    )

    indirect = db_session.get(SourceDefinitionRecord, "search-ai")
    credentials = db_session.get(SourceDefinitionRecord, "x-openai")
    assert indirect is not None
    assert credentials is not None
    credentials.availability = "requires_credentials"
    for source in (indirect, credentials):
        finished_at = direct_run.finished_at + timedelta(minutes=1)
        probe = SourceProbeRunRecord(
            source_id=source.id,
            access_kind="rss",
            access_url=f"https://feeds.example/{source.id}",
            outcome="success",
            started_at=finished_at - timedelta(seconds=1),
            finished_at=finished_at,
            latency_ms=10.0,
            http_status=200,
            final_url=f"https://feeds.example/{source.id}",
            response_headers={},
            metrics={"sample_count": 1, "field_completeness": 1.0},
            schema_fingerprint=f"{source.id}-schema",
            suggested_status="active",
            reason="ok",
            error_code=None,
        )
        db_session.add(probe)
        db_session.flush()
        db_session.add(
            SourceProbeSampleRecord(
                probe_run_id=probe.id,
                sample_index=0,
                canonical_url=f"https://feeds.example/{source.id}/item",
                published_at=finished_at,
                fields_present=["title", "canonical_url"],
                sample_hash=f"{source.id}-trial-sample",
            )
        )
    db_session.commit()

    @contextmanager
    def service_context():
        yield DashboardQueryService(db_session)

    with TestClient(create_app(service_context)) as client:
        dashboard = client.get("/sources")
        targets = client.get("/targets")

    assert dashboard.status_code == targets.status_code == 200
    for label in ("已探索", "可试用抓取", "仅发现", "受限目录"):
        assert label in dashboard.text
    assert "试用可抓取表示首次探测合格，不等于长期稳定或事实确认" in dashboard.text
    for reason in (
        "可试用抓取：公开直连且首次探测合格",
        "仅用于发现，需回源确认",
        "不可试用抓取：来源当前未就绪",
    ):
        assert reason in targets.text
    for sensitive_name in ("DATABASE_URL", "Authorization", "Cookie"):
        assert sensitive_name not in dashboard.text
        assert sensitive_name not in targets.text


def test_trial_dashboard_reads_latest_snapshots_through_source_repository(
    db_session, monkeypatch
) -> None:
    seen_source_ids: list[str] = []
    original = SourceRepository.latest_probe_snapshot

    def track_latest_snapshot(self, source_id: str):
        seen_source_ids.append(source_id)
        return original(self, source_id)

    monkeypatch.setattr(SourceRepository, "latest_probe_snapshot", track_latest_snapshot)

    DashboardQueryService(db_session).summary()

    assert set(seen_source_ids) == {"github-openai-python", "search-ai", "x-openai"}
