"""Records docs/demo.gif: the real app, driven by a script and drawn with a pointer, without showing a window.

  .venv\\Scripts\\python.exe tools\\record_demo.py --only-winget RARLab.WinRAR,Zoom.Zoom.EXE

Same privacy rules as screenshots.py: no account name, and only the listed winget ids appear."""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app as A  # noqa: E402
from storemgr import ui_kit as K  # noqa: E402

FPS = 12


class Recorder:
    def __init__(self, qa, w, scale):
        self.qa, self.w, self.scale = qa, w, scale
        self.frames: list[Image.Image] = []
        self.pointer = QPointF(w.width() * 0.6, w.height() * 0.5)

    def settle(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.qa.processEvents()
            time.sleep(0.01)

    def frame(self):
        img = self.w.grab().toImage().convertToFormat(QImage.Format_RGB888)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        x, y = self.pointer.x(), self.pointer.y()
        arrow = QPainterPath(QPointF(x, y))
        for dx, dy in ((0, 22), (6, 17), (10, 26), (14, 24), (10, 15), (17, 15)):
            arrow.lineTo(x + dx, y + dy)
        arrow.closeSubpath()
        p.setPen(QPen(QColor("#000000"), 1.5))
        p.setBrush(QColor("#ffffff"))
        p.drawPath(arrow)
        p.end()
        pil = Image.frombytes("RGB", (img.width(), img.height()), bytes(img.constBits())[: img.sizeInBytes()],
                              "raw", "RGB", img.bytesPerLine())
        self.frames.append(pil.resize((int(pil.width * self.scale), int(pil.height * self.scale)), Image.LANCZOS))

    def hold(self, seconds):
        for _ in range(int(seconds * FPS)):
            self.settle(1 / FPS)
            self.frame()

    def move_to(self, widget, seconds=0.6):
        target = QPointF(widget.mapTo(self.w, QPoint(widget.width() // 2, widget.height() // 2)))
        start, n = QPointF(self.pointer), max(1, int(seconds * FPS))
        for i in range(1, n + 1):
            t = i / n
            t = t * t * (3 - 2 * t)        # ease in-out
            self.pointer = start + (target - start) * t
            self.settle(1 / FPS)
            self.frame()

    def click(self, widget, then=None, seconds=0.6):
        self.move_to(widget, seconds)
        (then or widget.click)()
        self.hold(0.3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/demo.gif")
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--only-winget", default="")
    ap.add_argument("--app", default="9NCBCSZSJRSB", help="product id to open (default: Spotify)")
    a = ap.parse_args()
    qa = QApplication([])
    K.apply_theme(a.theme)
    qa.setStyleSheet(K.STYLE)
    w = A.Main()
    w.settings["display_name"] = ""
    w.setAttribute(Qt.WA_DontShowOnScreen)
    w.resize(1280, 800)
    w.show()
    r = Recorder(qa, w, 0.75)
    t0 = time.time()
    while (w.scanning or w.checking or not w.engine.apps) and time.time() - t0 < 120:
        r.settle(0.5)
    r.settle(15)
    if a.only_winget:
        keep = {i.strip().lower() for i in a.only_winget.split(",")}
        w.winget_ups = [u for u in w.winget_ups if u.id.lower() in keep]
        w.refresh_badges()
    w.show_page("home")
    r.settle(2)

    r.hold(1.6)                                             # home
    r.click(w.nav["updates"])                               # every update in one place
    r.hold(2.6)
    r.move_to(w.search)                                     # search the Store
    w.search.setFocus()
    w.search.clear()
    for ch in "spotify":
        w.search.setText(w.search.text() + ch)
        r.hold(0.12)
    w.do_search()
    r.settle(6)
    r.hold(1.6)
    w.open_product(a.app)                                   # an app page, with what it can access
    r.settle(8)
    r.hold(1.4)
    sa = w.pages["app"][0]
    bar = sa.verticalScrollBar()
    target = min(bar.maximum(), 300)            # down to "Details", where the permissions line is
    for i in range(1, 13):
        bar.setValue(int(target * i / 12))
        r.hold(1 / FPS)
    r.hold(2.0)
    r.click(w.nav["health"])                                # the jam detector
    r.hold(2.4)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pal = r.frames[len(r.frames) // 2].quantize(colors=200, method=Image.Quantize.MEDIANCUT)
    frames = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in r.frames]
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    print(f"wrote {out}: {len(frames)} frames, {out.stat().st_size / 1048576:.1f} MB")


if __name__ == "__main__":
    main()
