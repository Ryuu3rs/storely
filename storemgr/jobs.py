"""Background work for the UI: every engine call runs off the UI thread and reports back through signals."""

from __future__ import annotations

import itertools
import json
import threading
import time
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from . import DATA_DIR, admin, health, storequeue
from .download import Cancelled
from .engine import App, Engine, NotYetOut, log

HISTORY_FILE = DATA_DIR / "history.json"


class _Sig(QObject):
    done = Signal(int, object, object)                 # token, result, error text
    progress = Signal(str, str, float, float, str)      # family, stage, done, total, message


class _Task(QRunnable):
    def __init__(self, token, fn, sig):
        super().__init__()
        self.token, self.fn, self.sig = token, fn, sig

    def run(self):
        try:
            self.sig.done.emit(self.token, self.fn(), None)
        except Cancelled:
            self.sig.done.emit(self.token, None, "cancelled")
        except Exception as e:
            self.sig.done.emit(self.token, None, f"{e}" or traceback.format_exc(limit=1))


class Jobs(QObject):
    progress = Signal(str, str, float, float, str)    # family, stage, done, total, message
    app_finished = Signal(str, bool, str)              # family, ok, message
    changed = Signal()

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(8)
        self.sig = _Sig()
        self.sig.done.connect(self._done)
        self.sig.progress.connect(self.progress)
        self._tok = itertools.count(1)
        self._cb = {}
        self.active: dict[str, dict] = {}     # family -> {stage, done, total, msg, cancel}
        self.close_apps = False

    # ------------------------------------------------------------------ generic
    def run(self, fn, on_done=None):
        t = next(self._tok)
        self._cb[t] = on_done
        self.pool.start(_Task(t, fn, self.sig))
        return t

    def _done(self, token, result, error):
        cb = self._cb.pop(token, None)
        if cb:
            cb(result, error)

    # ------------------------------------------------------------------ per-app jobs
    def busy(self, family: str) -> bool:
        return family in self.active

    def _start(self, app: App, label: str, fn):
        if app.family in self.active:
            return
        cancel = threading.Event()
        self.active[app.family] = {"stage": "queued", "done": 0, "total": 0, "msg": label, "cancel": cancel}
        self.changed.emit()

        def report(stage, done, total, msg):
            st = self.active.get(app.family)
            if st:
                st.update(stage=stage, done=done, total=total, msg=msg)
            self.sig.progress.emit(app.family, stage, float(done), float(total), msg)

        def work():
            return fn(report, cancel)

        def finished(result, error):
            self.active.pop(app.family, None)
            ok = error is None
            msg = result if ok else error
            if not ok:
                log.error("%s %s (%s) failed: %s", label, app.title, app.family, msg)
            _history(app.title, label, ok, str(msg))
            self.app_finished.emit(app.family, ok, str(msg))
            self.changed.emit()

        self.run(work, finished)

    def cancel(self, family: str):
        st = self.active.get(family)
        if st:
            st["cancel"].set()

    def update(self, app: App, close_app: bool | None = None):
        close = self.close_apps if close_app is None else close_app
        before = app.current_str if app.installed else ""
        self._start(app, "Update" if app.installed else "Install",
                    lambda report, cancel: self._update(app, report, cancel, close, before))

    def _update(self, app, report, cancel, close, before):
        try:
            v = self.engine.update(app, report, cancel, close_app=close)
        except NotYetOut as e:
            return f"nothing to install yet - {e}"
        return f"{before} -> {v}" if before else f"installed {v}"

    def unjam(self, app: App | None, deep: bool = False, then_update: bool = True):
        """Per-app unjam: cancel the Store's stuck item, clear stuck installer jobs (admin), then update."""
        def fn(report, cancel):
            steps = []
            fam = app.family if app else None
            report("unjam", 0, 0, "Cancelling the Store's stuck item")
            cancelled = storequeue.cancel(fam) if fam else [storequeue.cancel(i.family) for i in storequeue.items()]
            if cancelled:
                steps.append(f"Cancelled Store queue: {cancelled}")
            report("unjam", 0, 0, "Looking for stuck installer jobs")
            name = (app.package_name.lower() + "_") if app else ""
            stuck = [j for j in health.installer_jobs() if not app or j.package.lower().startswith(name)]
            if stuck or deep or not app:
                report("unjam", 0, 0, "Clearing the installer (approve the admin prompt)")
                r = admin.unjam(fam)
                steps += r.get("steps", [])
                if not r.get("ok"):
                    steps += [f"problem: {e}" for e in r.get("errors", [])]
            else:
                steps.append("Windows' installer had no stuck job for this app")
            if app and then_update and app.product:
                self.engine.check(app)
                if app.update_available or not app.installed:
                    report("unjam", 0, 0, "Updating")
                    steps.append(f"Updated to {self.engine.update(app, report, cancel, close_app=self.close_apps)}")
            return "\n".join(steps) or "Nothing was stuck"
        if app:
            self._start(app, "Unjam", fn)
        else:
            self.run(lambda: fn(lambda *a: None, threading.Event()),
                     lambda r, e: (_history("Windows' installer", "Unjam", e is None, str(r or e)),
                                   self.app_finished.emit("", e is None, str(r or e))))

    def simple(self, app: App, label: str, action):
        """repair / reset / uninstall / rollback - action(app) -> (ok, err) or str."""
        def fn(report, cancel):
            report(label.lower(), 0, 0, f"{label}...")
            out = action(app)
            if isinstance(out, tuple):
                ok, err = out
                if not ok:
                    raise RuntimeError(err)
                return f"{label} done"
            return f"{label} done ({out})"
        self._start(app, label, fn)


def _history(title, action, ok, msg):
    try:
        h = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        h = []
    h.append({"t": time.time(), "title": title, "action": action, "ok": ok, "msg": msg[:500]})
    HISTORY_FILE.write_text(json.dumps(h[-500:]), encoding="utf-8")


def history() -> list[dict]:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
