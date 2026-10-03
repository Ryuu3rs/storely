"""Draws the setup wizard's side panel and corner logo from assets/icon.png (100% and 200% scale).
Run: .venv\\Scripts\\python.exe tools\\make_installer_images.py   (needs Pillow)"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "installer"


def panel(scale: int) -> Image.Image:
    w, h = 164 * scale, 314 * scale
    img = Image.new("RGB", (w, h))
    top, bottom = (31, 95, 214), (11, 30, 72)
    for y in range(h):
        t = y / (h - 1)
        img.paste(tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)), (0, y, w, y + 1))
    icon = Image.open(ROOT / "assets" / "icon.png").convert("RGBA").resize((112 * scale, 112 * scale), Image.LANCZOS)
    img.paste(icon, ((w - icon.width) // 2, 56 * scale), icon)
    return img


def corner(scale: int) -> Image.Image:
    size = 55 * scale
    img = Image.new("RGB", (size, size), (255, 255, 255))
    icon = Image.open(ROOT / "assets" / "icon.png").convert("RGBA").resize((size - 6 * scale,) * 2, Image.LANCZOS)
    img.paste(icon, (3 * scale, 3 * scale), icon)
    return img


def main():
    OUT.mkdir(exist_ok=True)
    for scale in (1, 2):
        panel(scale).save(OUT / f"wizard-large-{scale * 100}.bmp")
        corner(scale).save(OUT / f"wizard-small-{scale * 100}.bmp")
    print("wrote wizard images to", OUT)


if __name__ == "__main__":
    main()
