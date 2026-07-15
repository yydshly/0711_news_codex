from __future__ import annotations

import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class ManagedProcess(Protocol):
    def poll(self) -> int | None: ...

    def send_signal(self, signum: int) -> None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


ProcessFactory = Callable[[tuple[str, ...]], ManagedProcess]


@dataclass(frozen=True)
class ChildSpec:
    name: str
    args: tuple[str, ...]


class RuntimeSupervisor:
    """Run the local Web and Worker processes as one bounded runtime."""

    def __init__(
        self,
        process_factory: ProcessFactory | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        worker_id: str | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._process_factory = process_factory or self._spawn
        self.host = host
        self.port = port
        self.worker_id = worker_id
        self._sleeper = sleeper
        self.children: list[ManagedProcess] = []

    def start(self) -> None:
        if self.children:
            raise RuntimeError("runtime supervisor has already started")
        self.children = [self._process_factory(spec.args) for spec in self.specifications()]

    def stop(self, signum: int = signal.SIGTERM) -> None:
        for child in self.children:
            if child.poll() is None:
                child.send_signal(signum)
        for child in self.children:
            if child.poll() is None:
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    child.wait(timeout=5)
            else:
                child.wait(timeout=0)

    def run(self) -> int:
        self.start()
        try:
            while True:
                for child in self.children:
                    exit_code = child.poll()
                    if exit_code is not None:
                        self.stop()
                        return exit_code if exit_code != 0 else 1
                self._sleeper(0.2)
        except KeyboardInterrupt:
            self.stop(signal.SIGINT)
            return 0

    @staticmethod
    def _spawn(args: tuple[str, ...]) -> ManagedProcess:
        return subprocess.Popen(args)  # noqa: S603

    def specifications(self) -> tuple[ChildSpec, ChildSpec]:
        invoke_cli = "from newsradar.cli import app; app()"
        worker_args = [sys.executable, "-c", invoke_cli, "worker"]
        if self.worker_id:
            worker_args.extend(["--worker-id", self.worker_id])
        worker_args.append("--forever")
        return (
            ChildSpec(
                "web",
                (
                    sys.executable,
                    "-c",
                    invoke_cli,
                    "web",
                    "--host",
                    self.host,
                    "--port",
                    str(self.port),
                ),
            ),
            ChildSpec("worker", tuple(worker_args)),
        )
