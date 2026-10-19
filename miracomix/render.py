"""Pillow post-processing: dialogue strip under each panel, and the 2x2 comic page.

Dialogue is drawn here rather than by FLUX because diffusion models misspell text.
"""
import io
import textwrap

from PIL import Image, ImageDraw, ImageFont

PANEL = 768           # panel width/height on the page
FONT = 34
LINE_H = 44
WRAP = 38             # characters per dialogue line at this font size
GUTTER = 24
INK = (20, 20, 20)
PAPER = (255, 253, 245)


def _font(size=FONT):
    return ImageFont.load_default(size=size)


def load_image(data):
    """Decode and normalise untrusted image bytes; raises on anything that isn't an image."""
    img = Image.open(io.BytesIO(data))
    img.load()
    return img.convert("RGB")


def to_jpeg(data, max_side=1024):
    img = load_image(data)
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88)
    return out.getvalue()


def panel_with_dialogue(image_bytes, dialogue):
    art = load_image(image_bytes).resize((PANEL, PANEL))
    lines = []
    for line in dialogue:
        lines += textwrap.wrap(f"{line['speaker']}: {line['text']}", WRAP) or [""]
    strip = LINE_H * len(lines) + (24 if lines else 0)

    panel = Image.new("RGB", (PANEL, PANEL + strip), PAPER)
    panel.paste(art, (0, 0))
    draw = ImageDraw.Draw(panel)
    for i, text in enumerate(lines):
        draw.text((16, PANEL + 12 + i * LINE_H), text, font=_font(), fill=INK)
    draw.rectangle([0, 0, panel.width - 1, panel.height - 1], outline=INK, width=4)
    return panel


def compose_page(panels, title):
    """Lay four panels out 2x2 under a title; rows take the height of their tallest panel."""
    header = 90
    row_h = [max(p.height for p in panels[0:2]), max(p.height for p in panels[2:4])]
    width = 2 * PANEL + 3 * GUTTER
    height = header + sum(row_h) + 3 * GUTTER
    page = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(page)
    draw.text((width // 2, header // 2 + GUTTER // 2), title, font=_font(44), fill=INK, anchor="mm")
    y = header
    for row in range(2):
        for col in range(2):
            page.paste(panels[row * 2 + col], (GUTTER + col * (PANEL + GUTTER), y + GUTTER))
        y += row_h[row] + GUTTER
    return page
