from __future__ import annotations

import sys
from pathlib import Path

import pytest


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
    from newsradar.desktop import launcher, single_instance

    started: list[int] = []
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "argv", ["NewsCodex.exe"])
    monkeypatch.setattr(desktop_app, "run_desktop", lambda *, port: started.append(port))
    monkeypatch.setattr(
        single_instance,
        "acquire_desktop_instance",
        lambda: pytest.fail("development desktop must not acquire the packaged mutex"),
    )

    launcher.main()

    assert started == [8767]


def test_packaged_windows_duplicate_skips_desktop_and_shows_message(
    monkeypatch, tmp_path: Path
) -> None:
    from newsradar.desktop import app as desktop_app
    from newsradar.desktop import launcher, single_instance

    started: list[int] = []
    messages: list[str] = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["NewsCodex.exe"])
    monkeypatch.setattr(launcher, "is_windows", lambda: True)
    monkeypatch.setattr(launcher, "find_project_root", lambda _anchor: tmp_path)
    monkeypatch.setattr(launcher.os, "chdir", lambda _path: None)
    monkeypatch.setattr(launcher, "ensure_standard_streams", lambda _root: None)
    monkeypatch.setattr(desktop_app, "run_desktop", lambda *, port: started.append(port))
    monkeypatch.setattr(single_instance, "acquire_desktop_instance", lambda: None)
    monkeypatch.setattr(single_instance, "show_duplicate_message", messages.append)

    launcher.main()

    assert started == []
    assert messages == ["News Codex 已在运行，请从系统托盘打开。"]


def test_packaged_internal_service_bypasses_desktop_mutex(monkeypatch, tmp_path: Path) -> None:
    from newsradar import cli
    from newsradar.desktop import launcher, single_instance

    called: list[str] = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["NewsCodex.exe", launcher.INTERNAL_COMMAND_MARKER, "worker", "--forever"],
    )
    monkeypatch.setattr(launcher, "is_windows", lambda: True)
    monkeypatch.setattr(launcher, "find_project_root", lambda _anchor: tmp_path)
    monkeypatch.setattr(launcher.os, "chdir", lambda _path: None)
    monkeypatch.setattr(launcher, "ensure_standard_streams", lambda _root: None)
    monkeypatch.setattr(cli, "app", lambda: called.append("cli"))
    monkeypatch.setattr(
        single_instance,
        "acquire_desktop_instance",
        lambda: pytest.fail("internal service must not acquire the desktop mutex"),
    )

    launcher.main()

    assert called == ["cli"]


def test_windowed_streams_support_uvicorn_logging(monkeypatch, tmp_path: Path) -> None:
    from uvicorn.logging import DefaultFormatter

    from newsradar.desktop import launcher

    project_root = tmp_path / "project"
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    launcher.ensure_standard_streams(project_root)
    DefaultFormatter("%(message)s")

    assert sys.stdout is not None and sys.stdout.isatty() is False
    assert sys.stderr is not None and sys.stderr.isatty() is False
    assert (project_root / ".local" / "logs" / "news-codex-desktop.log").exists()
