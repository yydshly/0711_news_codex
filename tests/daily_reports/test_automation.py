from datetime import UTC, date, datetime, time

from newsradar.daily_reports.automation import due_schedule, next_daily_run


def test_next_daily_run_converts_shanghai_schedule_to_utc() -> None:
    now = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)

    assert next_daily_run(now, time(7, 30)) == datetime(2026, 7, 18, 23, 30, tzinfo=UTC)


def test_next_daily_run_moves_to_tomorrow_at_the_scheduled_time() -> None:
    now = datetime(2026, 7, 17, 23, 30, tzinfo=UTC)

    assert next_daily_run(now, time(7, 30)) == datetime(2026, 7, 18, 23, 30, tzinfo=UTC)


def test_due_schedule_returns_today_once_after_daily_time() -> None:
    now = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)

    due = due_schedule(now, None)

    assert due is not None
    assert due.schedule_date == date(2026, 7, 18)
    assert due.due_at == datetime(2026, 7, 17, 23, 30, tzinfo=UTC)


def test_due_schedule_is_absent_before_daily_time_or_after_today_is_scheduled() -> None:
    before_due = datetime(2026, 7, 17, 23, 29, tzinfo=UTC)
    after_due = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)

    assert due_schedule(before_due, None) is None
    assert due_schedule(after_due, date(2026, 7, 18)) is None
