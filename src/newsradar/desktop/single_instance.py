from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

DESKTOP_MUTEX_NAME = r"Local\NewsCodex.Desktop.SingleInstance"
DUPLICATE_INSTANCE_MESSAGE = "News Codex 已在运行，请从系统托盘打开。"
ERROR_ALREADY_EXISTS = 183


class MutexApi(Protocol):
    last_error: int

    def create_mutex(self, name: str) -> int: ...

    def close_handle(self, handle: int) -> None: ...


class Closeable(Protocol):
    def close(self) -> None: ...


@dataclass(slots=True)
class DesktopInstanceLease:
    handle: int
    api: MutexApi
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self.api.close_handle(self.handle)
        self._closed = True


def acquire_desktop_instance(*, api: MutexApi | None = None) -> DesktopInstanceLease | None:
    mutex_api = api or _load_windows_mutex_api()
    handle = mutex_api.create_mutex(DESKTOP_MUTEX_NAME)
    if mutex_api.last_error == ERROR_ALREADY_EXISTS:
        mutex_api.close_handle(handle)
        return None
    return DesktopInstanceLease(handle, mutex_api)


def run_desktop_single_instance(
    run_desktop: Callable[[], None],
    *,
    acquire_instance: Callable[[], Closeable | None] | None = None,
    notify_duplicate: Callable[[str], None] | None = None,
) -> bool:
    acquire = acquire_instance or acquire_desktop_instance
    notify = notify_duplicate or show_duplicate_message
    lease = acquire()
    if lease is None:
        notify(DUPLICATE_INSTANCE_MESSAGE)
        return False
    try:
        run_desktop()
    finally:
        lease.close()
    return True


def show_duplicate_message(message: str) -> None:
    if os.name != "nt":
        print(message, file=sys.stderr)
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    message_box = user32.MessageBoxW
    message_box.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    message_box.restype = ctypes.c_int
    message_box(None, message, "News Codex", 0x00000040)


def _load_windows_mutex_api() -> MutexApi:
    if os.name != "nt":
        raise OSError("windows_desktop_mutex_requires_windows")
    return _WindowsMutexApi()


class _WindowsMutexApi:
    def __init__(self) -> None:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._create_mutex = kernel32.CreateMutexW
        self._create_mutex.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self._create_mutex.restype = wintypes.HANDLE
        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = [wintypes.HANDLE]
        self._close_handle.restype = wintypes.BOOL
        self._handle_type = wintypes.HANDLE
        self.last_error = 0

    def create_mutex(self, name: str) -> int:
        ctypes.set_last_error(0)
        handle = self._create_mutex(None, False, name)
        self.last_error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(self.last_error)
        return int(handle)

    def close_handle(self, handle: int) -> None:
        if not self._close_handle(self._handle_type(handle)):
            raise ctypes.WinError(ctypes.get_last_error())
