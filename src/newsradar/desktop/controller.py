from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx
import psutil

from newsradar.desktop.launcher import runtime_command
from newsradar.desktop.processes import (
    ProcessCleanupResult,
    ProcessIdentity,
    cleanup_current_packaged_orphans,
    stop_owned_process_tree,
)


class ManagedProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def create_time(self) -> float: ...


ProcessFactory = Callable[[tuple[str, ...]], ManagedProcess]
HealthProbe = Callable[[str], bool]
ProcessTreeStopper = Callable[[ProcessIdentity], ProcessCleanupResult]
OrphanCleaner = Callable[[], ProcessCleanupResult]
_ORPHAN_CLEANUP_FAILED_MESSAGE = (
    "检测到无法清理的 News Codex 遗留进程，请退出旧实例后重试。"
)
_PROCESS_IDENTITY_FAILED_MESSAGE = (
    "无法安全确认 News Codex 服务进程身份，请稍后重试。"
)


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
        tree_stopper: ProcessTreeStopper = stop_owned_process_tree,
        orphan_cleaner: OrphanCleaner = cleanup_current_packaged_orphans,
        sleeper: Callable[[float], None] = time.sleep,
        health_attempts: int = 20,
        health_interval_seconds: float = 0.5,
    ) -> None:
        self.port = port
        self._process_factory = process_factory or self._spawn
        self._probe = probe or self._http_probe
        self._tree_stopper = tree_stopper
        self._orphan_cleaner = orphan_cleaner
        self._sleeper = sleeper
        self._health_attempts = health_attempts
        self._health_interval_seconds = health_interval_seconds
        self._owned_process: ManagedProcess | None = None
        self._owned_process_identity: ProcessIdentity | None = None
        self._initial_orphan_cleanup_done = False

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
        if not self._initial_orphan_cleanup_done:
            cleanup = self._orphan_cleaner()
            if not cleanup.succeeded:
                return DesktopStatus("failed", _ORPHAN_CLEANUP_FAILED_MESSAGE)
            self._initial_orphan_cleanup_done = True
        current = self.status()
        if current.state in {"running", "external_running"}:
            return current
        self._owned_process = self._process_factory(self._service_command())
        try:
            self._owned_process_identity = ProcessIdentity(
                self._owned_process.pid,
                self._owned_process.create_time(),
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            if self._owned_process.poll() is not None:
                self._cleanup_owned_process()
                return DesktopStatus(
                    "failed",
                    "News Codex 服务启动失败，请查看本地运行日志。",
                )
            return DesktopStatus("failed", _PROCESS_IDENTITY_FAILED_MESSAGE)
        for attempt in range(self._health_attempts):
            if self._probe(self.url):
                return DesktopStatus("running", "News Codex 已启动。")
            if self._owned_process.poll() is not None:
                self._cleanup_owned_process()
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
        if not self._cleanup_owned_process():
            return DesktopStatus("failed", "News Codex 服务停止失败，请重试。")
        return DesktopStatus("stopped", "News Codex 已停止。")

    def shutdown(self) -> DesktopStatus:
        return self.stop_service()

    def _cleanup_owned_process(self) -> bool:
        process = self._owned_process
        if process is None:
            return True
        identity = self._owned_process_identity
        if identity is None:
            orphan_cleanup = self._orphan_cleaner()
            if not orphan_cleanup.succeeded or process.poll() is None:
                return False
            self._owned_process = None
            return True
        tree_cleanup = self._tree_stopper(identity)
        orphan_cleanup = self._orphan_cleaner()
        if not tree_cleanup.succeeded or not orphan_cleanup.succeeded:
            return False
        self._owned_process = None
        self._owned_process_identity = None
        return True

    @staticmethod
    def _spawn(command: tuple[str, ...]) -> ManagedProcess:
        return psutil.Popen(command)  # noqa: S603

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
