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


def main() -> None:
    """Entrypoint used by the branded Windows executable."""
    arguments = sys.argv[1:]
    if arguments and arguments[0] == INTERNAL_COMMAND_MARKER:
        sys.argv = [sys.argv[0], *arguments[1:]]
        from newsradar.cli import app

        app()
        return

    if is_packaged():
        os.chdir(find_project_root(Path(sys.executable)))
    from newsradar.desktop.app import run_desktop

    run_desktop(port=8767)


if __name__ == "__main__":
    main()
