from __future__ import annotations

from dataclasses import dataclass

from newsradar.desktop.controller import DesktopController
from newsradar.desktop.processes import ProcessCleanupResult


@dataclass
class FakeProcess:
    pid: int = 321
    exit_code: int | None = None

    def poll(self) -> int | None:
        return self.exit_code


def test_controller_starts_missing_service_and_waits_for_health() -> None:
    process = FakeProcess()
    commands: list[tuple[str, ...]] = []
    attempts = 0

    def probe(_url: str) -> bool:
        nonlocal attempts
        attempts += 1
        return attempts == 2

    controller = DesktopController(
        port=8767,
        process_factory=lambda command: commands.append(command) or process,
        probe=probe,
        sleeper=lambda _seconds: None,
    )

    status = controller.start_service()

    assert status.state == "running"
    assert attempts == 2
    assert commands[0][-5:] == ("serve", "--host", "127.0.0.1", "--port", "8767")


def test_controller_never_stops_an_unowned_running_service() -> None:
    stopped: list[int] = []
    controller = DesktopController(
        port=8767,
        probe=lambda _url: True,
        tree_stopper=lambda pid: stopped.append(pid) or ProcessCleanupResult(),
    )

    status = controller.stop_service()

    assert status.state == "external_running"
    assert stopped == []


def test_controller_cleans_orphans_before_health_probe() -> None:
    calls: list[str] = []
    controller = DesktopController(
        probe=lambda _url: calls.append("probe") or True,
        orphan_cleaner=lambda: calls.append("cleanup") or ProcessCleanupResult(),
    )

    assert controller.start_service().state == "external_running"

    assert calls == ["cleanup", "probe"]


def test_controller_returns_failed_status_when_orphan_cleanup_fails() -> None:
    probe_called = False

    def probe(_url: str) -> bool:
        nonlocal probe_called
        probe_called = True
        return False

    controller = DesktopController(
        probe=probe,
        orphan_cleaner=lambda: ProcessCleanupResult(failed_pids=(123,)),
    )

    assert controller.start_service().state == "failed"
    assert probe_called is False


def test_controller_stops_the_complete_owned_tree() -> None:
    process = FakeProcess(pid=321)
    stopped: list[int] = []
    probe_calls = 0

    def probe(_url: str) -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return probe_calls >= 2

    controller = DesktopController(
        port=8767,
        process_factory=lambda _command: process,
        probe=probe,
        sleeper=lambda _seconds: None,
        tree_stopper=lambda pid: stopped.append(pid)
        or ProcessCleanupResult((pid,), (pid,), ()),
        orphan_cleaner=lambda: ProcessCleanupResult(),
    )
    controller.start_service()

    status = controller.stop_service()

    assert status.state == "stopped"
    assert stopped == [321]


def test_controller_reports_bounded_startup_timeout() -> None:
    controller = DesktopController(
        port=8767,
        process_factory=lambda _command: FakeProcess(),
        probe=lambda _url: False,
        sleeper=lambda _seconds: None,
        health_attempts=2,
        tree_stopper=lambda _pid: ProcessCleanupResult(),
    )

    status = controller.start_service()

    assert status.state == "failed"
    assert "未在限定时间内启动" in status.message_zh


def test_controller_keeps_owned_process_after_failed_cleanup_for_retry() -> None:
    process = FakeProcess()
    cleanup_results = iter(
        [
            ProcessCleanupResult(failed_pids=(process.pid,)),
            ProcessCleanupResult((process.pid,), (process.pid,), ()),
        ]
    )
    stopped: list[int] = []
    controller = DesktopController(
        probe=lambda _url: False,
        tree_stopper=lambda pid: stopped.append(pid) or next(cleanup_results),
        orphan_cleaner=lambda: ProcessCleanupResult(),
    )
    controller._owned_process = process

    first_status = controller.stop_service()
    assert controller._owned_process is process

    second_status = controller.stop_service()

    assert first_status.state == "failed"
    assert second_status.state == "stopped"
    assert stopped == [process.pid, process.pid]
