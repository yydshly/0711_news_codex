from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from newsradar.desktop.launcher import runtime_command


class ManagedProcess(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


ProcessFactory = Callable[[tuple[str, ...]], ManagedProcess]
HealthProbe = Callable[[str], bool]


@dataclass(frozen=True)
class DesktopStatus:
    state: Literal["running", "stopped", "external_running", "failed"]
    message_zh: str


class DesktopController:
    """Own only the service process this controller created."""

    def __init__(
        self,
        *,
        port: int = 8767,
        process_factory: ProcessFactory | None = None,
        probe: HealthProbe | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        health_attempts: int = 20,
        health_interval_seconds: float = 0.5,
    ) -> None:
        self.port = port
        self._process_factory = process_factory or self._spawn
        self._probe = probe or self._http_probe
        self._sleeper = sleeper
        self._health_attempts = health_attempts
        self._health_interval_seconds = health_interval_seconds
        self._owned_process: ManagedProcess | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/daily-reports"

    def status(self) -> DesktopStatus:
        if self._owned_process is not None and self._owned_process.poll() is None:
            return DesktopStatus("running", "News Codex 正在运行。")
        if self._probe(self.url):
            return DesktopStatus("external_running", "News Codex 已由其他进程运行。")
        return DesktopStatus("stopped", "News Codex 当前未运行。")

    def start_service(self) -> DesktopStatus:
        current = self.status()
        if current.state in {"running", "external_running"}:
            return current
        self._owned_process = self._process_factory(self._service_command())
        for attempt in range(self._health_attempts):
            if self._probe(self.url):
                return DesktopStatus("running", "News Codex 已启动。")
            if self._owned_process.poll() is not None:
                self._owned_process = None
                return DesktopStatus("failed", "News Codex 服务启动失败，请查看本地运行日志。")
            if attempt < self._health_attempts - 1:
                self._sleeper(self._health_interval_seconds)
        self.stop_service()
        return DesktopStatus("failed", "News Codex 未在限定时间内启动，请查看本地运行日志。")

    def stop_service(self) -> DesktopStatus:
        if self._owned_process is None:
            if self._probe(self.url):
                return DesktopStatus("external_running", "服务由其他进程运行，桌面窗口不会停止它。")
            return DesktopStatus("stopped", "News Codex 已停止。")
        process = self._owned_process
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                return DesktopStatus("failed", "服务停止超时，请检查本地运行日志。")
        self._owned_process = None
        return DesktopStatus("stopped", "News Codex 已停止。")

    def shutdown(self) -> DesktopStatus:
        return self.stop_service()

    @staticmethod
    def _spawn(command: tuple[str, ...]) -> ManagedProcess:
        return subprocess.Popen(command)  # noqa: S603

    @staticmethod
    def _http_probe(url: str) -> bool:
        try:
            response = httpx.get(url, timeout=1.0, trust_env=False)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def _service_command(self) -> tuple[str, ...]:
        return runtime_command(
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
        )
