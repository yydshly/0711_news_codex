from datetime import UTC, datetime


def test_report_contains_each_entry_without_query_or_fragment():
    from newsradar.remediation.reporting import render_remediation_report
    from newsradar.remediation.schema import (
        FailureCategory,
        RemediationEntry,
        RemediationEvidence,
        RemediationManifest,
    )

    manifest = RemediationManifest(
        baseline_at=datetime(2026, 7, 13, tzinfo=UTC),
        entries=(
            RemediationEntry(
                source_id="alpha",
                source_name="Alpha",
                original_probe_id=7,
                original_finished_at=datetime(2026, 7, 13, tzinfo=UTC),
                category=FailureCategory.ENDPOINT_CHANGED,
                reason_zh="端点可能已变化",
                next_action_zh="检查官方 RSS 或 API",
                access_url="https://example.test/feed?token=secret#fragment",
                evidence=RemediationEvidence(
                    candidate_key="official-feed",
                    candidate_kind="rss",
                    acquisition_outcome="succeeded",
                    acquisition_sample_count=5,
                    content_outcome="success",
                    content_sample_count=5,
                    field_completeness=1.0,
                    trial_eligible=True,
                    trial_reason_zh="公开直连且样本合格",
                    fetch_outcome="succeeded",
                    fetch_items_received=5,
                    fetch_items_inserted=5,
                    html_research_status="不涉及（RSS/API 主路径）",
                    final_conclusion_zh="试用抓取已验证",
                ),
            ),
        ),
        before_trial_count=16,
        after_trial_count=37,
    )

    report = render_remediation_report(manifest)

    assert "本批强绑定试用验证：1" in report

    assert "alpha" in report
    assert "端点可能已变化" in report
    assert "https://example.test/feed" in report
    assert "token=secret" not in report
    assert "#fragment" not in report
    assert "修复前可试用来源：16" in report
    assert "修复后可试用来源：37" in report
    assert "official-feed / rss" in report
    assert "succeeded / 5 条" in report
    assert "success / 5 条 / 100%" in report
    assert "试用抓取已验证" in report

    unsafe = manifest.model_copy(
        update={
            "entries": (
                manifest.entries[0].model_copy(
                    update={"access_url": "https://user:secret@example.test/feed"}
                ),
            )
        }
    )
    assert "user:secret" not in render_remediation_report(unsafe)
