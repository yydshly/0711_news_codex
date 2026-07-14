from __future__ import annotations

from datetime import UTC, datetime

from newsradar.ingestion.coverage_closure import (
    CoverageClosureEntry,
    CoverageClosurePlan,
    CoverageClosureState,
)
from newsradar.ingestion.coverage_closure_reporting import (
    COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS,
    CatalogAdjustment,
    render_coverage_closure_report,
)
from newsradar.ingestion.coverage_closure_runtime import ClosureOperation, CoverageEvidence


def _plan(state: CoverageClosureState) -> CoverageClosurePlan:
    return CoverageClosurePlan(
        tuple(
            CoverageClosureEntry(
                source_id,
                source_id,
                state,
                None,
                "可试用抓取：公开直连且首次探测合格",
            )
            for source_id in COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS
            if source_id != "qwen3-releases"
        )
    )


def test_report_is_chinese_auditable_and_scrubbed() -> None:
    before = _plan(CoverageClosureState.QUEUEABLE)
    after = _plan(CoverageClosureState.COVERED)
    report = render_coverage_closure_report(
        before=before,
        after=after,
        operations=(ClosureOperation("arxiv-cs-cl", 11, "succeeded"),),
        before_evidence=(CoverageEvidence("arxiv-cs-cl", None, None, 0),),
        after_evidence=(CoverageEvidence("arxiv-cs-cl", "succeeded", None, 5),),
        adjustments=(
            CatalogAdjustment(
                "qwen3-releases",
                "退出就绪直连统计",
                "Authorization: Bearer sk-secret must not be shown.",
                "官方仓库出现 Release 后重新探测。",
            ),
        ),
        generated_at=datetime(2026, 7, 14, tzinfo=UTC),
    )

    assert "# 来源覆盖收口 v1 验收报告" in report
    assert "执行前" in report and "执行后" in report
    assert "已覆盖" in report and "仍未收口的来源" in report
    assert "OpenAI YouTube" in report
    assert "MiniMax" in report
    assert "sk-secret" not in report
    assert "DATABASE_URL" not in report
    assert "Authorization: Bearer" not in report
    assert "本轮新增 RawItem" in report
    for source_id in COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS:
        assert f"`{source_id}`" in report


def test_report_rejects_a_missing_baseline_conclusion() -> None:
    before = CoverageClosurePlan(())
    after = CoverageClosurePlan(())

    try:
        render_coverage_closure_report(
            before=before,
            after=after,
            operations=(),
            before_evidence=(),
            after_evidence=(),
            adjustments=(),
            generated_at=datetime(2026, 7, 14, tzinfo=UTC),
        )
    except ValueError as error:
        assert str(error) == "missing_baseline_conclusion:arxiv-cs-cl"
    else:
        raise AssertionError("missing baseline source must not be silently omitted")
