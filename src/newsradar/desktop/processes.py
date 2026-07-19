"""Bounded cleanup for processes started by the branded desktop executable."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import psutil

from newsradar.desktop.launcher import INTERNAL_COMMAND_MARKER

_PROCESS_ERRORS = (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess)
_INTERNAL_CHILD_ROLES = frozenset({"web", "worker"})


@dataclass(frozen=True, slots=True)
class ProcessCleanupResult:
    matched_pids: tuple[int, ...] = ()
    stopped_pids: tuple[int, ...] = ()
    failed_pids: tuple[int, ...] = ()

    @property
    def succeeded(self) -> bool:
        return not self.failed_pids


def _normalized_executable(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).resolve(strict=False)))


def _internal_role(command: list[str]) -> str | None:
    try:
        marker_index = command.index(INTERNAL_COMMAND_MARKER)
    except ValueError:
        return None
    if marker_index + 1 >= len(command):
        return None
    return command[marker_index + 1]


def _is_running(process: psutil.Process) -> bool | None:
    try:
        return process.is_running()
    except psutil.NoSuchProcess:
        return False
    except (psutil.AccessDenied, psutil.ZombieProcess):
        return None


def _result_for_processes(
    matched: list[psutil.Process],
    failed: set[int],
) -> ProcessCleanupResult:
    matched_pids = tuple(process.pid for process in matched)
    stopped: list[int] = []
    for process in matched:
        if process.pid in failed:
            continue
        if _is_running(process) is False:
            stopped.append(process.pid)
        else:
            failed.add(process.pid)
    return ProcessCleanupResult(matched_pids, tuple(stopped), tuple(sorted(failed)))


def stop_owned_process_tree(root_pid: int, timeout_seconds: float = 5.0) -> ProcessCleanupResult:
    """Stop a root process and its snapshot descendants within the supplied timeout."""
    try:
        root = psutil.Process(root_pid)
        processes = [*root.children(recursive=True), root]
    except psutil.NoSuchProcess:
        return ProcessCleanupResult((root_pid,), (root_pid,))
    except (psutil.AccessDenied, psutil.ZombieProcess):
        return ProcessCleanupResult((root_pid,), (), (root_pid,))

    failed: set[int] = set()
    terminable: list[psutil.Process] = []
    for process in processes:
        try:
            process.terminate()
            terminable.append(process)
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, psutil.ZombieProcess):
            failed.add(process.pid)

    _gone, alive = psutil.wait_procs(terminable, timeout=max(timeout_seconds, 0.0))
    killable: list[psutil.Process] = []
    for process in alive:
        try:
            process.kill()
            killable.append(process)
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, psutil.ZombieProcess):
            failed.add(process.pid)
    psutil.wait_procs(killable, timeout=max(timeout_seconds, 0.0))

    return _result_for_processes(processes, failed)


def _parent_protection_status(process: psutil.Process, executable: str) -> bool | None:
    """Return whether a live branded serve parent protects a candidate.

    ``None`` means the parent could not be inspected, so the candidate must not
    be stopped speculatively.
    """
    try:
        parent_pid = process.ppid()
        parent = psutil.Process(parent_pid)
    except psutil.NoSuchProcess:
        return False
    except (psutil.AccessDenied, psutil.ZombieProcess):
        return None

    parent_running = _is_running(parent)
    if parent_running is None:
        return None
    if not parent_running:
        return False
    try:
        return (
            _normalized_executable(parent.exe()) == executable
            and _internal_role(parent.cmdline()) == "serve"
        )
    except _PROCESS_ERRORS:
        return None


def cleanup_orphaned_internal_processes(
    executable_path: Path,
    current_pid: int | None = None,
    timeout_seconds: float = 3.0,
) -> ProcessCleanupResult:
    """Stop orphaned internal web and worker processes for one executable only."""
    executable = _normalized_executable(executable_path)
    current_pid = os.getpid() if current_pid is None else current_pid
    targets: list[psutil.Process] = []
    failed: set[int] = set()

    for process in psutil.process_iter():
        if process.pid == current_pid:
            continue
        try:
            same_executable = _normalized_executable(process.exe()) == executable
            role = _internal_role(process.cmdline())
        except _PROCESS_ERRORS:
            continue
        if not same_executable or role not in _INTERNAL_CHILD_ROLES:
            continue

        protection = _parent_protection_status(process, executable)
        if protection is True:
            continue
        if protection is None:
            failed.add(process.pid)
            continue
        targets.append(process)

    matched_pids = tuple(process.pid for process in targets)
    stopped: list[int] = []
    for process in targets:
        result = stop_owned_process_tree(process.pid, timeout_seconds)
        stopped.extend(result.stopped_pids)
        failed.update(result.failed_pids)

    return ProcessCleanupResult(matched_pids, tuple(stopped), tuple(sorted(failed)))


def cleanup_current_packaged_orphans() -> ProcessCleanupResult:
    """Clean stale branded child processes only when running from a packaged app."""
    if not getattr(sys, "frozen", False):
        return ProcessCleanupResult()
    return cleanup_orphaned_internal_processes(Path(sys.executable), os.getpid())
