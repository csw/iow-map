"""Regenerate the favicon assets from the ring+dot brand mark.

Safari doesn't render `<link rel="icon">` when the href is a data: URI (a
long-standing WebKit limitation) — Chrome/Firefox are fine with it, which is
why the icon only ever showed up there. This writes real static files
instead:

  assets/favicon.svg          — vector, used by browsers that support it
  assets/favicon-32.png       — raster fallback (Safari's tab icon)
  assets/apple-touch-icon.png — iOS/iPadOS home-screen + bookmark icon

Usage: uv run python tools/gen_favicon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

BG = "#12191f"
RING = "#2dd4a8"
DOT = "#ffd700"

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<rect width="100" height="100" rx="20" fill="{bg}"/>
<circle cx="50" cy="50" r="34" fill="none" stroke="{ring}" stroke-width="7"/>
<circle cx="50" cy="50" r="11" fill="{dot}"/>
</svg>
""".format(bg=BG, ring=RING, dot=DOT)


def _render(size, rounded, supersample=4):
    """Draw the mark at `size`px using PIL (no SVG rasterizer dependency),
    supersampled for anti-aliasing. `rounded` controls whether the
    background square gets the same rx=20/100 corner rounding as the SVG —
    off for apple-touch-icon, since iOS applies its own mask."""
    s = size * supersample
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if rounded:
        draw.rounded_rectangle([0, 0, s - 1, s - 1], radius=round(s * 0.2), fill=BG)
    else:
        draw.rectangle([0, 0, s - 1, s - 1], fill=BG)

    center = s / 2
    ring_r = s * 0.34
    ring_w = s * 0.07
    draw.ellipse(
        [center - ring_r, center - ring_r, center + ring_r, center + ring_r],
        outline=RING, width=round(ring_w),
    )
    dot_r = s * 0.11
    draw.ellipse(
        [center - dot_r, center - dot_r, center + dot_r, center + dot_r],
        fill=DOT,
    )
    return img.resize((size, size), Image.LANCZOS)


def main():
    ASSETS.mkdir(exist_ok=True)

    (ASSETS / "favicon.svg").write_text(SVG)

    _render(32, rounded=True).save(ASSETS / "favicon-32.png")
    _render(180, rounded=False).convert("RGB").save(ASSETS / "apple-touch-icon.png")

    print(f"Wrote {ASSETS/'favicon.svg'}, favicon-32.png, apple-touch-icon.png")


if __name__ == "__main__":
    main()
