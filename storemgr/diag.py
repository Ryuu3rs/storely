"""Diagnostics: the log (rotated, so it never grows without limit), crash capture (an installed windowed app has no
console, so an unexpected error would otherwise vanish) and a self-test of the Microsoft services Unjammed uses."""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler

from . import LOG_FILE

log = logging.getLogger("unjammed")
if not log.handlers:
    try:
        _h = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8", delay=True)
        _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))
        log.addHandler(_h)
    except OSError:
        log.addHandler(logging.NullHandler())
    log.setLevel(logging.INFO)

_showing = threading.Lock()


def crash_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def install_crash_handlers(gui: bool = False) -> None:
    """Log every uncaught error; in the window, also tell the user instead of silently dying."""
    def report(exc_type, exc, tb, where: str):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        log.critical("unhandled error in %s:\n%s", where, "".join(traceback.format_exception(exc_type, exc, tb)))
        if gui and threading.current_thread() is threading.main_thread() and _showing.acquire(blocking=False):
            try:
                from PySide6.QtWidgets import QApplication, QMessageBox
                if QApplication.instance():
                    QMessageBox.warning(None, "Unjammed", f"Something went wrong: {exc}\n\nThe details are in the log "
                                        f"(Settings > Open Unjammed's data folder):\n{LOG_FILE}")
            finally:
                _showing.release()

    sys.excepthook = lambda t, e, tb: report(t, e, tb, "main thread")
    threading.excepthook = lambda a: report(a.exc_type, a.exc_value, a.exc_traceback, a.thread.name if a.thread else "thread")


def selftest(market: str = "GB") -> list[dict]:
    """Can we reach each Microsoft service Unjammed depends on? (They're undocumented and can change.)"""
    from . import fe3
    from .browse import Browse
    from .catalog import Catalog

    def run(name: str, fn) -> dict:
        t0 = time.time()
        try:
            detail = fn() or "ok"
            return {"name": name, "ok": True, "ms": int((time.time() - t0) * 1000), "detail": detail}
        except Exception as e:
            return {"name": name, "ok": False, "ms": int((time.time() - t0) * 1000), "detail": str(e)[:200]}

    def catalog():
        p = Catalog(market).product("9WZDNCRFJBMP", fresh=True)
        if not p.title:
            raise RuntimeError("answered, but without product details")

    def search():
        cards, _ = Browse(market).search("calculator")
        if not cards:
            raise RuntimeError("answered, but found nothing")
        return f"{len(cards)} results"

    def delivery():
        fe3._cookie()

    return [run("Store catalogue (app details, update lookups)", catalog),
            run("Store search and charts", search),
            run("Windows Update delivery (downloads)", delivery)]
