from datetime import datetime

from newsradar.events.trends import HeatSnapshot, TrendDirection, assess_trend


def snapshot(when: str, heat: int) -> HeatSnapshot:
    return HeatSnapshot(datetime.fromisoformat(when.replace("Z", "+00:00")), heat)


def test_trend_uses_immutable_seven_day_snapshots() -> None:
    trend = assess_trend(
        current=snapshot("2026-07-16T00:00:00Z", 82),
        history=(snapshot("2026-07-15T00:00:00Z", 60),),
    )

    assert trend.direction is TrendDirection.RISING
    assert trend.delta == 22
    assert trend.baseline_heat == 60


def test_trend_uses_latest_snapshot_at_least_24_hours_old() -> None:
    trend = assess_trend(
        current=snapshot("2026-07-16T12:00:00Z", 50),
        history=(
            snapshot("2026-07-15T11:59:59Z", 90),
            snapshot("2026-07-15T12:00:00Z", 70),
            snapshot("2026-07-15T12:01:00Z", 10),
        ),
    )

    assert trend.direction is TrendDirection.COOLING
    assert trend.delta == -20
    assert trend.baseline_heat == 70


def test_first_snapshot_is_rising_with_a_stored_reason() -> None:
    trend = assess_trend(current=snapshot("2026-07-16T00:00:00Z", 50), history=())

    assert trend.direction is TrendDirection.RISING
    assert trend.reason == "trend:first_snapshot"
