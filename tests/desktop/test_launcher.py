from __future__ import annotations

import sys
from pathlib import Path


def test_frozen_runtime_command_reuses_branded_executable(monkeypatch, tmp_path: Path) -> None:
    from newsradar.desktop import launcher

    executable = tmp_path / "NewsCodex.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    assert launcher.runtime_command("web", "--port", "8767") == (
        str(executable),
        launcher.INTERNAL_COMMAND_MARKER,
        "web",
        "--port",
        "8767",
    )


def test_development_runtime_command_keeps_python_cli_contract(monkeypatch) -> None:
    from newsradar.desktop import launcher

    monkeypatch.delattr(sys, "frozen", raising=False)

    command = launcher.runtime_command("worker", "--forever")

    assert command[:3] == (sys.executable, "-c", launcher.CLI_INVOKE)
    assert command[-2:] == ("worker", "--forever")


def test_project_root_prefers_nearest_catalog_around_packaged_application(tmp_path: Path) -> None:
    from newsradar.desktop import launcher

    project_root = tmp_path / "project"
    (project_root / "sources").mkdir(parents=True)
    (project_root / "providers").mkdir()
    executable = project_root / "dist" / "NewsCodex" / "NewsCodex.exe"
    executable.parent.mkdir(parents=True)

    assert launcher.find_project_root(executable) == project_root


def test_main_starts_desktop_window_when_not_handling_internal_command(monkeypatch) -> None:
    from newsradar.desktop import app as desktop_app
    from newsradar.desktop import launcher

    started: list[int] = []
    monkeypatch.setattr(sys, "argv", ["NewsCodex.exe"])
    monkeypatch.setattr(desktop_app, "run_desktop", lambda *, port: started.append(port))

    launcher.main()

    assert started == [8767]
