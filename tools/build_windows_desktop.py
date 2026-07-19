"""Build the local branded Windows desktop launcher without bundling user data."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from newsradar.desktop.icon import create_news_codex_icon

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = PROJECT_ROOT / "build" / "windows-desktop"
ICON_PATH = BUILD_ROOT / "news-codex.ico"


def create_icon(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    create_news_codex_icon(256).save(
        destination,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


def main() -> None:
    create_icon(ICON_PATH)
    static_path = PROJECT_ROOT / "src" / "newsradar" / "web" / "static"
    templates_path = PROJECT_ROOT / "src" / "newsradar" / "web" / "templates"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "NewsCodex",
        "--icon",
        str(ICON_PATH),
        "--paths",
        str(PROJECT_ROOT / "src"),
        "--add-data",
        f"{static_path};newsradar/web/static",
        "--add-data",
        f"{templates_path};newsradar/web/templates",
        "--collect-all",
        "webview",
        "--collect-all",
        "pystray",
        "--distpath",
        str(PROJECT_ROOT / "dist"),
        "--workpath",
        str(BUILD_ROOT / "work"),
        "--specpath",
        str(BUILD_ROOT / "spec"),
        "src/newsradar/desktop/launcher.py",
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)  # noqa: S603
    print("Built: dist/NewsCodex/NewsCodex.exe")


if __name__ == "__main__":
    main()
