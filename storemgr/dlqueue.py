"""Downloads & installs queue: pause / resume / cancel / reorder, survives restarts.

Downloads run in parallel (default 2), installs go one at a time (PC-wide lock). Pausing stops the download and
keeps the partial file, so resuming carries on where it left off."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal

from . import DATA_DIR, perms, winsys, wpm
from .download import LIMIT, Cancelled
from .engine import Engine, NotYetOut, log

QUEUE_FILE = DATA_DIR / "queue.json"
ACTIVE = ("downloading", "installing", "waiting")
FINAL = ("done", "failed", "cancelled", "skipped")


@dataclass
class Item:
    kind: str                    # "store" (MSIX via Microsoft's delivery service) | "desktop" (Store desktop installer)
                                 # | "winget" (other apps, through winget) | "framework" (shared runtime)
    key: str                     # package family (store, framework: name|arch) / product id (desktop) / winget id
    title: str
    product_id: str = ""
    icon_url: str | None = None
    close_app: bool = False
    version: str = ""             # store: install this exact (e.g. older) version instead of the newest
    state: str = "queued"        # queued downloading paused waiting approve installing done failed cancelled skipped
    done: float = 0
    total: float = 0
    speed: float = 0
    msg: str = "Queued"
    error: str = ""
    result: str = ""
    added: float = field(default_factory=time.time)
    finished: float = 0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])


class Queue(QObject):
    changed = Signal(str)             # item id ("" = order/structure)
    finished = Signal(str, bool, str)  # item id, ok, message
    approval = Signal(str)             # item id: downloaded, but adds permissions the user should OK

    def __init__(self, engine: Engine, browse, settings: dict):
        super().__init__()
        self.engine, self.browse, self.settings = engine, browse, settings
        self.items: list[Item] = []
        self._ctl: dict[str, threading.Event] = {}
        self._why: dict[str, str] = {}
        self._approval: dict[str, tuple] = {}     # item id -> (app, prepared download) waiting for the user's OK
        self.paused_all = False
        self._load()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._schedule)
        self.timer.start(700)

    # ------------------------------------------------------------------ persistence
    def _load(self):
        try:
            raw = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = []
        for d in raw:
            it = Item(**{k: v for k, v in d.items() if k in Item.__dataclass_fields__})
            if it.state in ACTIVE or it.state == "approve":
                it.state, it.msg = "queued", "Queued (resumed after restart)"
            self.items.append(it)

    def save(self):
        keep = [i for i in self.items if i.state not in FINAL] + \
               sorted([i for i in self.items if i.state in FINAL], key=lambda i: -i.finished)[:40]
        QUEUE_FILE.write_text(json.dumps([asdict(i) for i in keep]), encoding="utf-8")

    # ------------------------------------------------------------------ adding
    def find(self, key: str) -> Item | None:
        return next((i for i in self.items if i.key == key and i.state not in FINAL), None)

    def add_store(self, app, close_app=False, version: str = "") -> Item:
        cur = self.find(app.family)
        if cur:
            return cur
        p = app.product
        it = Item("store", app.family, app.title, p.product_id if p else "", p.icon_url if p else None, close_app, version)
        self.items.append(it)
        self._touch(it)
        return it

    def add_winget(self, up) -> Item:
        cur = self.find(up.id)
        if cur:
            return cur
        it = Item("winget", up.id, up.name, msg=f"Queued ({up.version} -> {up.available})")
        self.items.append(it)
        self._touch(it)
        return it

    def add_framework(self, have, pkg) -> Item:
        key = f"{have.name}|{have.arch}"
        cur = self.find(key)
        if cur:
            return cur
        it = Item("framework", key, f"{have.name} ({have.arch})", version=pkg.version_str)
        self.items.append(it)
        self._touch(it)
        return it

    # ------------------------------------------------------------------ permission approvals
    def approve(self, iid):
        """The user OK'd the new permissions: install what's already downloaded and checked."""
        it = self._get(iid)
        prep = self._approval.pop(iid, None)
        if not it or it.state != "approve" or prep is None:
            return
        app, prep = prep
        ev = threading.Event()
        self._ctl[it.id] = ev
        it.state, it.msg = "waiting", "Approved - waiting for Windows' installer"
        self._touch(it)
        threading.Thread(target=self._finish_store, args=(it, ev, app, prep), daemon=True).start()

    def decline(self, iid):
        it = self._get(iid)
        if it and self._approval.pop(iid, None) is not None:
            it.state, it.msg, it.finished = "cancelled", "Declined - not installed", time.time()
            self._touch(it)

    def add_desktop(self, desk: wpm.DesktopApp, icon_url=None) -> Item:
        cur = self.find(desk.product_id)
        if cur:
            return cur
        it = Item("desktop", desk.product_id, desk.title, desk.product_id, icon_url)
        self.items.append(it)
        self._touch(it)
        return it

    # ------------------------------------------------------------------ controls
    def pause(self, iid):
        it = self._get(iid)
        if not it:
            return
        if it.state == "downloading":
            self._why[iid] = "paused"
            self._ctl[iid].set()
        elif it.state == "queued":
            it.state, it.msg = "paused", "Paused"
            self._touch(it)

    def resume(self, iid):
        it = self._get(iid)
        if it and it.state in ("paused", "failed", "cancelled"):
            it.state, it.msg, it.error = "queued", "Queued", ""
            self._touch(it)

    def cancel(self, iid):
        it = self._get(iid)
        if not it:
            return
        if it.state in ("downloading", "waiting", "installing") and iid in self._ctl:
            self._why[iid] = "cancelled"
            self._ctl[iid].set()
        elif it.state in ("queued", "paused"):
            it.state, it.msg, it.finished = "cancelled", "Cancelled", time.time()
            self._touch(it)

    def move(self, iid, delta):
        it = self._get(iid)
        if not it:
            return
        i = self.items.index(it)
        j = max(0, min(len(self.items) - 1, i + delta))
        self.items.insert(j, self.items.pop(i))
        self.save()
        self.changed.emit("")

    def to_top(self, iid):
        it = self._get(iid)
        if it:
            self.items.remove(it)
            self.items.insert(0, it)
            self.save()
            self.changed.emit("")

    def pause_all(self):
        self.paused_all = True
        for it in self.items:
            if it.state in ("downloading", "queued"):
                self.pause(it.id)
        self.changed.emit("")

    def resume_all(self):
        self.paused_all = False
        for it in self.items:
            if it.state == "paused":
                self.resume(it.id)
        self.changed.emit("")

    def clear_finished(self):
        self.items = [i for i in self.items if i.state not in FINAL]
        self.save()
        self.changed.emit("")

    def set_speed_limit(self, mbps: float):
        LIMIT.bps = int(mbps * 1024 * 1024) if mbps else 0

    # ------------------------------------------------------------------ scheduler
    def active(self) -> list[Item]:
        return [i for i in self.items if i.state in ACTIVE]

    def pending(self) -> list[Item]:
        return [i for i in self.items if i.state not in FINAL]

    def _schedule(self):
        if self.paused_all:
            return
        running_dl = sum(1 for i in self.items if i.state == "downloading")
        limit = int(self.settings.get("parallel_downloads", 2))
        if not any(i.state == "queued" for i in self.items):
            return
        for on, why in ((self.settings.get("pause_on_metered", True) and winsys.metered(), "Waiting - metered connection"),
                        (self.settings.get("pause_on_battery") and winsys.on_battery(), "Waiting - on battery")):
            if on:
                for i in self.items:
                    if i.state == "queued" and i.msg != why:
                        i.msg = why
                        self.changed.emit(i.id)
                return
        for it in self.items:
            if running_dl >= limit:
                break
            if it.state == "queued":
                running_dl += 1
                self._start(it)

    def _start(self, it: Item):
        ev = threading.Event()
        self._ctl[it.id] = ev
        self._why.pop(it.id, None)
        it.state, it.msg, it.error = "downloading", "Starting", ""
        self._touch(it)
        threading.Thread(target=self._run, args=(it, ev), daemon=True).start()

    def _report(self, it: Item):
        last = [0.0]

        def report(stage, done, total, msg):
            if stage in ("install", "deps") and it.state == "downloading" and stage == "install":
                it.state = "waiting" if "Waiting" in msg else "installing"
            if stage == "install" and "Installing" in msg:
                it.state = "installing"
            it.done, it.total, it.msg = done, total, msg
            now = time.time()
            if now - last[0] > 0.25 or stage != "download":
                last[0] = now
                self.changed.emit(it.id)
        return report

    def _run(self, it: Item, ev: threading.Event):
        report = self._report(it)
        ok, msg = False, ""
        try:
            if it.kind == "store":
                app = self.engine.apps.get(it.key)
                if app is None and it.product_id:
                    app = self.engine.app_for_product(self.engine.catalog.product(it.product_id))
                if app is None:
                    raise RuntimeError("app not found")
                try:
                    pick = None
                    if it.version:
                        pick = next((f for f in self.engine.versions(app) if f.version_str == it.version), None)
                        if pick is None:
                            raise RuntimeError(f"Microsoft no longer serves version {it.version}")
                    prep = self.engine.prepare(app, report, ev, pick=pick)
                    if (self.settings.get("ask_new_permissions", True) and app.installed and prep.perms
                            and perms.has_risky(prep.perms)):
                        self._approval[it.id] = (app, prep)       # downloaded and verified; the user decides
                        it.state, it.msg = "approve", "New permissions: " + perms.summary(prep.perms).removeprefix("Adds: ")
                        it.error = "\n".join(f"{p.label} ({p.risk})" for p in prep.perms.added)
                        self._ctl.pop(it.id, None)
                        self._touch(it)
                        self.approval.emit(it.id)
                        return
                    it.state, it.msg = "waiting", "Downloaded - waiting for Windows' installer"
                    self.changed.emit(it.id)
                    v = self.engine.install(app, prep, report, ev, close_app=it.close_app)
                    ok, msg = True, f"Installed {v}"
                except NotYetOut as e:
                    it.state, it.result, it.msg = "skipped", str(e), "Not out yet"
                    ok, msg = True, f"nothing to install yet - {e}"
            elif it.kind == "winget":
                from . import winget
                v = winget.upgrade(it.key, report, ev)
                ok, msg = True, f"Updated to {v}" if v else "Updated"
            elif it.kind == "framework":
                name, arch = it.key.split("|", 1)
                have, pkg = next(((h, p) for h, p in self.engine.framework_updates()
                                  if h.name == name and h.arch == arch), (None, None))
                if have is None:
                    ok, msg = True, "already up to date"
                else:
                    ok, msg = True, f"Installed {self.engine.update_framework(have, pkg, report, ev)}"
            else:
                desk = wpm.resolve(self.browse, it.product_id, self.engine.catalog.market)
                v = wpm.install(desk, report, ev)
                ok, msg = True, f"Installed {v}"
        except Cancelled:
            why = self._why.pop(it.id, "cancelled")
            it.state = "paused" if why == "paused" else "cancelled"
            it.msg = "Paused - resumes where it left off" if why == "paused" else "Cancelled"
            if why != "paused":
                it.finished = time.time()
            self._touch(it)
            self._ctl.pop(it.id, None)
            return
        except Exception as e:
            ok, msg = False, str(e)
            log.error("queue %s %s failed: %s", it.kind, it.title, e)
        self._ctl.pop(it.id, None)
        if it.state != "skipped":
            it.state = "done" if ok else "failed"
        it.msg = msg.splitlines()[0][:200] if msg else it.msg
        it.error = "" if ok else msg
        it.result = msg
        it.finished = time.time()
        self._touch(it)
        self.finished.emit(it.id, ok, msg)

    def _finish_store(self, it: Item, ev: threading.Event, app, prep):
        report = self._report(it)
        try:
            v = self.engine.install(app, prep, report, ev, close_app=it.close_app)
            ok, msg = True, f"Installed {v}"
        except Cancelled:
            it.state, it.msg, it.finished = "cancelled", "Cancelled", time.time()
            self._ctl.pop(it.id, None)
            self._touch(it)
            return
        except Exception as e:
            ok, msg = False, str(e)
            log.error("queue store %s failed: %s", it.title, e)
        self._ctl.pop(it.id, None)
        it.state = "done" if ok else "failed"
        it.msg, it.error, it.result, it.finished = msg.splitlines()[0][:200], "" if ok else msg, msg, time.time()
        self._touch(it)
        self.finished.emit(it.id, ok, msg)

    # ------------------------------------------------------------------ helpers
    def _get(self, iid) -> Item | None:
        return next((i for i in self.items if i.id == iid), None)

    def _touch(self, it: Item):
        self.save()
        self.changed.emit(it.id)
