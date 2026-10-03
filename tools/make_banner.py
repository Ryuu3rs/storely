"""Draws docs/banner.png (1280x640: README header + GitHub social preview) from the icon and a screenshot.
Run: .venv\\Scripts\\python.exe tools\\make_banner.py docs\\screenshots\\dark-home.png"""

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

ROOT = Path(__file__).resolve().parent.parent
W, H = 1280, 640


def main(shot: str):
    app = QGuiApplication([])  # noqa: F841 - fonts need a GUI app
    img = QImage(W * 2, H * 2, QImage.Format_ARGB32)
    img.setDevicePixelRatio(2)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor("#0b1e48"))
    g.setColorAt(0.55, QColor("#13306e"))
    g.setColorAt(1, QColor("#1f5fd6"))
    p.fillRect(0, 0, W, H, g)

    icon = QImage(str(ROOT / "assets" / "icon.png"))
    p.drawImage(QRectF(64, 72, 96, 96), icon)
    f = QFont("Segoe UI Variable Display")
    f.setPixelSize(72)
    f.setWeight(QFont.Bold)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(64, 190, 560, 90), Qt.AlignLeft | Qt.AlignVCenter, "Unjammed")
    f.setPixelSize(30)
    f.setWeight(QFont.DemiBold)
    p.setFont(f)
    p.setPen(QColor("#9fd8ff"))
    p.drawText(QRectF(64, 280, 560, 44), Qt.AlignLeft | Qt.AlignVCenter, "The Microsoft Store, unjammed.")
    f = QFont("Segoe UI Variable Text")
    f.setPixelSize(22)
    p.setFont(f)
    p.setPen(QColor("#dce9ff"))
    y = 350
    for line in ("Installs and updates Store apps - never stuck",
                 "Plus your other programs, through winget",
                 "Warns when an update wants new permissions",
                 "Free, open source, no account, no tracking"):
        p.setBrush(QColor("#60cdff"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(66, y + 12, 9, 9))
        p.setPen(QColor("#dce9ff"))
        p.drawText(QRectF(88, y, 520, 34), Qt.AlignLeft | Qt.AlignVCenter, line)
        y += 44

    s = QImage(shot)
    sw = 600
    sh = int(s.height() * sw / s.width())
    r = QRectF(640, (H - sh) / 2, sw, sh)
    for i in range(14, 0, -2):          # soft shadow
        sp = QPainterPath()
        sp.addRoundedRect(r.adjusted(-i, -i + 8, i, i + 8), 14 + i, 14 + i)
        p.fillPath(sp, QColor(0, 0, 0, 10))
    clip = QPainterPath()
    clip.addRoundedRect(r, 12, 12)
    p.save()
    p.setClipPath(clip)
    p.drawImage(r, s)
    p.restore()
    p.setPen(QPen(QColor(255, 255, 255, 60), 1))
    p.setBrush(Qt.NoBrush)
    p.drawPath(clip)
    p.end()
    out = ROOT / "docs" / "banner.png"
    out.parent.mkdir(exist_ok=True)
    img.scaled(W, H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).save(str(out))
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1])
