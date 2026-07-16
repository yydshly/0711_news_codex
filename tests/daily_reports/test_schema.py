import pytest

from newsradar.daily_reports.schema import (
    ALLOWED_WINDOW_HOURS,
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
