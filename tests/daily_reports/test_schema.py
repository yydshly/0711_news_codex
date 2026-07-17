import pytest

from newsradar.daily_reports.schema import (
    ALLOWED_WINDOW_HOURS,
    DailyReportEditorialReviewDraft,
    EditorialDecision,
    ReportSection,
    ReportStatus,
    validate_window_hours,
)


def test_daily_report_enums_and_windows_are_closed() -> None:
    assert ALLOWED_WINDOW_HOURS == frozenset({24, 48, 72})
    assert ReportStatus.DRAFT.value == "draft"
    assert ReportStatus.ARCHIVED.value == "archived"
    assert ReportSection.CONFIRMED.value == "confirmed"
    assert ReportSection.EMERGING.value == "emerging"
    assert validate_window_hours(24) == 24

    for invalid in (0, 12, 25, 96, True, "24"):
        with pytest.raises(ValueError, match="invalid_daily_report_window"):
            validate_window_hours(invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ("keep", "needs_evidence", "exclude", "duplicate"))
def test_editorial_decision_is_closed(value: str) -> None:
    assert EditorialDecision(value).value == value


def test_editorial_review_draft_trims_and_rejects_invalid_text() -> None:
    review = DailyReportEditorialReviewDraft.create(
        decision="keep",
        zh_title=" 标题 ",
        zh_summary=" 概述 ",
        review_recommendation=" 建议 ",
        evidence_assessment=" 评估 ",
    )

    assert review.zh_title == "标题"
    assert review.zh_summary == "概述"
    assert review.review_recommendation == "建议"
    assert review.evidence_assessment == "评估"

    with pytest.raises(ValueError, match="invalid_daily_report_editorial_title"):
        DailyReportEditorialReviewDraft.create(
            decision="keep",
            zh_title=" ",
            zh_summary="概述",
            review_recommendation="建议",
            evidence_assessment="评估",
        )
