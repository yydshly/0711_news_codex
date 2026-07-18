from __future__ import annotations

import subprocess
from dataclasses import dataclass

from newsradar.desktop.controller import DesktopController


@dataclass
class FakeProcess:
    exit_code: int | None = None
    terminated: bool = False

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True
        self.exit_code = 0

    def wait(self, timeout: float | None = None) -> int:
        assert timeout is not None
        return 0


@dataclass
class StubbornProcess:
    terminate_calls: int = 0

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        self.terminate_calls += 1

    def wait(self, timeout: float | None = None) -> int:
        raise subprocess.TimeoutExpired("newsradar", timeout)


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
    controller = DesktopController(port=8767, probe=lambda _url: True)

    status = controller.stop_service()

    assert status.state == "external_running"


def test_controller_stops_only_its_owned_process() -> None:
    process = FakeProcess()
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
    )
    controller.start_service()

    status = controller.stop_service()

    assert status.state == "stopped"
    assert process.terminated is True


def test_controller_reports_bounded_startup_timeout() -> None:
    controller = DesktopController(
        port=8767,
        process_factory=lambda _command: FakeProcess(),
        probe=lambda _url: False,
        sleeper=lambda _seconds: None,
        health_attempts=2,
    )

    status = controller.start_service()

    assert status.state == "failed"
    assert "未在限定时间内启动" in status.message_zh


def test_controller_keeps_owned_process_after_stop_timeout_for_retry() -> None:
    process = StubbornProcess()
    controller = DesktopController(
        port=8767,
        process_factory=lambda _command: process,
        probe=lambda _url: False,
        sleeper=lambda _seconds: None,
    )
    controller._owned_process = process

    first_status = controller.stop_service()
    second_status = controller.stop_service()

    assert first_status.state == "failed"
    assert second_status.state == "failed"
    assert process.terminate_calls == 2
