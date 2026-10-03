"""Renders Unjammed's pages to PNGs for the README, using this PC's real data, without showing a window.

  .venv\\Scripts\\python.exe tools\\screenshots.py --out docs\\screenshots --theme dark home updates app:9WZDNCRFJ364

Privacy: the greeting never shows the account name, and --only-winget keeps just the listed winget ids (so the
picture doesn't list every program on the PC). Pages: home updates library downloads wishlist health settings,
app:<product id>, search:<words>. Also a smoke test: exits 1 if any page raised."""

import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app as A  # noqa: E402
from storemgr import ui_kit as K  # noqa: E402


def settle(qa, seconds):
    end = time.time() + seconds
    while time.time() < end:
        qa.processEvents()
        time.sleep(0.02)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="*", default=["home", "updates", "library", "downloads", "wishlist", "health", "settings"])
    ap.add_argument("--out")
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--size", default="1360x900")
    ap.add_argument("--only-winget", default="", help="comma-separated winget ids to keep in the Updates picture")
    a = ap.parse_args()
    errors = []
    sys.excepthook = lambda t, e, tb: errors.append("".join(traceback.format_exception(t, e, tb)))
    qa = QApplication([])
    K.apply_theme(a.theme)
    qa.setStyleSheet(K.STYLE)
    w = A.Main()
    w.settings["display_name"] = ""
    w.setAttribute(Qt.WA_DontShowOnScreen)
    w.resize(*map(int, a.size.split("x")))
    w.show()
    t0 = time.time()
    while (w.scanning or w.checking or not w.engine.apps) and time.time() - t0 < 120:
        settle(qa, 0.5)
    settle(qa, 15)     # winget list, pictures
    if a.only_winget:
        keep = {i.strip().lower() for i in a.only_winget.split(",")}
        w.winget_ups = [u for u in w.winget_ups if u.id.lower() in keep]
        w.refresh_badges()
    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    for p in a.pages:
        try:
            kind, _, arg = p.partition(":")
            if kind == "app":
                w.open_product(arg)
                settle(qa, 8)
            elif kind == "search":
                w.search.setText(arg)
                w.do_search()
                settle(qa, 8)
            else:
                w.show_page(kind)
            settle(qa, 3)
            if out:
                name = f"{a.theme}-{kind}" + (f"-{arg}" if arg else "")
                w.grab().save(str(out / f"{''.join(c if c.isalnum() or c in '-_' else '_' for c in name)}.png"))
        except Exception:
            errors.append(f"page {p}:\n{traceback.format_exc()}")
    print(f"apps={len(w.engine.apps)} runtimes={len(w.framework_ups)} winget={len(w.winget_ups)} ({w.winget_state})")
    print("\n".join(errors) if errors else "no errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
