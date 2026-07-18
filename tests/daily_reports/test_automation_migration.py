from newsradar.db.models import DailyAutomationConfigRecord, DailyReportRecord


def test_automation_config_model_defines_singleton_scheduler_contract() -> None:
    table = DailyAutomationConfigRecord.__table__

    assert set(table.columns.keys()) == {
        "id",
        "enabled",
        "timezone",
        "daily_time",
        "window_hours",
        "resource_profile",
        "last_scheduled_date",
        "last_retention_date",
        "last_run_id",
        "next_run_at",
        "created_at",
        "updated_at",
    }
    assert {
        constraint.name
        for constraint in table.constraints
        if constraint.name is not None
    } >= {
        "ck_daily_automation_singleton",
        "ck_daily_automation_window",
        "ck_daily_automation_resource_profile",
    }
    assert {
        index.name: tuple(column.name for column in index.columns)
        for index in table.indexes
    } == {"ix_daily_automation_next_run": ("enabled", "next_run_at")}
    assert DailyAutomationConfigRecord.enabled.default.arg is False
    assert DailyAutomationConfigRecord.window_hours.default.arg == 24
    assert DailyAutomationConfigRecord.last_retention_date.nullable
    assert next(iter(DailyAutomationConfigRecord.last_run_id.foreign_keys)).ondelete == "SET NULL"


def test_daily_report_model_includes_retention_timestamps_and_indexes() -> None:
    table = DailyReportRecord.__table__

    assert {"pinned_at", "deleted_at", "purge_after"} <= set(table.columns.keys())
    assert all(table.columns[name].nullable for name in ("pinned_at", "deleted_at", "purge_after"))
    assert {
        index.name: tuple(column.name for column in index.columns)
        for index in table.indexes
    }.items() >= {
        "ix_daily_reports_deleted_purge": ("deleted_at", "purge_after"),
        "ix_daily_reports_pinned_date": ("pinned_at", "report_date"),
    }.items()
