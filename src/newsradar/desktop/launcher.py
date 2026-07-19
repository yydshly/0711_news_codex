from __future__ import annotations

import os
import sys
from pathlib import Path

CLI_INVOKE = "from newsradar.cli import app; app()"
INTERNAL_COMMAND_MARKER = "--news-codex-internal"


def is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False))


def runtime_command(*arguments: str) -> tuple[str, ...]:
    """Build a command that preserves the branded executable when packaged."""
    if is_packaged():
        return (sys.executable, INTERNAL_COMMAND_MARKER, *arguments)
    return (sys.executable, "-c", CLI_INVOKE, *arguments)


def find_project_root(anchor: Path) -> Path:
    """Locate the checked-out project that supplies local catalogs and configuration."""
    for candidate in (anchor.parent, *anchor.parents):
        if (candidate / "sources").is_dir() and (candidate / "providers").is_dir():
            return candidate
    return Path.cwd()


def ensure_standard_streams(project_root: Path) -> None:
    """Provide file-backed streams when a windowed executable has no console."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = project_root / ".local" / "logs" / "news-codex-desktop.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = log_path.open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main() -> None:
    """Entrypoint used by the branded Windows executable."""
    if is_packaged():
        project_root = find_project_root(Path(sys.executable))
        os.chdir(project_root)
        ensure_standard_streams(project_root)

    arguments = sys.argv[1:]
    if arguments and arguments[0] == INTERNAL_COMMAND_MARKER:
        sys.argv = [sys.argv[0], *arguments[1:]]
        from newsradar.cli import app

        app()
        return

    from newsradar.desktop.app import run_desktop

    run_desktop(port=8767)


if __name__ == "__main__":
    main()
