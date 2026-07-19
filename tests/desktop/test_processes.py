from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from newsradar.desktop import processes
from newsradar.desktop.launcher import INTERNAL_COMMAND_MARKER as MARKER


@dataclass
class FakeProcess:
    pid: int
    parent_pid: int
    executable: Path
    command: list[str]
    child_processes: list[FakeProcess] = field(default_factory=list)
    survives_terminate: bool = False
    terminate_error: Exception | None = None
    running: bool = True
    terminate_calls: int = 0
    kill_calls: int = 0

    def ppid(self) -> int:
        return self.parent_pid

    def exe(self) -> str:
        return str(self.executable)

    def cmdline(self) -> list[str]:
        return self.command

    def children(self, recursive: bool = False) -> list[FakeProcess]:
        if not recursive:
            return self.child_processes
        descendants = list(self.child_processes)
        for child in self.child_processes:
            descendants.extend(child.children(recursive=True))
        return descendants

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.terminate_error is not None:
            if isinstance(self.terminate_error, psutil.NoSuchProcess):
                self.running = False
            raise self.terminate_error
        if not self.survives_terminate:
            self.running = False

    def kill(self) -> None:
        self.kill_calls += 1
        self.running = False

    def is_running(self) -> bool:
        return self.running


def install_fake_backend(monkeypatch, processes_by_pid: list[FakeProcess]) -> None:
    by_pid = {process.pid: process for process in processes_by_pid}

    def fake_process(pid: int) -> FakeProcess:
        if pid not in by_pid:
            raise psutil.NoSuchProcess(pid)
        return by_pid[pid]

    def fake_wait_procs(
        candidates: list[FakeProcess], timeout: float
    ) -> tuple[list[FakeProcess], list[FakeProcess]]:
        assert timeout >= 0
        return (
            [process for process in candidates if not process.is_running()],
            [process for process in candidates if process.is_running()],
        )

    monkeypatch.setattr(processes.psutil, "process_iter", lambda: iter(processes_by_pid))
    monkeypatch.setattr(processes.psutil, "Process", fake_process)
    monkeypatch.setattr(processes.psutil, "wait_procs", fake_wait_procs)


def test_cleanup_selects_only_same_executable_orphan_web_and_worker(monkeypatch, tmp_path):
    executable = tmp_path / "NewsCodex.exe"
    orphan_web = FakeProcess(201, 999, executable, [str(executable), MARKER, "web"])
    orphan_worker = FakeProcess(202, 999, executable, [str(executable), MARKER, "worker"])
    manual_python = FakeProcess(203, 999, tmp_path / "python.exe", ["python", "-m", "newsradar"])
    live_child = FakeProcess(204, 205, executable, [str(executable), MARKER, "web"])
    supervisor = FakeProcess(205, 1, executable, [str(executable), MARKER, "serve"])
    install_fake_backend(
        monkeypatch,
        [orphan_web, orphan_worker, manual_python, live_child, supervisor],
    )

    result = processes.cleanup_orphaned_internal_processes(executable, current_pid=300)

    assert result.matched_pids == (201, 202)
    assert result.stopped_pids == (201, 202)
    assert manual_python.terminate_calls == 0
    assert live_child.terminate_calls == 0


def test_cleanup_reports_a_matched_process_that_cannot_be_terminated(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "NewsCodex.exe"
    inaccessible = FakeProcess(
        201,
        999,
        executable,
        [str(executable), MARKER, "worker"],
        terminate_error=psutil.AccessDenied(201),
    )
    install_fake_backend(monkeypatch, [inaccessible])

    result = processes.cleanup_orphaned_internal_processes(executable, current_pid=300)

    assert result.matched_pids == (201,)
    assert result.failed_pids == (201,)
    assert result.succeeded is False


def test_stop_owned_process_tree_kills_termination_survivors(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "NewsCodex.exe"
    child = FakeProcess(11, 10, executable, [str(executable), MARKER, "worker"])
    root = FakeProcess(
        10,
        1,
        executable,
        [str(executable), MARKER, "serve"],
        child_processes=[child],
        survives_terminate=True,
    )
    install_fake_backend(monkeypatch, [root, child])

    result = processes.stop_owned_process_tree(root.pid, timeout_seconds=0.1)

    assert result.matched_pids == (11, 10)
    assert result.stopped_pids == (11, 10)
    assert root.kill_calls == 1
    assert child.kill_calls == 0


def test_stop_owned_process_tree_treats_a_process_that_already_exited_as_stopped(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "NewsCodex.exe"
    root = FakeProcess(
        10,
        1,
        executable,
        [str(executable), MARKER, "serve"],
        terminate_error=psutil.NoSuchProcess(10),
    )
    install_fake_backend(monkeypatch, [root])

    result = processes.stop_owned_process_tree(root.pid, timeout_seconds=0.1)

    assert result.stopped_pids == (10,)
    assert result.failed_pids == ()


def test_cleanup_current_packaged_orphans_is_a_noop_when_not_frozen(monkeypatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert processes.cleanup_current_packaged_orphans() == processes.ProcessCleanupResult()
