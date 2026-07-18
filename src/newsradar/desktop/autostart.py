from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Protocol

RUN_VALUE_NAME = "NewsCodexDesktop"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class RunRegistry(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, command: str) -> None: ...

    def delete(self, name: str) -> None: ...


class WindowsRunRegistry:
    def get(self, name: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                return str(winreg.QueryValueEx(key, name)[0])
        except FileNotFoundError:
            return None

    def set(self, name: str, command: str) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)

    def delete(self, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return


@dataclass(frozen=True)
class AutostartStatus:
    enabled: bool
    command: str | None


class WindowsAutostart:
    def __init__(self, registry: RunRegistry | None = None) -> None:
        self._registry = registry or WindowsRunRegistry()

    def enable(self, command: str) -> None:
        if "DATABASE_URL" in command or "API_KEY" in command:
            raise ValueError("desktop_autostart_command_must_not_contain_secrets")
        self._registry.set(RUN_VALUE_NAME, command)

    def disable(self) -> None:
        self._registry.delete(RUN_VALUE_NAME)

    def status(self) -> AutostartStatus:
        command = self._registry.get(RUN_VALUE_NAME)
        return AutostartStatus(enabled=command is not None, command=command)


def windows_supported() -> bool:
    return sys.platform == "win32"
