"""Draws the Unjammed icon and writes assets/icon.png (512px) and assets/icon.ico (16-256px).
Run: .venv\\Scripts\\python.exe tools\\make_icon.py   (needs Pillow for the multi-size .ico)"""

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def draw(size: int = 512) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 512

    # tile: rounded square, Store-blue gradient
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#4fc3ff"))
    g.setColorAt(1, QColor("#1f5fd6"))
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(16 * s, 16 * s, 480 * s, 480 * s), 108 * s, 108 * s)
    p.fillPath(tile, QBrush(g))

    # bag handle
    pen = QPen(QColor("#ffffff"), 26 * s, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(186 * s, 104 * s, 140 * s, 150 * s), 0, 180 * 16)
    # bag body
    body = QPainterPath()
    body.addRoundedRect(QRectF(118 * s, 178 * s, 276 * s, 238 * s), 40 * s, 40 * s)
    p.setPen(Qt.NoPen)
    p.fillPath(body, QColor("#ffffff"))
    # tick - "updated, verified"
    pen = QPen(QColor("#1f5fd6"), 34 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    tick = QPainterPath(QPointF(190 * s, 300 * s))
    tick.lineTo(QPointF(240 * s, 350 * s))
    tick.lineTo(QPointF(326 * s, 252 * s))
    p.drawPath(tick)
    p.end()
    return img


def main():
    app = QGuiApplication([])  # noqa: F841 - QPainter on QImage needs a GUI app for fonts/raster
    ASSETS.mkdir(exist_ok=True)
    big = draw(512)
    big.save(str(ASSETS / "icon.png"))
    from PIL import Image
    im = Image.open(ASSETS / "icon.png").convert("RGBA")
    im.save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", ASSETS / "icon.png", "and", ASSETS / "icon.ico")


if __name__ == "__main__":
    main()
