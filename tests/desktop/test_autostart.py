from __future__ import annotations

from dataclasses import dataclass, field

from newsradar.desktop.autostart import RUN_VALUE_NAME, WindowsAutostart


@dataclass
class FakeRegistry:
    values: dict[str, str] = field(default_factory=dict)

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, command: str) -> None:
        self.values[name] = command

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def test_autostart_writes_current_user_run_value_without_secrets() -> None:
    registry = FakeRegistry()
    command = '"C:/Python/python.exe" -c "from newsradar.cli import app; app()" desktop run'

    WindowsAutostart(registry).enable(command)

    assert registry.values[RUN_VALUE_NAME] == command
    assert "DATABASE_URL" not in registry.values[RUN_VALUE_NAME]


def test_autostart_reports_and_removes_enabled_value() -> None:
    registry = FakeRegistry()
    autostart = WindowsAutostart(registry)
    autostart.enable("safe-command")

    assert autostart.status().enabled is True
    autostart.disable()
    assert autostart.status().enabled is False
