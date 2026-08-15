"""Generates the product icon assets.

Icon assets are checked into the repository; this script only re-generates
them. It is a build-time maintenance tool and needs Pillow (not a runtime or
release-build dependency):

    python -m pip install pillow
    python packaging/make_icon.py

Outputs:
  packaging/assets/atm.ico                                  - Windows EXE icon
  android-task-manager-website/website/app/favicon.ico      - website favicon
  android-task-manager-website/website/app/icon.png         - 512 px app icon
  android-task-manager-website/website/public/og-image.png  - 1200 x 630 Open Graph image

Design: a dark terminal rounded-square with a blue "CPU gauge" arc, a needle
and three activity bars - a small, readable product mark at favicon sizes.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PACKAGING_ASSETS = ROOT / "packaging" / "assets"
WEBSITE = ROOT / "android-task-manager-website" / "website"

BG = (10, 12, 16, 255)
BORDER = (42, 50, 66, 255)
ACCENT = (76, 130, 247, 255)
ACCENT_MID = (96, 147, 255, 255)
ACCENT_STRONG = (122, 164, 255, 255)
WHITE = (233, 236, 242, 255)


def draw_icon(size: int) -> Image.Image:
    """Renders the app mark at ``size`` pixels (assumed square)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size
    m = s * 0.06

    d.rounded_rectangle(
        [m, m, s - m, s - m],
        radius=s * 0.2,
        fill=BG,
        outline=BORDER,
        width=max(1, int(s * 0.02)),
    )

    cx, cy = s * 0.5, s * 0.43
    rad = s * 0.27
    arc_width = max(1, int(s * 0.055))
    d.arc(
        [cx - rad, cy - rad, cx + rad, cy + rad],
        135,
        405,
        fill=ACCENT,
        width=arc_width,
    )

    end_angle = math.radians(405)
    nx = cx + math.cos(end_angle) * rad * 0.55
    ny = cy + math.sin(end_angle) * rad * 0.55
    d.line(
        [cx, cy, nx, ny],
        fill=ACCENT_STRONG,
        width=max(1, int(s * 0.045)),
    )
    hub = max(1, int(s * 0.03))
    d.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=WHITE)

    bar_w = s * 0.075
    gap = s * 0.045
    heights = [s * 0.15, s * 0.25, s * 0.35]
    colors = [ACCENT, ACCENT_MID, ACCENT_STRONG]
    total = 3 * bar_w + 2 * gap
    x0 = cx - total / 2
    base = s * 0.86
    for i, (h, color) in enumerate(zip(heights, colors)):
        x = x0 + i * (bar_w + gap)
        d.rounded_rectangle(
            [x, base - h, x + bar_w, base],
            radius=bar_w / 2,
            fill=color,
        )
    return img


def write_ico(master: Image.Image, path: Path) -> None:
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [master.resize((s, s), Image.LANCZOS) for s in sizes]
    frames[0].save(path, format="ICO", sizes=[(s, s) for s in sizes])


def _draw_text(d: ImageDraw.ImageDraw, cx: float, y: float, text: str,
               font: ImageFont.FreeTypeFont, fill: tuple[int, int, int, int]) -> None:
    w = d.textlength(text, font=font)
    d.text((cx - w / 2, y), text, font=font, fill=fill)


def write_og(main_font: str, sub_font: str) -> None:
    W, H = 1200, 630
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    d = ImageDraw.Draw(img)

    for y in range(H):
        t = y / H
        r = int(10 + (8 - 10) * t)
        g = int(12 + (10 - 12) * t)
        b = int(16 + (12 - 16) * t)
        d.line([(0, y), (W, y)], fill=(r, g, b, 255))

    for x in range(14, W, 28):
        for y in range(14, H, 28):
            d.point((x, y), fill=(255, 255, 255, 16))

    icon = draw_icon(200)
    img.alpha_composite(icon, ((W - 200) // 2, 74))

    font_bold = ImageFont.truetype(main_font, 68)
    _draw_text(d, W / 2, 300, "Android Task Manager", font_bold, WHITE)
    font_sub = ImageFont.truetype(sub_font, 34)
    _draw_text(d, W / 2, 396, "Android system monitor for Windows", font_sub, (147, 155, 169, 255))
    font_small = ImageFont.truetype(sub_font, 24)
    _draw_text(
        d,
        W / 2,
        470,
        "CPU \u00b7 Memory \u00b7 Processes \u00b7 Network \u00b7 Battery \u00b7 Process Inspector",
        font_small,
        (92, 100, 114, 255),
    )
    _draw_text(
        d,
        W / 2,
        536,
        "Download for Windows \u2014 no Python required",
        font_small,
        ACCENT_STRONG,
    )
    img.save(WEBSITE / "public" / "og-image.png", format="PNG")
    print(f"Wrote {WEBSITE / 'public' / 'og-image.png'}")


def main() -> None:
    win_fonts = "C:/Windows/Fonts"
    main_font = f"{win_fonts}/segoeuib.ttf"
    sub_font = f"{win_fonts}/segoeui.ttf"

    master = draw_icon(256)

    PACKAGING_ASSETS.mkdir(parents=True, exist_ok=True)
    ico = PACKAGING_ASSETS / "atm.ico"
    write_ico(master, ico)
    print(f"Wrote {ico}")

    favicon = WEBSITE / "app" / "favicon.ico"
    write_ico(master, favicon)
    print(f"Wrote {favicon}")

    icon_png = WEBSITE / "app" / "icon.png"
    draw_icon(512).save(icon_png, format="PNG")
    print(f"Wrote {icon_png}")

    (WEBSITE / "public").mkdir(parents=True, exist_ok=True)
    write_og(main_font, sub_font)


if __name__ == "__main__":
    main()