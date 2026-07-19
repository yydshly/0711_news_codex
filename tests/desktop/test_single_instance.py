from __future__ import annotations

from dataclasses import dataclass

import pytest

from newsradar.desktop.single_instance import (
    DESKTOP_MUTEX_NAME,
    DUPLICATE_INSTANCE_MESSAGE,
    ERROR_ALREADY_EXISTS,
    acquire_desktop_instance,
    run_desktop_single_instance,
)


class FakeMutexApi:
    def __init__(self, *, last_error: int = 0) -> None:
        self.last_error = last_error
        self.created_names: list[str] = []
        self.closed_handles: list[int] = []

    def create_mutex(self, name: str) -> int:
        self.created_names.append(name)
        return 101

    def close_handle(self, handle: int) -> None:
        self.closed_handles.append(handle)


@dataclass
class FakeLease:
    close_calls: int = 0

    def close(self) -> None:
        self.close_calls += 1


def test_first_mutex_owner_uses_stable_local_identity_and_releases_handle() -> None:
    api = FakeMutexApi()

    lease = acquire_desktop_instance(api=api)

    assert DESKTOP_MUTEX_NAME == r"Local\NewsCodex.Desktop.SingleInstance"
    assert api.created_names == [DESKTOP_MUTEX_NAME]
    assert lease is not None
    lease.close()
    lease.close()
    assert api.closed_handles == [101]


def test_existing_mutex_closes_duplicate_handle_and_rejects_instance() -> None:
    api = FakeMutexApi(last_error=ERROR_ALREADY_EXISTS)

    lease = acquire_desktop_instance(api=api)

    assert lease is None
    assert api.closed_handles == [101]


def test_first_desktop_instance_runs_and_releases_after_return() -> None:
    lease = FakeLease()
    calls: list[str] = []

    started = run_desktop_single_instance(
        lambda: calls.append("run"),
        acquire_instance=lambda: lease,
        notify_duplicate=lambda message: calls.append(message),
    )

    assert started is True
    assert calls == ["run"]
    assert lease.close_calls == 1


def test_duplicate_desktop_instance_shows_chinese_message_without_running() -> None:
    calls: list[str] = []

    started = run_desktop_single_instance(
        lambda: calls.append("run"),
        acquire_instance=lambda: None,
        notify_duplicate=lambda message: calls.append(message),
    )

    assert started is False
    assert calls == ["News Codex 已在运行，请从系统托盘打开。"]
    assert DUPLICATE_INSTANCE_MESSAGE == calls[0]


def test_desktop_exception_still_releases_mutex_handle() -> None:
    lease = FakeLease()

    def fail() -> None:
        raise RuntimeError("desktop_failed")

    with pytest.raises(RuntimeError, match="desktop_failed"):
        run_desktop_single_instance(
            fail,
            acquire_instance=lambda: lease,
            notify_duplicate=lambda _message: None,
        )

    assert lease.close_calls == 1
