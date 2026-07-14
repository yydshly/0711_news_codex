from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from newsradar.db.models import (
    EventItemRecord,
    EventModelRunRecord,
    EventVersionRecord,
    ModelUsageRecord,
    OperationRunRecord,
    RawItemProcessingRecord,
    RawItemRecord,
)
from newsradar.web.app import create_app
from tests.web.test_event_routes import _add_event

NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)


def test_home_renders_current_quality_metrics_and_explanatory_event_cards(
    db_session, monkeypatch
):
    _add_event(db_session, 101, "confirmed", "当前确认事件")
    _add_event(db_session, 102, "emerging", "当前新兴线索")
    selected = []
    for index in range(2):
        raw = RawItemRecord(
            source_id="github-openai-python",
            external_id=f"home-quality-{index}",
            canonical_url=f"https://example.com/home-quality/{index}",
            payload={},
            title=f"处理样本 {index}",
            published_at=datetime.now(UTC) - timedelta(minutes=index),
        )
        db_session.add(raw)
        selected.append(raw)
    db_session.flush()
    db_session.add_all(
        [
            RawItemProcessingRecord(
                raw_item_id=selected[0].id,
                stage="relevance",
                algorithm_version="relevance-v2",
                outcome="included",
                score=90,
                reason_codes=["ai_product_action"],
                details={},
            ),
            RawItemProcessingRecord(
                raw_item_id=selected[1].id,
                stage="relevance",
                algorithm_version="relevance-v2",
                outcome="excluded",
                score=10,
                reason_codes=["generic_technology"],
                details={},
            ),
        ]
    )
    db_session.add(
        OperationRunRecord(
            operation_type="event_pipeline",
            trigger="manual",
            status="succeeded",
            requested_scope={"window_hours": 72},
            result_summary={},
            finished_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    db_session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    for expected in (
        "当前确认事件",
        "当前新兴线索",
        "72 小时已处理",
        "2 / 2",
        "排除 1",
        "独立证据 1",
        "重要度",
        "可信度",
        "热度",
        "影响行业采用。",
    ):
        assert expected in response.text
    for score in ("83.0", "90.0", "88"):
        assert score in response.text


def test_event_detail_explains_six_scores_and_redacts_untrusted_sensitive_text(
    db_session, monkeypatch
):
    _add_event(db_session, 103, "confirmed", "<script>alert(1)</script>安全事件")
    raw = RawItemRecord(
        source_id="github-openai-python",
        external_id="detail-sensitive",
        canonical_url="https://example.com/report?token=query-secret",
        original_url="https://example.com/report?token=query-secret",
        payload={"body": "正文不应展示"},
        title="<img src=x onerror=alert(1)>原始证据",
        published_at=NOW,
    )
    db_session.add(raw)
    db_session.flush()
    db_session.add(EventItemRecord(event_id=103, raw_item_id=raw.id, added_version_number=1))
    version = db_session.query(EventVersionRecord).filter_by(event_id=103).one()
    version.payload = {
        "enrichment": {
            "why_it_matters": "Authorization: Bearer secret；MINIMAX_API_KEY=secret",
            "limitations": ["Cookie=session-secret", "not_peer_reviewed"],
            "origin": "rule_fallback",
            "prompt": "提示全文不应展示",
        },
        "evidence": [
            {
                "raw_item_id": raw.id,
                "role": "official",
                "root_evidence_key": "official:safe",
                "independent": True,
            }
        ],
        "model_runs": [
            {
                "model": "MiniMax-M2.7-highspeed",
                "purpose": "event_enrichment",
                "outcome": "fallback",
                "latency_ms": 245.0,
                "prompt": "提示全文不应展示",
                "error": "API 原始错误不应展示",
            }
        ],
    }
    usage = ModelUsageRecord(
        purpose="event_enrichment",
        model="MiniMax-M2.7-highspeed",
        input_tokens=999,
        output_tokens=888,
        latency_ms=245.0,
        outcome="fallback",
        error="API 原始错误：Cookie=must-not-leak",
    )
    db_session.add(usage)
    db_session.flush()
    db_session.add(
        EventModelRunRecord(
            event_id=103,
            model_usage_id=usage.id,
            stage="event_enrichment",
            algorithm_version="MiniMax-M2.7-highspeed",
        )
    )
    db_session.commit()
    monkeypatch.setattr("newsradar.web.app.create_session", lambda: db_session)

    with TestClient(create_app()) as client:
        response = client.get("/events/103")

    assert response.status_code == 200
    for label in ("AI 相关性", "来源覆盖", "来源权威性", "时效", "互动热度", "新颖性"):
        assert label in response.text
    for expected in (
        "独立证据根 1",
        "模型运行摘要",
        "MiniMax-M2.7-highspeed",
        "事件中文增强",
        "规则回退",
        "245.0 毫秒",
        "未经同行评审",
        "北京时间",
    ):
        assert expected in response.text
    for forbidden in (
        "Authorization",
        "Cookie",
        "MINIMAX_API_KEY",
        "query-secret",
        "提示全文不应展示",
        "正文不应展示",
        "must-not-leak",
        "input_tokens",
        "output_tokens",
        "<script>",
        "<img src=x",
    ):
        assert forbidden not in response.text
    assert 'href="https://example.com/report"' in response.text
