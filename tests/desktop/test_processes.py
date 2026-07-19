from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import psutil
import pytest

from newsradar.desktop import processes
from newsradar.desktop.launcher import INTERNAL_COMMAND_MARKER as MARKER


@dataclass
class FakeProcess:
    pid: int
    parent_pid: int
    executable: Path
    command: list[str]
    child_processes: list[FakeProcess] = field(default_factory=list)
    created_at: float = 1.0
    survives_terminate: bool = False
    terminate_error: Exception | None = None
    parent_error: Exception | None = None
    create_time_error: Exception | None = None
    executable_error: Exception | None = None
    resolved_parent: FakeProcess | None = None
    resolve_parent_from_backend: bool = True
    running: bool = True
    terminate_calls: int = 0
    kill_calls: int = 0
    children_calls: int = 0

    def ppid(self) -> int:
        if self.parent_error is not None:
            raise self.parent_error
        return self.parent_pid

    def create_time(self) -> float:
        if self.create_time_error is not None:
            raise self.create_time_error
        return self.created_at

    def parent(self) -> FakeProcess | None:
        if self.parent_error is not None:
            raise self.parent_error
        return self.resolved_parent

    def exe(self) -> str:
        if self.executable_error is not None:
            raise self.executable_error
        return str(self.executable)

    def cmdline(self) -> list[str]:
        return self.command

    def children(self, recursive: bool = False) -> list[FakeProcess]:
        self.children_calls += 1
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


def install_fake_backend(
    monkeypatch,
    processes_by_pid: list[FakeProcess],
    *,
    iter_processes: list[FakeProcess] | None = None,
) -> None:
    by_pid = {process.pid: process for process in processes_by_pid}
    for process in processes_by_pid:
        if process.resolve_parent_from_backend and process.resolved_parent is None:
            process.resolved_parent = by_pid.get(process.parent_pid)

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

    monkeypatch.setattr(
        processes.psutil,
        "process_iter",
        lambda: iter(processes_by_pid if iter_processes is None else iter_processes),
    )
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


def test_cleanup_keeps_an_uninspectable_parent_candidate_matched_and_untouched(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "NewsCodex.exe"
    candidate = FakeProcess(
        201,
        999,
        executable,
        [str(executable), MARKER, "worker"],
        parent_error=psutil.AccessDenied(999),
    )
    install_fake_backend(monkeypatch, [candidate])

    result = processes.cleanup_orphaned_internal_processes(executable, current_pid=300)

    assert result.matched_pids == (201,)
    assert result.failed_pids == (201,)
    assert candidate.terminate_calls == 0


def test_cleanup_protects_internal_child_with_live_foreign_parent(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "NewsCodex.exe"
    python = FakeProcess(205, 1, tmp_path / "python.exe", ["python", "manual.py"])
    child = FakeProcess(201, python.pid, executable, [str(executable), MARKER, "worker"])
    install_fake_backend(monkeypatch, [child, python], iter_processes=[child])

    result = processes.cleanup_orphaned_internal_processes(executable, current_pid=300)

    assert result == processes.ProcessCleanupResult()
    assert child.terminate_calls == 0


def test_cleanup_protects_internal_child_with_live_nonserve_branded_parent(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "NewsCodex.exe"
    parent = FakeProcess(205, 1, executable, [str(executable), MARKER, "worker"])
    child = FakeProcess(201, parent.pid, executable, [str(executable), MARKER, "web"])
    install_fake_backend(monkeypatch, [child, parent], iter_processes=[child])

    result = processes.cleanup_orphaned_internal_processes(executable, current_pid=300)

    assert result == processes.ProcessCleanupResult()
    assert child.terminate_calls == 0


def test_cleanup_stops_true_orphan_when_parent_pid_has_been_reused(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "NewsCodex.exe"
    replacement_parent = FakeProcess(
        205,
        1,
        tmp_path / "python.exe",
        ["python", "unrelated.py"],
        created_at=9.0,
    )
    orphan = FakeProcess(
        201,
        replacement_parent.pid,
        executable,
        [str(executable), MARKER, "worker"],
        resolve_parent_from_backend=False,
    )
    install_fake_backend(
        monkeypatch,
        [orphan, replacement_parent],
        iter_processes=[orphan],
    )

    result = processes.cleanup_orphaned_internal_processes(executable, current_pid=300)

    assert result.stopped_pids == (orphan.pid,)
    assert orphan.terminate_calls == 1
    assert replacement_parent.terminate_calls == 0


def test_cleanup_leaves_foreign_descendants_of_an_orphaned_branded_process_running(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "NewsCodex.exe"
    orphan_web = FakeProcess(201, 999, executable, [str(executable), MARKER, "web"])
    branded_worker = FakeProcess(202, 201, executable, [str(executable), MARKER, "worker"])
    manual_python = FakeProcess(203, 201, tmp_path / "python.exe", ["python", "-m", "newsradar"])
    postgres = FakeProcess(204, 201, tmp_path / "postgres.exe", ["postgres", "-D", "data"])
    orphan_web.child_processes = [branded_worker, manual_python, postgres]
    install_fake_backend(
        monkeypatch,
        [orphan_web, branded_worker, manual_python, postgres],
        iter_processes=[orphan_web, manual_python, postgres],
    )

    result = processes.cleanup_orphaned_internal_processes(executable, current_pid=300)

    assert result.stopped_pids == (202, 201)
    assert branded_worker.terminate_calls == 1
    assert manual_python.terminate_calls == 0
    assert postgres.terminate_calls == 0


def test_cleanup_fails_closed_when_a_selected_pid_has_been_reused(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "NewsCodex.exe"
    selected = FakeProcess(
        201, 999, executable, [str(executable), MARKER, "web"], created_at=1.0
    )
    reused = FakeProcess(
        201,
        999,
        tmp_path / "python.exe",
        ["python", "-m", "newsradar"],
        created_at=2.0,
    )
    install_fake_backend(monkeypatch, [selected])

    original_process = processes.psutil.Process

    def process_after_reuse(pid: int) -> FakeProcess:
        if pid == selected.pid:
            return reused
        return original_process(pid)

    monkeypatch.setattr(processes.psutil, "Process", process_after_reuse)

    result = processes.cleanup_orphaned_internal_processes(executable, current_pid=300)

    assert result.matched_pids == (201,)
    assert result.failed_pids == (201,)
    assert reused.terminate_calls == 0


def test_cleanup_reports_an_inaccessible_snapshotted_descendant_as_failed(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "NewsCodex.exe"
    orphan_web = FakeProcess(201, 999, executable, [str(executable), MARKER, "web"])
    inaccessible_worker = FakeProcess(
        202,
        201,
        executable,
        [str(executable), MARKER, "worker"],
        executable_error=psutil.AccessDenied(202),
    )
    orphan_web.child_processes = [inaccessible_worker]
    install_fake_backend(
        monkeypatch,
        [orphan_web, inaccessible_worker],
        iter_processes=[orphan_web],
    )

    result = processes.cleanup_orphaned_internal_processes(executable, current_pid=300)

    assert result.stopped_pids == (201,)
    assert result.failed_pids == (202,)
    assert inaccessible_worker.terminate_calls == 0


def test_cleanup_treats_a_selected_process_that_vanishes_as_stopped(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "NewsCodex.exe"
    selected = FakeProcess(201, 999, executable, [str(executable), MARKER, "web"])
    install_fake_backend(monkeypatch, [selected])

    original_process = processes.psutil.Process

    def process_after_exit(pid: int) -> FakeProcess:
        if pid == selected.pid:
            raise psutil.NoSuchProcess(pid)
        return original_process(pid)

    monkeypatch.setattr(processes.psutil, "Process", process_after_exit)

    result = processes.cleanup_orphaned_internal_processes(executable, current_pid=300)

    assert result.stopped_pids == (201,)
    assert result.failed_pids == ()


@pytest.mark.parametrize("replacement_name", ["python.exe", "postgres.exe", "other.exe"])
def test_stop_owned_process_tree_never_touches_reused_pid_or_its_descendants(
    monkeypatch, tmp_path: Path, replacement_name: str
) -> None:
    replacement_child = FakeProcess(
        11,
        10,
        tmp_path / replacement_name,
        [replacement_name, "child"],
        created_at=8.0,
    )
    replacement = FakeProcess(
        10,
        1,
        tmp_path / replacement_name,
        [replacement_name, "replacement"],
        child_processes=[replacement_child],
        created_at=8.0,
    )
    install_fake_backend(monkeypatch, [replacement, replacement_child])
    owned_identity = processes.ProcessIdentity(replacement.pid, 1.0)

    result = processes.stop_owned_process_tree(owned_identity, timeout_seconds=0.1)

    assert result == processes.ProcessCleanupResult((10,), (10,), ())
    assert replacement.children_calls == 0
    assert replacement.terminate_calls == 0
    assert replacement.kill_calls == 0
    assert replacement_child.terminate_calls == 0
    assert replacement_child.kill_calls == 0


def test_stop_owned_process_tree_fails_closed_when_identity_is_inaccessible(
    monkeypatch, tmp_path: Path
) -> None:
    root = FakeProcess(
        10,
        1,
        tmp_path / "NewsCodex.exe",
        ["NewsCodex.exe", MARKER, "serve"],
        create_time_error=psutil.AccessDenied(10),
    )
    install_fake_backend(monkeypatch, [root])
    owned_identity = processes.ProcessIdentity(root.pid, 1.0)

    result = processes.stop_owned_process_tree(owned_identity, timeout_seconds=0.1)

    assert result == processes.ProcessCleanupResult((10,), (), (10,))
    assert root.children_calls == 0
    assert root.terminate_calls == 0


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

    owned_identity = processes.ProcessIdentity(root.pid, root.created_at)

    result = processes.stop_owned_process_tree(owned_identity, timeout_seconds=0.1)

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

    owned_identity = processes.ProcessIdentity(root.pid, root.created_at)

    result = processes.stop_owned_process_tree(owned_identity, timeout_seconds=0.1)

    assert result.stopped_pids == (10,)
    assert result.failed_pids == ()


def test_cleanup_current_packaged_orphans_is_a_noop_when_not_frozen(monkeypatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert processes.cleanup_current_packaged_orphans() == processes.ProcessCleanupResult()
