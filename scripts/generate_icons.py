"""Generate PWA icons for the TASCAM CD-400U web controller.

Run once to (re)generate PNG icons under static/icons/. The icon design
mirrors the on-device LCD aesthetic: amber-on-black with a stylized CD disc.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "static" / "icons"

# Brand colors (kept in sync with index.html :root tokens)
BG = (10, 10, 10)              # --black
LCD_BG = (12, 26, 10)          # --lcd-bg
LCD_BORDER = (26, 42, 24)
AMBER = (240, 160, 0)          # --amber
AMBER_BRIGHT = (255, 184, 32)  # --amber-bright
TEXT_DIM = (119, 119, 119)


def draw_icon(size: int, *, maskable: bool = False) -> Image.Image:
    """Draw a single icon at the given pixel size."""
    img = Image.new("RGB", (size, size), BG)
    draw = ImageDraw.Draw(img)

    # Maskable icons need ~10% safe area on each side; shrink the artwork.
    inset = int(size * 0.10) if maskable else int(size * 0.06)
    inner = size - 2 * inset

    # Faceplate (rounded LCD-style background)
    radius = max(2, inner // 12)
    draw.rounded_rectangle(
        (inset, inset, inset + inner, inset + inner),
        radius=radius,
        fill=LCD_BG,
        outline=LCD_BORDER,
        width=max(1, inner // 64),
    )

    # CD disc
    cx = cy = size // 2
    disc_r = inner // 2 - inner // 10
    draw.ellipse(
        (cx - disc_r, cy - disc_r, cx + disc_r, cy + disc_r),
        outline=AMBER,
        width=max(2, inner // 32),
    )
    # Inner ring
    inner_r = disc_r // 2
    draw.ellipse(
        (cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r),
        outline=AMBER_BRIGHT,
        width=max(1, inner // 48),
    )
    # Spindle hole
    hole_r = max(2, inner // 24)
    draw.ellipse(
        (cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r),
        fill=BG,
    )

    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
        ("apple-touch-icon.png", 180, False),
    ]
    for name, size, maskable in targets:
        path = OUT_DIR / name
        draw_icon(size, maskable=maskable).save(path, "PNG", optimize=True)
        print(f"wrote {path} ({size}x{size}{' maskable' if maskable else ''})")


if __name__ == "__main__":
    main()
