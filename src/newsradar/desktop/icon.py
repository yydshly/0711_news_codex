from __future__ import annotations

from PIL import Image, ImageDraw


def create_news_codex_icon(size: int = 256) -> Image.Image:
    if size <= 0:
        raise ValueError("icon_size_must_be_positive")

    image = _draw_master_icon()
    if size == 256:
        return image
    return image.resize((size, size), Image.Resampling.LANCZOS)


def _draw_master_icon() -> Image.Image:
    image = Image.new("RGBA", (256, 256), "#0f172a")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (20, 20, 236, 236), radius=52, fill="#0f172a", outline="#38bdf8", width=10
    )
    draw.ellipse((64, 64, 192, 192), fill="#38bdf8")
    draw.rectangle((104, 98, 122, 158), fill="#0f172a")
    draw.rectangle((134, 98, 152, 158), fill="#0f172a")
    draw.polygon(((122, 110), (134, 128), (122, 146)), fill="#0f172a")
    return image
