"""My Store - a Microsoft Store replacement that doesn't jam."""

from __future__ import annotations

import getpass
import re
import sys
import time
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QLineEdit, QMainWindow, QMenu, QMessageBox, QScrollArea, QStackedWidget,
                               QSystemTrayIcon, QToolButton, QVBoxLayout, QHBoxLayout, QWidget)

from storemgr import APP_ID, APP_NAME, ICON_FILE, __version__, admin, health, settings as settings_mod, storequeue, winapps, wpm
from storemgr import ui_kit as K
from storemgr.browse import Browse
from storemgr.cleanup import app_sizes
from storemgr.dlqueue import Queue
from storemgr.engine import App, Engine
from storemgr.jobs import Jobs
from storemgr.ui.browse_pages import BrowsePages
from storemgr.ui.manage_pages import ManagePages
from storemgr.ui.widgets import AppRow, label, button

PAGES = ("home", "updates", "library", "downloads", "wishlist", "health", "settings", "search", "app", "chart", "category")
NAV = (("home", "Home", "home"), ("updates", "Updates", "updates"), ("library", "Library", "library"),
       ("downloads", "Downloads", ""), ("wishlist", "Wishlist", ""), ("health", "Health", "health"))


def scroll_page():
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(36, 26, 36, 28)
    lay.setSpacing(14)
    sa.setWidget(inner)
    return sa, lay


class Main(QMainWindow, BrowsePages, ManagePages):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(ICON_FILE)))
        self.resize(1360, 900)
        self.settings = settings_mod.load()
        self.engine = Engine(self.settings["market"], self.settings["keep_rollback"], self.settings.setdefault("holds", {}))
        self.browse = Browse(self.settings["market"])
        self.jobs = Jobs(self.engine)
        self.jobs.close_apps = self.settings["close_apps"]
        self.queue = Queue(self.engine, self.browse, self.settings)
        self.queue.set_speed_limit(self.settings.get("speed_limit_mbps", 0))
        self.images = K.Images()
        self.rows: dict[str, list[AppRow]] = {}
        self.queue_rows = {}
        self.failures: dict[str, tuple[str, str]] = {}
        self.sizes: dict[str, int] = {}
        self.desktop_apps: dict[str, wpm.DesktopApp] = {}
        self.desktop_state: dict[str, str] = {}
        self.health = None
        self.scanning = self.checking = False
        self.last_check = 0.0
        self.history_stack = []
        self.current = None

        self.jobs.progress.connect(lambda fam, *a: self._refresh_family(fam))
        self.jobs.app_finished.connect(self.on_job_finished)
        self.jobs.changed.connect(self.refresh_badges)
        self.queue.changed.connect(self.on_queue_changed)
        self.queue.finished.connect(self.on_queue_finished)
        self._build()
        self._tray()
        self.watchdog = QTimer(self)
        self.watchdog.timeout.connect(self.check_health)
        self.watchdog.start(5 * 60 * 1000)
        QTimer.singleShot(50, self.rescan)

    # ------------------------------------------------------------------ layout
    def _build(self):
        root = QWidget()
        root.setObjectName("Root")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        nav = QVBoxLayout()
        nav.setContentsMargins(6, 54, 6, 10)
        nav.setSpacing(4)
        self.nav = {}
        for key, text, icon in NAV:
            nav.addWidget(self._nav_button(key, text, icon))
        nav.addStretch()
        nav.addWidget(self._nav_button("settings", "Settings", "settings"))
        outer.addLayout(nav)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(16, 10, 16, 10)
        self.back = button("", flat=True, icon="back", tip="Back")
        self.back.clicked.connect(self.go_back)
        self.back.setVisible(False)
        top.addWidget(self.back)
        brand = label(f"  {APP_NAME}")
        brand.setStyleSheet(f"color:{K.TEXT2}")
        top.addWidget(brand)
        top.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search apps, games and your library")
        self.search.addAction(K.glyph_icon("search", K.TEXT2, 16), QLineEdit.TrailingPosition)
        self.search.setFixedWidth(540)
        self.search.returnPressed.connect(self.do_search)
        top.addWidget(self.search)
        top.addStretch(1)
        self.health_chip = label("", "Chip")
        self.health_chip.setCursor(Qt.PointingHandCursor)
        self.health_chip.mousePressEvent = lambda e: self.show_page("health")
        top.addWidget(self.health_chip)
        right.addLayout(top)
        content = QWidget()
        content.setObjectName("Content")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        cl.addWidget(self.stack)
        right.addWidget(content, 1)
        outer.addLayout(right, 1)
        self.setCentralWidget(root)
        self.pages = {}
        for key in PAGES:
            sa, lay = scroll_page()
            self.pages[key] = (sa, lay)
            self.stack.addWidget(sa)
        for key, fn in (("F5", self.rescan), ("Ctrl+F", lambda: self.search.setFocus()), ("Alt+Left", self.go_back)):
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            self.addAction(a)
        self.show_page("home")

    def _nav_button(self, key, text, icon):
        b = QToolButton()
        b.setObjectName("Nav")
        b.setText(text)
        b.setIcon(K.glyph_icon(icon, K.TEXT, 22))
        b.setIconSize(QSize(22, 22))
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setCheckable(True)
        b.setFixedSize(72, 58)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda: self.show_page(key))
        self.nav[key] = b
        return b

    def _tray(self):
        self.tray = QSystemTrayIcon(QIcon(str(ICON_FILE)), self)
        m = QMenu()
        m.addAction("Open My Store", self.showNormal)
        m.addAction("Check for updates", self.check_updates)
        m.addAction("Update all", self.update_all)
        m.addAction("Downloads", lambda: (self.showNormal(), self.show_page("downloads")))
        m.addSeparator()
        m.addAction("Quit", QApplication.quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.showNormal() if r == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip(APP_NAME)
        self.tray.show()

    def notify(self, title, body, warn=False):
        if not self.settings.get("notify", True):
            return
        self.tray.showMessage(title, body, QSystemTrayIcon.Warning if warn else QSystemTrayIcon.Information, 6000)

    # ------------------------------------------------------------------ navigation
    def show_page(self, key, push=True):
        if push and self.current and self.current != key:
            self.history_stack.append(self.current)
            self.history_stack = self.history_stack[-30:]
        self.current = key
        for k, b in self.nav.items():
            b.setChecked(k == key)
        self.back.setVisible(bool(self.history_stack))
        self.stack.setCurrentWidget(self.pages[key][0])
        self.pages[key][0].verticalScrollBar().setValue(0)
        self.render_current()

    def go_back(self):
        if self.history_stack:
            self.show_page(self.history_stack.pop(), push=False)

    def render_current(self):
        getattr(self, f"render_{self.current}", lambda: None)()

    def do_search(self):
        self.search_query = self.search.text().strip()
        if self.search_query:
            self.show_page("search")

    # ------------------------------------------------------------------ data
    def rescan(self):
        if self.scanning:
            return
        self.scanning = True
        self.statusBar().showMessage("Reading installed apps...")
        self.jobs.run(self.engine.scan, self._scanned)

    def _scanned(self, result, error):
        self.scanning = False
        if error:
            self.statusBar().showMessage(f"Could not read installed apps: {error}")
            return
        self.statusBar().showMessage(f"{len(self.engine.apps)} Store apps")
        self.render_current()
        if self.settings["check_on_start"] or self.last_check:
            self.check_updates()
        self.check_health()
        self.refresh_desktop()
        self.jobs.run(lambda: app_sizes(list(self.engine.apps.values())), self._sized)

    def _sized(self, sizes, err):
        if sizes:
            self.sizes = sizes
            if self.current == "library":
                self.render_library()

    def refresh_desktop(self):
        def load():
            out = {}
            for pid in wpm.tracked():
                try:
                    out[pid] = wpm.resolve(self.browse, pid, self.engine.catalog.market)
                except Exception:
                    pass
            return out

        def done(res, err):
            if res is not None:
                self.desktop_apps = res
                self.desktop_state = {pid: ("Update" if d.update_available else "Installed" if d.installed_version else "")
                                      for pid, d in res.items()}
                self.refresh_badges()
        self.jobs.run(load, done)

    def check_updates(self):
        if self.checking or not self.engine.apps:
            return
        self.checking = True
        self.statusBar().showMessage("Checking Microsoft for updates...")
        self.jobs.run(self.engine.check_all, self._checked)

    def _checked(self, result, error):
        self.checking = False
        self.last_check = time.time()
        n = sum(1 for a in self.engine.apps.values() if a.update_available)
        self.statusBar().showMessage(f"Checked {datetime.now():%H:%M} - {n} update(s)" if not error else f"Check failed: {error}")
        self.refresh_badges()
        self.render_current()
        if n and not self.isVisible():
            self.notify(APP_NAME, f"{n} app update(s) available")
        for a in self.engine.apps.values():
            if a.update_available and a.family in self.settings["auto_update"] and not self.queue.find(a.family):
                if not (a.installed and winapps.running(a.installed.location)):
                    self.queue.add_store(a)

    def check_health(self):
        self.jobs.run(health.status, self._health)

    def _health(self, h, error):
        if error or h is None:
            return
        prev = self.health
        self.health = h
        if h["stuck"]:
            self.health_chip.setText(f"  ⚠ Installer jammed ({len(h['stuck'])})  ")
            self.health_chip.setStyleSheet(f"background:#4a2b2e; color:{K.BAD}; border-radius:10px; padding:2px 10px")
            if self.settings.get("auto_unjam") and not getattr(self, "_auto_unjammed", False):
                self._auto_unjammed = True     # cancel the Store's stuck items once, no prompt, then look again
                for i in storequeue.items():
                    if i.state not in ("Completed", "Cancelled"):
                        storequeue.cancel(i.family)
                QTimer.singleShot(20000, self.check_health)
            elif self.settings["watchdog"] and (not prev or not prev["stuck"]):
                self.notify(APP_NAME, f"Windows' app installer is jammed ({len(h['stuck'])} stuck job(s)). "
                            "Open My Store > Health and press Unjam.", warn=True)
        else:
            self._auto_unjammed = False
            self.health_chip.setText("  ✓ Installer healthy  ")
            self.health_chip.setStyleSheet(f"background:#25402a; color:{K.GOOD}; border-radius:10px; padding:2px 10px")
        if self.current in ("health", "home"):
            self.render_current()

    # ------------------------------------------------------------------ live updates
    def _refresh_family(self, family):
        for r in self.rows.get(family, []):
            try:
                r.refresh()
            except RuntimeError:
                pass

    def on_queue_changed(self, iid):
        it = self.queue._get(iid) if iid else None
        if it:
            self._refresh_family(it.key)
            r = self.queue_rows.get(iid)
            if r is not None:
                try:
                    r.refresh()
                except RuntimeError:
                    pass
            elif self.current == "downloads":
                self.render_downloads()
            if self.current == "app":
                a, d = getattr(self, "detail_app", None), getattr(self, "detail_desktop", None)
                if (a and a.family == it.key) or (d and d[1].product_id == it.key):
                    try:
                        self.detail_status.setText(it.msg)
                    except RuntimeError:
                        pass
        elif self.current == "downloads":
            self.render_downloads()
        self.refresh_badges(rows=False)

    def on_queue_finished(self, iid, ok, msg):
        it = self.queue._get(iid)
        if not it:
            return
        if ok:
            self.failures.pop(it.key, None)
        else:
            self.failures[it.key] = (winapps.explain(msg), msg)
            if not self.isVisible():
                self.notify(APP_NAME, f"{it.title} didn't update: {winapps.explain(msg)}", warn=True)
        if it.kind == "desktop":
            self.refresh_desktop()
        if not self.queue.active() and not [i for i in self.queue.items if i.state == "queued"]:
            done = [i for i in self.queue.items if i.state == "done" and time.time() - i.finished < 600]
            if done and not self.isActiveWindow():
                self.notify(APP_NAME, f"Finished: {', '.join(i.title for i in done[:4])}" + (" ..." if len(done) > 4 else ""))
        self.refresh_badges()
        if self.current in ("updates", "home", "library", "app"):
            self.render_current()

    def on_job_finished(self, family, ok, msg):
        name = self.engine.apps[family].title if family in self.engine.apps else (family or "Windows' installer")
        if family == "":
            (QMessageBox.information if ok else QMessageBox.warning)(self, APP_NAME, msg[:2000])
        elif ok:
            self.failures.pop(family, None)
            self.statusBar().showMessage(f"{name}: {msg.splitlines()[0] if msg else 'done'}", 10000)
        elif msg != "cancelled":
            self.failures[family] = (winapps.explain(msg), msg)
            self.statusBar().showMessage(f"{name}: {winapps.explain(msg)}", 15000)
        self.refresh_badges()
        if self.current in ("updates", "home", "health", "app", "library"):
            self.render_current()

    def refresh_badges(self, rows=True):
        n = sum(1 for a in self.engine.apps.values() if a.update_available) + \
            sum(1 for d in self.desktop_apps.values() if d.update_available)
        live = len(self.queue.pending())
        self.nav["updates"].setText(f"Updates ({n})" if n else "Updates")
        self.nav["downloads"].setText(f"Downloads ({live})" if live else "Downloads")
        self.tray.setToolTip(f"{APP_NAME} - {n} update(s)" + (f", {live} in Downloads" if live else ""))
        if rows:
            for fam in list(self.rows):
                self._refresh_family(fam)

    def _rows_for(self, lay, apps):
        for a in apps:
            row = AppRow(self, a)
            self.rows.setdefault(a.family, []).append(row)
            lay.addWidget(row)

    def _reset_rows(self):
        self.rows = {}

    # ------------------------------------------------------------------ actions
    def start_update(self, app: App, ask=True):
        self.failures.pop(app.family, None)
        close = self.jobs.close_apps
        if ask and app.installed and winapps.running(app.installed.location) and not close:
            if QMessageBox.question(self, APP_NAME, f"{app.title} is open. Close it when it's ready to install?") != QMessageBox.Yes:
                return
            close = True
        self.queue.add_store(app, close_app=close)
        self.statusBar().showMessage(f"{app.title} added to Downloads", 5000)
        self.refresh_badges()

    def row_primary(self, app: App):
        q = self.queue.find(app.family)
        if q:
            if q.state == "downloading":
                self.queue.pause(q.id)
            elif q.state == "paused":
                self.queue.resume(q.id)
            else:
                self.queue.cancel(q.id)
        elif self.jobs.busy(app.family):
            self.jobs.cancel(app.family)
        elif app.update_available or not app.installed or app.family in self.failures:
            self.start_update(app)
        elif app.entries:
            winapps.launch(app.family, app.entries[0].app_id)

    def update_all(self):
        apps = [a for a in self.engine.apps.values() if a.update_available and not self.queue.find(a.family)]
        desk = [d for d in self.desktop_apps.values() if d.update_available and not self.queue.find(d.product_id)]
        if not apps and not desk:
            self.statusBar().showMessage("Nothing to update", 5000)
            return
        open_ = [a.title for a in apps if a.installed and winapps.running(a.installed.location)]
        close = self.jobs.close_apps
        if open_ and not close:
            close = QMessageBox.question(self, APP_NAME, f"These are open: {', '.join(open_[:8])}.\n\nClose them when "
                                         "their update is ready? (No = update everything else, skip those)") == QMessageBox.Yes
        for a in sorted(apps, key=lambda a: a.latest.size):
            if close or not (a.installed and winapps.running(a.installed.location)):
                self.failures.pop(a.family, None)
                self.queue.add_store(a, close_app=close)
        for d in desk:
            self.queue.add_desktop(d)
        self.refresh_badges()
        self.show_page("downloads")

    def unjam_and_retry(self, apps):
        def after(result, error):
            QMessageBox.information(self, APP_NAME, (str(result or error) or "done")[:2000])
            for a in apps:
                self.start_update(a, ask=False)
            self.render_current()

        def work():
            steps = [f"Cancelled Store queue: {storequeue.cancel(i.family)}" for i in storequeue.items()]
            r = admin.unjam(None)
            return "\n".join(steps + r.get("steps", []) + [f"problem: {e}" for e in r.get("errors", [])])
        self.jobs.run(work, after)

    def set_hold(self, family, what):
        holds = self.settings.setdefault("holds", {})
        if what:
            holds[family] = what
        else:
            holds.pop(family, None)
        self.engine.holds = holds
        settings_mod.save(self.settings)
        a = self.engine.apps.get(family)
        if a:
            a.held = holds.get(family, "")
        self.refresh_badges()
        self.render_current()

    def app_menu(self, app: App, pos):
        m = QMenu(self)
        if app.family in self.failures:
            def show_error(a=app):
                short, full = self.failures[a.family]
                detail = "" if full.strip() in short else f"\n\nDetails:\n{full[:2500]}"
                QMessageBox.information(self, APP_NAME, f"{a.title}\n\n{short}{detail}")
            m.addAction(K.glyph_icon("warning", K.BAD), "Show the full error", show_error)
            m.addAction("Dismiss this error", lambda: (self.failures.pop(app.family, None), self.refresh_badges()))
            m.addSeparator()
        if app.entries:
            m.addAction(K.glyph_icon("open"), "Open", lambda: winapps.launch(app.family, app.entries[0].app_id))
        if app.update_available:
            m.addAction(K.glyph_icon("download"), "Update", lambda: self.start_update(app))
        m.addAction(K.glyph_icon("unjam", K.WARN), "Unjam", lambda: self.jobs.unjam(app))
        m.addAction(K.glyph_icon("unjam", K.WARN), "Unjam (deep clean, admin)", lambda: self.jobs.unjam(app, deep=True))
        hold = m.addMenu("Hold")
        cur = self.settings.get("holds", {}).get(app.family)
        hold.addAction(("✓ " if cur == "all" else "") + "Never update this app", lambda: self.set_hold(app.family, "all"))
        if app.latest:
            v = app.latest.version_str
            hold.addAction(("✓ " if cur == v else "") + f"Skip version {v}", lambda: self.set_hold(app.family, v))
        if cur:
            hold.addAction("Release hold", lambda: self.set_hold(app.family, None))
        if app.installed:
            m.addSeparator()
            m.addAction(K.glyph_icon("repair"), "Repair (keeps your data)",
                        lambda: self.jobs.simple(app, "Repair", lambda a: winapps.repair(a.installed)))
            m.addAction(K.glyph_icon("refresh"), "Reset (clears its data)...", lambda: self._confirm(
                f"Reset {app.title}? This deletes the app's data and sign-ins.",
                lambda: self.jobs.simple(app, "Reset", lambda a: winapps.reset(a.installed))))
            if self.engine.rollback_file(app):
                m.addAction(K.glyph_icon("rollback"), "Roll back to previous version",
                            lambda: self.jobs.simple(app, "Roll back", lambda a: self.engine.rollback(a, close_app=True)))
            if app.installed.removable:
                m.addAction(K.glyph_icon("delete", K.BAD), "Uninstall...", lambda: self._confirm(
                    f"Uninstall {app.title}?", lambda: self.jobs.simple(app, "Uninstall", lambda a: winapps.uninstall(a.installed))))
        m.addSeparator()
        auto = app.family in self.settings["auto_update"]
        m.addAction(("✓ " if auto else "") + "Update automatically (background)", lambda: self.toggle_auto(app))
        if app.product:
            m.addAction("Copy Store ID", lambda: QApplication.clipboard().setText(app.product.product_id))
        m.addAction("Details", lambda: self.open_app(app))
        m.exec(pos)

    def _confirm(self, text, fn):
        if QMessageBox.question(self, APP_NAME, text) == QMessageBox.Yes:
            fn()

    def toggle_auto(self, app):
        lst = self.settings["auto_update"]
        if app.family in lst:
            lst.remove(app.family)
        else:
            lst.append(app.family)
        settings_mod.save(self.settings)

    def closeEvent(self, e):
        if self.queue.active() or self.jobs.active:
            r = QMessageBox.question(self, APP_NAME, "Downloads or installs are still running. Keep them going in the tray?\n\n"
                                     "(No = quit now - paused downloads resume next time)")
            if r == QMessageBox.Yes:
                self.hide()
                e.ignore()
                return
        self.queue.save()
        self.tray.hide()
        self.engine.catalog.save()
        super().closeEvent(e)


    # ------------------------------------------------------------------ Store links (ms-windows-store://...)
    def handle_link(self, text: str):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        kind, value = parse_store_link(text)
        if kind == "product":
            self.open_product(value)
        elif kind == "family":
            app = next((a for a in self.engine.apps.values() if a.family.lower() == value.lower()), None)
            if app:
                self.open_app(app)
            else:
                self.jobs.run(lambda: self.engine.catalog.by_family(value),
                              lambda p, e: self.open_product(p.product_id) if p and not e else self.show_page("home"))
        elif kind == "search":
            self.search.setText(value)
            self.do_search()
        elif kind in ("updates", "library", "home"):
            self.show_page(kind)


def parse_store_link(text: str) -> tuple[str, str]:
    """ms-windows-store://pdp/?ProductId=9WZDNCRFJBMP -> ("product", "9WZDNCRFJBMP"); also PFN=, search, updates,
    library. ("", "") = not a Store link (just bring the window forward)."""
    u = urlsplit(text or "")
    if u.scheme.lower() != "ms-windows-store":
        return "", ""
    where = (u.netloc or u.path.strip("/")).lower()
    qs = {k.lower(): v for k, v in parse_qsl(u.query)}
    pid, pfn = qs.get("productid", ""), qs.get("pfn", "")
    if re.fullmatch(r"[A-Za-z0-9]{8,20}", pid):
        return "product", pid.upper()
    if winapps.FAMILY_RE.match(pfn):
        return "family", pfn
    if where in ("downloadsandupdates", "updates"):
        return "updates", ""
    if where == "search" and qs.get("query", "").strip():
        return "search", qs["query"].strip()[:200]
    if where == "library":
        return "library", ""
    return "home", ""


def _instance_name() -> str:
    return f"MyStore-{getpass.getuser()}"


def _hand_over(msg: str) -> bool:
    """Pass a link to the copy that's already open. True if one was."""
    s = QLocalSocket()
    s.connectToServer(_instance_name())
    if not s.waitForConnected(500):
        return False
    s.write(msg.encode("utf-8")[:4096])
    s.waitForBytesWritten(1000)
    s.disconnectFromServer()
    return True


def main(args: list[str] | None = None):
    args = sys.argv[1:] if args is None else args
    link = next((a for a in args if a.lower().startswith("ms-windows-store:")), "")
    try:   # own taskbar identity, so Windows shows our icon instead of Python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(ICON_FILE)))
    app.setQuitOnLastWindowClosed(True)
    if _hand_over(link or "show"):
        return 0
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.UserAccessOption)   # only this Windows account can talk to it
    QLocalServer.removeServer(_instance_name())
    server.listen(_instance_name())
    app.setStyleSheet(K.STYLE)
    w = Main()

    def incoming():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        sock.waitForReadyRead(1000)
        msg = bytes(sock.readAll()).decode("utf-8", "replace")
        sock.disconnectFromServer()
        w.handle_link(msg)
    server.newConnection.connect(incoming)
    w.show()
    if link:
        QTimer.singleShot(300, lambda: w.handle_link(link))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
