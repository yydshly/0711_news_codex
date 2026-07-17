from __future__ import annotations

import pytest

from newsradar.daily_reports.schema import (
    DailyReportEditorialReviewDraft,
    DailyReportOverviewEditorialReviewDraft,
)
from newsradar.daily_reports.text_integrity import has_suspicious_question_run


def test_detects_only_a_run_of_four_or_more_ascii_question_marks() -> None:
    assert has_suspicious_question_run("正常？") is False
    assert has_suspicious_question_run("FAQ???") is False
    assert has_suspicious_question_run("损坏????内容") is True


@pytest.mark.parametrize(
    "field",
    ["zh_title", "zh_summary", "review_recommendation", "evidence_assessment"],
)
def test_editorial_review_drafts_reject_corrupted_text(field: str) -> None:
    values = {
        "decision": "keep",
        "zh_title": "中文标题",
        "zh_summary": "中文概述。",
        "review_recommendation": "继续关注后续公开材料。",
        "evidence_assessment": "当前证据可供审核。",
    }
    values[field] = "????"

    with pytest.raises(ValueError, match="daily_report_text_corrupted"):
        DailyReportEditorialReviewDraft.create(**values)
    with pytest.raises(ValueError, match="daily_report_text_corrupted"):
        DailyReportOverviewEditorialReviewDraft.create(**values)
