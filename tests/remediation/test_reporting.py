from datetime import UTC, datetime


def test_report_contains_each_entry_without_query_or_fragment():
    from newsradar.remediation.reporting import render_remediation_report
    from newsradar.remediation.schema import FailureCategory, RemediationEntry, RemediationManifest

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
            ),
        ),
    )

    report = render_remediation_report(manifest)

    assert "alpha" in report
    assert "端点可能已变化" in report
    assert "https://example.test/feed" in report
    assert "token=secret" not in report
    assert "#fragment" not in report
