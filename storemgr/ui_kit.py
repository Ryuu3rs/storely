"""Look and feel: Windows 11 Store-style dark theme, Fluent icon glyphs, cached remote images."""

from __future__ import annotations

import hashlib

import requests
from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap

from . import CACHE_DIR

BG = "#202020"
SURFACE = "#272727"
CARD = "#2d2d2d"
CARD_HOVER = "#353535"
BORDER = "#3a3a3a"
TEXT = "#ffffff"
TEXT2 = "#a8a8a8"
ACCENT = "#60cdff"
ACCENT_TEXT = "#000000"
GOOD = "#6ccb5f"
WARN = "#fce100"
BAD = "#ff99a4"

ICON_FONT = "Segoe Fluent Icons"
G = {"home": "", "updates": "", "library": "", "health": "", "settings": "",
     "search": "", "more": "", "refresh": "", "close": "", "repair": "",
     "delete": "", "open": "", "star": "", "check": "", "warning": "",
     "unjam": "", "back": "", "download": "", "shield": "", "history": "",
     "app": "", "rollback": ""}

IMG_DIR = CACHE_DIR / "img"
IMG_DIR.mkdir(parents=True, exist_ok=True)

STYLE = f"""
* {{ font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 10pt; color: {TEXT}; }}
QMainWindow, #Root {{ background: {BG}; }}
#Content {{ background: {SURFACE}; border-top-left-radius: 8px; border-left: 1px solid {BORDER}; border-top: 1px solid {BORDER}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #5a5a5a; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #5a5a5a; border-radius: 4px; min-width: 30px; }}
QLineEdit {{ background: #2b2b2b; border: 1px solid {BORDER}; border-bottom: 1px solid #8a8a8a; border-radius: 6px;
             padding: 6px 10px; selection-background-color: {ACCENT}; selection-color: black; }}
QLineEdit:focus {{ border-bottom: 2px solid {ACCENT}; background: #1f1f1f; }}
QPushButton {{ background: #373737; border: 1px solid #434343; border-radius: 5px; padding: 6px 16px; }}
QPushButton:hover {{ background: #3d3d3d; }}
QPushButton:pressed {{ background: #2f2f2f; color: {TEXT2}; }}
QPushButton:disabled {{ color: #6f6f6f; background: #2e2e2e; }}
QPushButton[accent="true"] {{ background: {ACCENT}; color: {ACCENT_TEXT}; border: 1px solid #6fd3ff; font-weight: 600; }}
QPushButton[accent="true"]:hover {{ background: #5ab9e6; }}
QPushButton[accent="true"]:disabled {{ background: #3b5866; color: #1e2a30; }}
QPushButton[flat="true"] {{ background: transparent; border: none; padding: 6px; }}
QPushButton[flat="true"]:hover {{ background: #3a3a3a; }}
QToolButton#Nav {{ background: transparent; border: none; border-radius: 6px; padding: 6px 2px; color: {TEXT2}; font-size: 8pt; }}
QToolButton#Nav:hover {{ background: #2d2d2d; }}
QToolButton#Nav:checked {{ background: #2d2d2d; color: {TEXT}; }}
QProgressBar {{ background: #4a4a4a; border: none; border-radius: 2px; height: 4px; max-height: 4px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}
QFrame#Card {{ background: {CARD}; border: 1px solid #333333; border-radius: 8px; }}
QFrame#Card:hover {{ background: {CARD_HOVER}; }}
QFrame#Hero {{ border-radius: 10px; border: 1px solid #3c3c3c;
               background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1d4a63, stop:0.55 #23384d, stop:1 #2a2440); }}
QLabel#H1 {{ font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-size: 20pt; font-weight: 600; }}
QLabel#H2 {{ font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-size: 14pt; font-weight: 600; }}
QLabel#Muted {{ color: {TEXT2}; }}
QLabel#Chip {{ background: #3a3a3a; border-radius: 10px; padding: 2px 10px; font-size: 9pt; }}
QMenu {{ background: #2c2c2c; border: 1px solid #454545; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: #3a3a3a; }}
QMenu::separator {{ height: 1px; background: #454545; margin: 4px 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; }}
QComboBox {{ background: #2d2d2d; border: 1px solid {BORDER}; border-radius: 5px; padding: 5px 10px; }}
QToolTip {{ background: #2c2c2c; color: {TEXT}; border: 1px solid #454545; padding: 4px; }}
QMessageBox {{ background: {SURFACE}; }}
"""


def glyph_icon(key: str, color: str = TEXT, size: int = 20) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    f = QFont(ICON_FONT)
    f.setPixelSize(int(size * 1.6))
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(pm.rect(), Qt.AlignCenter, G.get(key, key))
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


def rounded(pm: QPixmap, size: int, radius: int = 8, bg: str | None = None) -> QPixmap:
    out = QPixmap(size * 2, size * 2)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size * 2, size * 2, radius * 2, radius * 2)
    p.setClipPath(path)
    if bg and bg.lower() not in ("transparent", "#00000000"):
        p.fillPath(path, QColor(bg))
    if not pm.isNull():
        scaled = pm.scaled(QSize(size * 2, size * 2), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap((size * 2 - scaled.width()) // 2, (size * 2 - scaled.height()) // 2, scaled)
    p.end()
    out.setDevicePixelRatio(2)
    return out


def letter_tile(text: str, size: int) -> QPixmap:
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size * 2, size * 2, 16, 16)
    hue = int(hashlib.md5(text.encode()).hexdigest()[:2], 16) * 360 // 256
    p.fillPath(path, QColor.fromHsl(hue, 90, 70))
    f = QFont("Segoe UI Variable Display")
    f.setPixelSize(size)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(pm.rect(), Qt.AlignCenter, (text[:1] or "?").upper())
    p.end()
    pm.setDevicePixelRatio(2)
    return pm


class _ImgSignals(QObject):
    loaded = Signal(str, str)


class _ImgJob(QRunnable):
    def __init__(self, url, path, signals):
        super().__init__()
        self.url, self.path, self.signals = url, path, signals

    def run(self):
        try:
            r = requests.get(self.url + ("&" if "?" in self.url else "?") + "w=192&h=192", timeout=20)
            if r.ok and r.content:
                self.path.write_bytes(r.content)
                self.signals.loaded.emit(self.url, str(self.path))
        except (requests.RequestException, RuntimeError):   # RuntimeError: window closed while downloading
            pass


class Images(QObject):
    """Downloads store artwork once, caches it on disk, tells waiting widgets when it lands."""
    loaded = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(6)
        self.sig = _ImgSignals()
        self.sig.loaded.connect(self.loaded)
        self.pending = set()

    def path_for(self, url: str):
        return IMG_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".img")

    def get(self, url: str | None) -> str | None:
        """Cached file path now, or None and a 'loaded' signal later."""
        if not url:
            return None
        p = self.path_for(url)
        if p.exists() and p.stat().st_size:
            return str(p)
        if url not in self.pending:
            self.pending.add(url)
            self.pool.start(_ImgJob(url, p, self.sig))
        return None
