"""Build the local branded Windows desktop launcher without bundling user data."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = PROJECT_ROOT / "build" / "windows-desktop"
ICON_PATH = BUILD_ROOT / "news-codex.ico"


def create_icon(destination: Path) -> None:
    from PIL import Image, ImageDraw

    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (256, 256), "#0f172a")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (20, 20, 236, 236), radius=52, fill="#0f172a", outline="#38bdf8", width=10
    )
    draw.ellipse((64, 64, 192, 192), fill="#38bdf8")
    draw.rectangle((104, 98, 122, 158), fill="#0f172a")
    draw.rectangle((134, 98, 152, 158), fill="#0f172a")
    draw.polygon(((122, 110), (134, 128), (122, 146)), fill="#0f172a")
    image.save(
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
