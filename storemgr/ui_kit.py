"""Look and feel: Windows 11 Store-style dark and light themes, Fluent icon glyphs, cached remote images."""

from __future__ import annotations

import hashlib

import requests
from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap

from . import CACHE_DIR

PALETTES = {
    "dark": dict(BG="#202020", SURFACE="#272727", CARD="#2d2d2d", CARD_HOVER="#353535", CARD_BORDER="#333333",
                 BORDER="#3a3a3a", TEXT="#ffffff", TEXT2="#a8a8a8", ACCENT="#60cdff", ACCENT_TEXT="#000000",
                 ACCENT_HOVER="#5ab9e6", ACCENT_BORDER="#6fd3ff", ACCENT_DIS_BG="#3b5866", ACCENT_DIS_TEXT="#1e2a30",
                 GOOD="#6ccb5f", WARN="#fce100", BAD="#ff99a4", GOOD_BG="#25402a", BAD_BG="#4a2b2e",
                 WARN_CARD_BG="#3b2427", WARN_CARD_BORDER="#6b3a40", INPUT="#2b2b2b", INPUT_FOCUS="#1f1f1f",
                 INPUT_LINE="#8a8a8a", BTN="#373737", BTN_BORDER="#434343", BTN_HOVER="#3d3d3d", BTN_PRESSED="#2f2f2f",
                 BTN_DIS_BG="#2e2e2e", BTN_DIS_TEXT="#6f6f6f", FLAT_HOVER="#3a3a3a", NAV_HOVER="#2d2d2d",
                 SCROLL="#5a5a5a", PROGRESS_BG="#4a4a4a", MENU="#2c2c2c", MENU_BORDER="#454545", MENU_SEL="#3a3a3a",
                 CHIP="#3a3a3a", ICON_BG="#3a3a3a", SHOT_BG="#1f1f1f", HERO_BORDER="#3c3c3c",
                 HERO="stop:0 #1d4a63, stop:0.55 #23384d, stop:1 #2a2440"),
    "light": dict(BG="#f3f3f3", SURFACE="#f9f9f9", CARD="#ffffff", CARD_HOVER="#f6f6f6", CARD_BORDER="#e5e5e5",
                  BORDER="#e0e0e0", TEXT="#1a1a1a", TEXT2="#5d5d5d", ACCENT="#005fb8", ACCENT_TEXT="#ffffff",
                  ACCENT_HOVER="#196ebf", ACCENT_BORDER="#0067c0", ACCENT_DIS_BG="#bcd3ea", ACCENT_DIS_TEXT="#f3f7fb",
                  GOOD="#0f7b0f", WARN="#9d5d00", BAD="#c42b1c", GOOD_BG="#dff6dd", BAD_BG="#fde7e9",
                  WARN_CARD_BG="#fde7e9", WARN_CARD_BORDER="#f1b9be", INPUT="#ffffff", INPUT_FOCUS="#ffffff",
                  INPUT_LINE="#868686", BTN="#fbfbfb", BTN_BORDER="#d6d6d6", BTN_HOVER="#f3f3f3", BTN_PRESSED="#ececec",
                  BTN_DIS_BG="#f5f5f5", BTN_DIS_TEXT="#a0a0a0", FLAT_HOVER="#ebebeb", NAV_HOVER="#e9e9e9",
                  SCROLL="#b0b0b0", PROGRESS_BG="#d6d6d6", MENU="#f9f9f9", MENU_BORDER="#d6d6d6", MENU_SEL="#ececec",
                  CHIP="#e6e6e6", ICON_BG="#e6e6e6", SHOT_BG="#e9e9e9", HERO_BORDER="#dcdcdc",
                  HERO="stop:0 #cfe8f7, stop:0.55 #dfe7f3, stop:1 #e9e3f5"),
}
THEME = "dark"


def windows_theme() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
    except OSError:
        return "dark"


def apply_theme(mode: str = "system") -> str:
    """Set the palette (module constants such as TEXT, ACCENT) and STYLE before any window is built."""
    global THEME, STYLE
    THEME = windows_theme() if mode not in PALETTES else mode
    globals().update(PALETTES[THEME])
    STYLE = _style()
    return THEME


globals().update(PALETTES["dark"])

ICON_FONT = "Segoe Fluent Icons"
G = {"home": "", "updates": "", "library": "", "health": "", "settings": "",
     "search": "", "more": "", "refresh": "", "close": "", "repair": "",
     "delete": "", "open": "", "star": "", "check": "", "warning": "",
     "unjam": "", "back": "", "download": "", "shield": "", "history": "",
     "app": "", "rollback": ""}

IMG_DIR = CACHE_DIR / "img"
IMG_DIR.mkdir(parents=True, exist_ok=True)

def _style() -> str:
    c = PALETTES[THEME]
    return """
* { font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 10pt; color: %(TEXT)s; }
QMainWindow, #Root { background: %(BG)s; }
#Content { background: %(SURFACE)s; border-top-left-radius: 8px; border-left: 1px solid %(BORDER)s; border-top: 1px solid %(BORDER)s; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: %(SCROLL)s; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(SCROLL)s; border-radius: 4px; min-width: 30px; }
QLineEdit { background: %(INPUT)s; border: 1px solid %(BORDER)s; border-bottom: 1px solid %(INPUT_LINE)s; border-radius: 6px;
            padding: 6px 10px; selection-background-color: %(ACCENT)s; selection-color: %(ACCENT_TEXT)s; }
QLineEdit:focus { border-bottom: 2px solid %(ACCENT)s; background: %(INPUT_FOCUS)s; }
QPushButton { background: %(BTN)s; border: 1px solid %(BTN_BORDER)s; border-radius: 5px; padding: 6px 16px; }
QPushButton:hover { background: %(BTN_HOVER)s; }
QPushButton:pressed { background: %(BTN_PRESSED)s; color: %(TEXT2)s; }
QPushButton:disabled { color: %(BTN_DIS_TEXT)s; background: %(BTN_DIS_BG)s; }
QPushButton[accent="true"] { background: %(ACCENT)s; color: %(ACCENT_TEXT)s; border: 1px solid %(ACCENT_BORDER)s; font-weight: 600; }
QPushButton[accent="true"]:hover { background: %(ACCENT_HOVER)s; }
QPushButton[accent="true"]:disabled { background: %(ACCENT_DIS_BG)s; color: %(ACCENT_DIS_TEXT)s; }
QPushButton[flat="true"] { background: transparent; border: none; padding: 6px; }
QPushButton[flat="true"]:hover { background: %(FLAT_HOVER)s; }
QToolButton#Nav { background: transparent; border: none; border-radius: 6px; padding: 6px 2px; color: %(TEXT2)s; font-size: 8pt; }
QToolButton#Nav:hover { background: %(NAV_HOVER)s; }
QToolButton#Nav:checked { background: %(NAV_HOVER)s; color: %(TEXT)s; }
QProgressBar { background: %(PROGRESS_BG)s; border: none; border-radius: 2px; height: 4px; max-height: 4px; }
QProgressBar::chunk { background: %(ACCENT)s; border-radius: 2px; }
QFrame#Card { background: %(CARD)s; border: 1px solid %(CARD_BORDER)s; border-radius: 8px; }
QFrame#Card:hover { background: %(CARD_HOVER)s; }
QFrame#Hero { border-radius: 10px; border: 1px solid %(HERO_BORDER)s;
              background: qlineargradient(x1:0, y1:0, x2:1, y2:1, %(HERO)s); }
QLabel#H1 { font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-size: 20pt; font-weight: 600; }
QLabel#H2 { font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-size: 14pt; font-weight: 600; }
QLabel#Muted { color: %(TEXT2)s; }
QLabel#Chip { background: %(CHIP)s; border-radius: 10px; padding: 2px 10px; font-size: 9pt; }
QMenu { background: %(MENU)s; border: 1px solid %(MENU_BORDER)s; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 28px 6px 12px; border-radius: 4px; }
QMenu::item:selected { background: %(MENU_SEL)s; }
QMenu::separator { height: 1px; background: %(MENU_BORDER)s; margin: 4px 8px; }
QCheckBox::indicator { width: 18px; height: 18px; }
QComboBox { background: %(CARD)s; border: 1px solid %(BORDER)s; border-radius: 5px; padding: 5px 10px; }
QToolTip { background: %(MENU)s; color: %(TEXT)s; border: 1px solid %(MENU_BORDER)s; padding: 4px; }
QMessageBox { background: %(SURFACE)s; }
""" % c


STYLE = _style()


def glyph_icon(key: str, color: str | None = None, size: int = 20) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    f = QFont(ICON_FONT)
    f.setPixelSize(int(size * 1.6))
    p.setFont(f)
    p.setPen(QColor(color or globals()["TEXT"]))
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
