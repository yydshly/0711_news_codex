from __future__ import annotations

from dataclasses import dataclass

import psutil
import pytest

from newsradar.desktop.controller import DesktopController
from newsradar.desktop.processes import ProcessCleanupResult


@dataclass
class FakeProcess:
    pid: int = 321
    exit_code: int | None = None
    created_at: float = 1.0
    create_time_error: Exception | None = None

    def poll(self) -> int | None:
        return self.exit_code

    def create_time(self) -> float:
        if self.create_time_error is not None:
            raise self.create_time_error
        return self.created_at


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


def test_controller_recovers_orphans_when_supervisor_exits_before_identity_capture() -> None:
    process = FakeProcess(
        pid=321,
        exit_code=17,
        create_time_error=psutil.NoSuchProcess(321),
    )
    calls: list[str] = []
    controller = DesktopController(
        process_factory=lambda _command: process,
        probe=lambda _url: False,
        tree_stopper=lambda identity: calls.append(f"tree:{identity.pid}")
        or ProcessCleanupResult(),
        orphan_cleaner=lambda: calls.append("orphans") or ProcessCleanupResult(),
    )

    status = controller.start_service()

    assert status.state == "failed"
    assert status.message_zh == "News Codex 服务启动失败，请查看本地运行日志。"
    assert calls == ["orphans", "orphans"]
    assert controller._owned_process is None


def test_controller_retries_orphan_recovery_after_fast_exit_cleanup_failure() -> None:
    process = FakeProcess(
        pid=321,
        exit_code=17,
        create_time_error=psutil.NoSuchProcess(321),
    )
    cleanup_results = iter(
        [
            ProcessCleanupResult(),
            ProcessCleanupResult(failed_pids=(401,)),
            ProcessCleanupResult(),
        ]
    )
    calls: list[str] = []
    controller = DesktopController(
        process_factory=lambda _command: process,
        probe=lambda _url: False,
        tree_stopper=lambda identity: calls.append(f"tree:{identity.pid}")
        or ProcessCleanupResult(),
        orphan_cleaner=lambda: calls.append("orphans") or next(cleanup_results),
    )

    startup_status = controller.start_service()
    assert controller._owned_process is process

    retry_status = controller.stop_service()

    assert startup_status.state == "failed"
    assert retry_status.state == "stopped"
    assert calls == ["orphans", "orphans", "orphans"]
    assert controller._owned_process is None


@pytest.mark.parametrize(
    "identity_error",
    [psutil.AccessDenied(321), psutil.ZombieProcess(321)],
)
def test_controller_keeps_live_supervisor_when_identity_capture_is_inaccessible(
    identity_error: Exception,
) -> None:
    process = FakeProcess(pid=321, create_time_error=identity_error)
    calls: list[str] = []
    controller = DesktopController(
        process_factory=lambda _command: process,
        probe=lambda _url: False,
        tree_stopper=lambda identity: calls.append(f"tree:{identity.pid}")
        or ProcessCleanupResult(),
        orphan_cleaner=lambda: calls.append("orphans") or ProcessCleanupResult(),
    )

    startup_status = controller.start_service()

    assert startup_status.state == "failed"
    assert startup_status.message_zh == (
        "无法安全确认 News Codex 服务进程身份，请稍后重试。"
    )
    assert calls == ["orphans"]
    assert controller._owned_process is process

    live_retry_status = controller.stop_service()
    assert live_retry_status.state == "failed"
    assert calls == ["orphans", "orphans"]
    assert controller._owned_process is process

    process.exit_code = 0
    exited_retry_status = controller.stop_service()

    assert exited_retry_status.state == "stopped"
    assert calls == ["orphans", "orphans", "orphans"]
    assert controller._owned_process is None


def test_controller_never_stops_an_unowned_running_service() -> None:
    stopped: list[int] = []
    controller = DesktopController(
        port=8767,
        probe=lambda _url: True,
        tree_stopper=lambda identity: stopped.append(identity.pid)
        or ProcessCleanupResult(),
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

    status = controller.start_service()

    assert status.state == "failed"
    assert status.message_zh == "检测到无法清理的 News Codex 遗留进程，请退出旧实例后重试。"
    assert probe_called is False


def test_controller_retries_failed_initial_cleanup_before_probe_or_spawn() -> None:
    calls: list[str] = []
    cleanup_results = iter(
        [
            ProcessCleanupResult(failed_pids=(123,)),
            ProcessCleanupResult(failed_pids=(123,)),
            ProcessCleanupResult(),
        ]
    )

    def cleanup() -> ProcessCleanupResult:
        calls.append("cleanup")
        return next(cleanup_results)

    controller = DesktopController(
        process_factory=lambda _command: calls.append("spawn") or FakeProcess(),
        probe=lambda _url: calls.append("probe") or True,
        orphan_cleaner=cleanup,
    )

    assert controller.start_service().state == "failed"
    assert controller.start_service().state == "failed"
    assert calls == ["cleanup", "cleanup"]

    assert controller.start_service().state == "external_running"
    assert calls == ["cleanup", "cleanup", "cleanup", "probe"]


def test_controller_cleans_exited_supervisor_before_reporting_startup_failure() -> None:
    process = FakeProcess(pid=321, exit_code=17)
    calls: list[str] = []
    controller = DesktopController(
        process_factory=lambda _command: process,
        probe=lambda _url: False,
        tree_stopper=lambda identity: calls.append(f"tree:{identity.pid}")
        or ProcessCleanupResult((identity.pid,), (identity.pid,), ()),
        orphan_cleaner=lambda: calls.append("orphans") or ProcessCleanupResult(),
    )

    status = controller.start_service()

    assert status.state == "failed"
    assert calls == ["orphans", "tree:321", "orphans"]
    assert controller._owned_process is None


def test_controller_keeps_exited_supervisor_for_retry_when_cleanup_fails() -> None:
    process = FakeProcess(pid=321, exit_code=17)
    orphan_cleanup_results = iter(
        [
            ProcessCleanupResult(),
            ProcessCleanupResult(failed_pids=(process.pid,)),
            ProcessCleanupResult(),
        ]
    )
    calls: list[str] = []
    controller = DesktopController(
        process_factory=lambda _command: process,
        probe=lambda _url: False,
        tree_stopper=lambda identity: calls.append(f"tree:{identity.pid}")
        or ProcessCleanupResult((identity.pid,), (identity.pid,), ()),
        orphan_cleaner=lambda: calls.append("orphans") or next(orphan_cleanup_results),
    )

    startup_status = controller.start_service()
    assert controller._owned_process is process

    retry_status = controller.stop_service()

    assert startup_status.state == "failed"
    assert controller._owned_process is None
    assert retry_status.state == "stopped"
    assert calls == ["orphans", "tree:321", "orphans", "tree:321", "orphans"]


def test_controller_stops_the_complete_owned_tree() -> None:
    process = FakeProcess(pid=321, created_at=12.5)
    stopped: list[tuple[int, float]] = []
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
        tree_stopper=lambda identity: stopped.append(
            (identity.pid, identity.create_time)
        )
        or ProcessCleanupResult((identity.pid,), (identity.pid,), ()),
        orphan_cleaner=lambda: ProcessCleanupResult(),
    )
    controller.start_service()

    status = controller.stop_service()

    assert status.state == "stopped"
    assert stopped == [(321, 12.5)]


def test_controller_reports_bounded_startup_timeout() -> None:
    controller = DesktopController(
        port=8767,
        process_factory=lambda _command: FakeProcess(),
        probe=lambda _url: False,
        sleeper=lambda _seconds: None,
        health_attempts=2,
        tree_stopper=lambda _identity: ProcessCleanupResult(),
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
    probe_calls = 0

    def probe(_url: str) -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return probe_calls >= 2

    controller = DesktopController(
        process_factory=lambda _command: process,
        probe=probe,
        tree_stopper=lambda identity: stopped.append(identity.pid)
        or next(cleanup_results),
        orphan_cleaner=lambda: ProcessCleanupResult(),
    )
    controller.start_service()

    first_status = controller.stop_service()
    assert controller._owned_process is process

    second_status = controller.stop_service()

    assert first_status.state == "failed"
    assert second_status.state == "stopped"
    assert stopped == [process.pid, process.pid]
