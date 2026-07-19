from __future__ import annotations

from PIL import Image

from newsradar.desktop.icon import create_news_codex_icon
from tools import build_windows_desktop


def test_news_codex_icon_has_expected_sizes() -> None:
    master = create_news_codex_icon(256)
    resized = create_news_codex_icon(64)

    assert master.mode == "RGBA"
    assert master.size == (256, 256)
    assert resized.size == (64, 64)


def test_news_codex_icon_rejects_non_positive_sizes() -> None:
    try:
        create_news_codex_icon(0)
    except ValueError as error:
        assert str(error) == "icon_size_must_be_positive"
    else:
        raise AssertionError("expected a non-positive icon size to fail")


def test_build_icon_uses_shared_factory(monkeypatch, tmp_path) -> None:
    calls: list[int] = []

    def fake_icon(size: int) -> Image.Image:
        calls.append(size)
        return Image.new("RGBA", (size, size), "#0f172a")

    monkeypatch.setattr(build_windows_desktop, "create_news_codex_icon", fake_icon)

    build_windows_desktop.create_icon(tmp_path / "news-codex.ico")

    assert calls == [256]
