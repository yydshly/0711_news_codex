from pathlib import Path

from tests.research.test_failure_remediation_catalog import FAILED_BASELINE_IDS


def test_final_source_remediation_report_contains_the_full_verified_batch() -> None:
    report = Path("reports/source-failure-remediation.md").read_text(encoding="utf-8")

    assert "固定失败 Target 数：27" in report
    assert "修复前可试用来源：16" in report
    assert "修复后可试用来源：37" in report
    assert "试用抓取已验证" in report
    for source_id in FAILED_BASELINE_IDS:
        assert f"`{source_id}`" in report

    lowered = report.lower()
    assert "authorization:" not in lowered
    assert "cookie:" not in lowered
    assert "database_url" not in lowered
    assert "minimax_api_key" not in lowered
    assert "proxy=" not in lowered
