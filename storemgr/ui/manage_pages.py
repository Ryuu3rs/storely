"""Updates, Library, Downloads queue, Wishlist, Health (+ clean-up) and Settings."""

from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QMessageBox,
                               QVBoxLayout)

import sys

import PySide6

from ..winsys import store_links_ours
from .. import DATA_DIR, FROZEN, ROOT, __version__, admin, background, cleanup, settings as settings_mod, storequeue, wpm
from .. import ui_kit as K
from ..browse import Card
from .widgets import AppIcon, Grid, QueueRow, StoreTile, button, clear, fmt_size, label


class ManagePages:
    # ------------------------------------------------------------------ updates
    def render_updates(self):
        _, lay = self.pages["updates"]
        clear(lay)
        self._reset_rows()
        head = QHBoxLayout()
        head.addWidget(label("Updates", "H1"))
        head.addStretch()
        when = f"Last checked {datetime.fromtimestamp(self.last_check):%H:%M}" if self.last_check else "Not checked yet"
        head.addWidget(label("Checking..." if self.checking else when, "Muted"))
        ck = button("Check for updates", icon="refresh")
        ck.clicked.connect(self.check_updates)
        ua = button("Update all", accent=True, icon="download")
        ua.clicked.connect(self.update_all)
        head.addWidget(ck)
        head.addWidget(ua)
        lay.addLayout(head)
        apps = list(self.engine.apps.values())
        failed = [a for a in apps if a.family in self.failures and not self.queue.find(a.family)]
        busy = [a for a in apps if self.queue.find(a.family) or self.jobs.busy(a.family)]
        ups = [a for a in apps if a.update_available and a not in busy and a.family not in self.failures]
        held = [a for a in apps if a.is_held]
        if failed:
            fh = QHBoxLayout()
            fh.addWidget(label(f"Needs attention ({len(failed)})", "H2"))
            fh.addStretch()
            ra = button("Retry all", icon="refresh")
            ra.clicked.connect(lambda: [self.start_update(a, ask=False) for a in failed])
            ua2 = button("Unjam & retry all", icon="unjam", tip="Cancels the Store's stuck jobs and clears the installer "
                         "(one admin prompt), then retries each failed app")
            ua2.clicked.connect(lambda: self.unjam_and_retry(failed))
            fh.addWidget(ra)
            fh.addWidget(ua2)
            lay.addLayout(fh)
            self._rows_for(lay, sorted(failed, key=lambda a: a.title.lower()))
        if busy:
            bh = QHBoxLayout()
            bh.addWidget(label(f"In progress ({len(busy)})", "H2"))
            bh.addStretch()
            go = button("Open Downloads")
            go.clicked.connect(lambda: self.show_page("downloads"))
            bh.addWidget(go)
            lay.addLayout(bh)
            self._rows_for(lay, busy)
        lay.addWidget(label(f"Available ({len(ups)})", "H2"))
        if ups:
            self._rows_for(lay, sorted(ups, key=lambda a: a.title.lower()))
        else:
            lay.addWidget(label("Everything is up to date." if self.last_check else "Press 'Check for updates'.", "Muted"))
        desk = [d for d in self.desktop_apps.values() if d.update_available]
        if desk:
            lay.addWidget(label(f"Desktop apps from the Store ({len(desk)})", "H2"))
            for d in desk:
                lay.addWidget(self._desktop_row(d))
        if held:
            lay.addWidget(label(f"Held back ({len(held)})", "H2"))
            self._rows_for(lay, held)
        q = [i for i in storequeue.items() if i.state not in ("Completed", "Cancelled")]
        if q:
            lay.addWidget(label("Stuck in the Microsoft Store's own queue", "H2"))
            for i in q:
                row = QFrame()
                row.setObjectName("Card")
                rl = QHBoxLayout(row)
                rl.addWidget(label(f"{i.family.split('_')[0]}  ·  {i.state}  {i.percent:.0f}%  {i.error}"))
                rl.addStretch()
                b = button("Cancel it")
                b.clicked.connect(lambda _, f=i.family: (storequeue.cancel(f), self.render_updates()))
                rl.addWidget(b)
                lay.addWidget(row)
        lay.addStretch()

    def _desktop_row(self, d: wpm.DesktopApp) -> QFrame:
        row = QFrame()
        row.setObjectName("Card")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(14, 10, 14, 10)
        ic = AppIcon(self, 40)
        ic.set_app(d.title)
        rl.addWidget(ic)
        mid = QVBoxLayout()
        mid.addWidget(label(d.title))
        mid.addWidget(label(f"{d.publisher}  ·  Version {d.installed_version or '-'}" +
                            (f"  →  {d.version}" if d.update_available else "") + "  ·  desktop installer", "Muted"))
        rl.addLayout(mid, 1)
        qi = self.queue.find(d.product_id)
        b = button(qi.msg[:30] if qi else ("Update" if d.update_available else "Open page"), accent=d.update_available and not qi)
        b.clicked.connect(lambda: self.show_page("downloads") if qi else
                          (self.get_desktop(d, None) if d.update_available else self.open_product(d.product_id)))
        rl.addWidget(b)
        return row

    # ------------------------------------------------------------------ library
    def render_library(self):
        _, lay = self.pages["library"]
        clear(lay)
        self._reset_rows()
        head = QHBoxLayout()
        head.addWidget(label("Library", "H1"))
        head.addStretch()
        flt = QLineEdit(getattr(self, "lib_filter_text", ""))
        flt.setPlaceholderText("Filter your apps")
        flt.setFixedWidth(240)
        sort = QComboBox()
        sort.addItems(["Name", "Updates first", "Publisher", "Size (biggest first)"])
        sort.setCurrentIndex(getattr(self, "lib_sort", 0))
        exp = button("Export list", tip="Save the list of your Store apps - import it on another PC to install them all")
        exp.clicked.connect(self.export_apps)
        imp = button("Import list")
        imp.clicked.connect(self.import_apps)
        for w_ in (flt, sort, exp, imp):
            head.addWidget(w_)
        lay.addLayout(head)
        apps = list(self.engine.apps.values())
        if not apps:
            lay.addWidget(label("Reading your apps...", "Muted"))
            lay.addStretch()
            return
        total = sum(self.sizes.values())
        lay.addWidget(label(f"{len(apps)} Store apps" + (f"  ·  {fmt_size(total)} on disk" if total else "  ·  measuring sizes...")
                            + (f"  ·  {len(self.desktop_apps)} desktop apps from the Store" if self.desktop_apps else ""), "Muted"))
        box = QVBoxLayout()
        box.setSpacing(8)
        lay.addLayout(box)
        desk_box = QVBoxLayout()
        lay.addLayout(desk_box)
        lay.addStretch()

        def fill():
            clear(box)
            self._reset_rows()
            q = flt.text().strip().lower()
            self.lib_filter_text = flt.text()
            self.lib_sort = sort.currentIndex()
            shown = [a for a in apps if not q or q in a.title.lower() or q in a.family.lower() or
                     (a.product and q in a.product.publisher.lower())]
            key = [lambda a: a.title.lower(), lambda a: (not a.update_available, a.title.lower()),
                   lambda a: ((a.product.publisher if a.product else "~").lower(), a.title.lower()),
                   lambda a: -self.sizes.get(a.family, 0)][sort.currentIndex()]
            self._rows_for(box, sorted(shown, key=key))
        flt.textChanged.connect(lambda _: fill())
        sort.currentIndexChanged.connect(lambda _: fill())
        fill()
        if self.desktop_apps:
            desk_box.addWidget(label("Desktop apps installed from the Store", "H2"))
            for d in self.desktop_apps.values():
                desk_box.addWidget(self._desktop_row(d))

    def export_apps(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export app list", str(DATA_DIR / "my-apps.json"), "JSON (*.json)")
        if not path:
            return
        data = {"apps": [{"family": a.family, "product_id": a.product.product_id, "title": a.title, "kind": "store"}
                         for a in self.engine.apps.values() if a.product],
                "desktop": [{"product_id": pid, "title": t.get("title", pid), "kind": "desktop"}
                            for pid, t in wpm.tracked().items()]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        self.statusBar().showMessage(f"Saved {len(data['apps']) + len(data['desktop'])} apps to {path}", 8000)

    def import_apps(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import app list", str(DATA_DIR), "JSON (*.json)")
        if not path:
            return
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "My Store", f"Couldn't read that file: {e}")
            return
        missing = [w for w in data.get("apps", []) if w.get("family") not in self.engine.apps and w.get("product_id")]
        desk = [w for w in data.get("desktop", []) if w["product_id"] not in self.desktop_apps]
        if not missing and not desk:
            QMessageBox.information(self, "My Store", "Everything in that list is already installed.")
            return
        if QMessageBox.question(self, "My Store", f"Install {len(missing)} Store app(s) and {len(desk)} desktop app(s) "
                                "that aren't on this PC?\n\n" + "\n".join(w["title"] for w in (missing + desk)[:25])) != QMessageBox.Yes:
            return

        def add():
            out = []
            for w in missing:
                try:
                    out.append(("store", self.engine.app_for_product(self.engine.catalog.product(w["product_id"]))))
                except Exception:
                    pass
            for w in desk:
                try:
                    out.append(("desktop", wpm.resolve(self.browse, w["product_id"], self.engine.catalog.market)))
                except Exception:
                    pass
            return out

        def done(res, err):
            for kind, obj in res or []:
                if kind == "store":
                    self.queue.add_store(obj)
                else:
                    self.queue.add_desktop(obj)
            self.show_page("downloads")
        self.jobs.run(add, done)

    # ------------------------------------------------------------------ downloads queue
    def render_downloads(self):
        _, lay = self.pages["downloads"]
        clear(lay)
        self._reset_rows()
        self.queue_rows = {}
        head = QHBoxLayout()
        head.addWidget(label("Downloads", "H1"))
        head.addStretch()
        pa = button("Resume all" if self.queue.paused_all else "Pause all", icon="" if self.queue.paused_all else "")
        pa.clicked.connect(lambda: (self.queue.resume_all() if self.queue.paused_all else self.queue.pause_all(), self.render_downloads()))
        cf = button("Clear finished")
        cf.clicked.connect(lambda: (self.queue.clear_finished(), self.render_downloads()))
        par = QComboBox()
        par.addItems(["1 at a time", "2 at a time", "3 at a time", "4 at a time"])
        par.setCurrentIndex(max(0, min(3, int(self.settings.get("parallel_downloads", 2)) - 1)))
        par.setToolTip("How many downloads run at once. Installs always go one at a time - that is what stops jams.")
        par.currentIndexChanged.connect(lambda i: self._set("parallel_downloads", i + 1))
        spd = QComboBox()
        spd.addItems(["No speed limit", "2 MB/s", "5 MB/s", "10 MB/s", "20 MB/s"])
        cur = self.settings.get("speed_limit_mbps", 0)
        spd.setCurrentIndex({0: 0, 2: 1, 5: 2, 10: 3, 20: 4}.get(int(cur), 0))
        spd.currentIndexChanged.connect(lambda i: (self._set("speed_limit_mbps", [0, 2, 5, 10, 20][i]),
                                                   self.queue.set_speed_limit([0, 2, 5, 10, 20][i])))
        for w_ in (par, spd, pa, cf):
            head.addWidget(w_)
        lay.addLayout(head)
        items = self.queue.items
        live = [i for i in items if i.state not in ("done", "failed", "cancelled", "skipped")]
        fin = sorted([i for i in items if i.state in ("done", "failed", "cancelled", "skipped")], key=lambda i: -i.finished)
        lay.addWidget(label(f"Queue ({len(live)})", "H2"))
        if not live:
            lay.addWidget(label("Nothing queued. Updates and installs you start appear here - pause, reorder or cancel them.", "Muted"))
        for it in live:
            r = QueueRow(self, it)
            self.queue_rows[it.id] = r
            lay.addWidget(r)
        if fin:
            lay.addWidget(label("Finished", "H2"))
            for it in fin[:30]:
                r = QueueRow(self, it)
                self.queue_rows[it.id] = r
                lay.addWidget(r)
        lay.addStretch()

    # ------------------------------------------------------------------ wishlist
    def toggle_wish(self, pid, title, product=None):
        wl = self.settings.setdefault("wishlist", [])
        hit = next((w for w in wl if w["product_id"] == pid), None)
        if hit:
            wl.remove(hit)
        else:
            wl.append({"product_id": pid, "title": title, "icon_url": product.icon_url if product else None,
                       "tile_color": product.tile_color if product else None,
                       "price_text": ("Free" if product.is_free else f"{product.price:.2f}") if product else ""})
        settings_mod.save(self.settings)

    def render_wishlist(self):
        _, lay = self.pages["wishlist"]
        clear(lay)
        lay.addWidget(label("Wishlist", "H1"))
        wl = self.settings.get("wishlist") or []
        if not wl:
            lay.addWidget(label("Nothing here yet - open any app and press ☆ Wishlist.", "Muted"))
        grid = Grid()
        for w in wl:
            grid.add(StoreTile(self, Card(w["product_id"], w["title"], icon_url=w.get("icon_url"),
                                          tile_color=w.get("tile_color"), price_text=w.get("price_text", ""))))
        lay.addWidget(grid)
        lay.addStretch()

    # ------------------------------------------------------------------ health + clean-up
    def render_health(self):
        _, lay = self.pages["health"]
        clear(lay)
        self._reset_rows()
        head = QHBoxLayout()
        head.addWidget(label("Health & clean-up", "H1"))
        head.addStretch()
        rb = button("Re-check", icon="refresh")
        rb.clicked.connect(self.check_health)
        head.addWidget(rb)
        lay.addLayout(head)
        h = self.health
        if not h:
            lay.addWidget(label("Checking...", "Muted"))
        else:
            card = QFrame()
            card.setObjectName("Card")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(22, 18, 22, 18)
            ok = not h["stuck"]
            ic = label()
            ic.setPixmap(K.glyph_icon("check" if ok else "warning", K.GOOD if ok else K.BAD, 40).pixmap(40, 40))
            cl.addWidget(ic)
            txt = QVBoxLayout()
            txt.addWidget(label("Windows' app installer is working" if ok else
                                f"Windows' app installer is jammed - {len(h['stuck'])} stuck job(s)", "H2"))
            txt.addWidget(label("No job has been stuck for more than 10 minutes." if ok else
                                "These jobs started and never finished. Everything else queues behind them, and Windows "
                                "reloads them at every boot - so restarting does not fix it. Unjam clears them.", "Muted", wrap=True))
            cl.addLayout(txt, 1)
            ub = button("Unjam everything", accent=not ok, icon="unjam", tip="One admin prompt: cancels the Store queue, "
                        "ends hung install services, clears saved stuck jobs (as SYSTEM), restarts the services")
            ub.clicked.connect(lambda: self.jobs.unjam(None))
            cl.addWidget(ub)
            lay.addWidget(card)
            for j in h["stuck"]:
                lay.addWidget(label(f"  {j.operation:10}  {j.package}   -  stuck {j.minutes:.0f} min (since {j.started:%d %b %H:%M})", "Muted"))
            q = h["store_queue"]
            lay.addWidget(label("Microsoft Store queue", "H2"))
            if q:
                for i in q:
                    row = QHBoxLayout()
                    row.addWidget(label(f"  {i.family.split('_')[0]}  ·  {i.state}  {i.percent:.0f}%  {i.error}", "Muted"))
                    row.addStretch()
                    b = button("Cancel")
                    b.clicked.connect(lambda _, f=i.family: (storequeue.cancel(f), self.check_health()))
                    row.addWidget(b)
                    lay.addLayout(row)
            else:
                lay.addWidget(label("  Empty - nothing waiting in the Store.", "Muted"))
            lay.addWidget(label("  Services: " + "    ".join(f"{k}: {v}" for k, v in h["services"].items()), "Muted"))
        self._toggle(lay, "auto_unjam", "Fix jams automatically",
                     "When a jam is seen, cancel the Store's stuck items straight away (no prompt). If it's still stuck, "
                     "you get a notification with a one-click Unjam.")
        lay.addWidget(label("Stop the Microsoft Store fighting My Store", "H2"))
        off = admin.store_auto_updates_off()
        row = QHBoxLayout()
        row.addWidget(label("Microsoft Store automatic updates are " + ("OFF - My Store handles updates."
                            if off else "ON - the Store can start its own jobs for the same apps and jam them."), "Muted", wrap=True), 1)
        tb = button("Turn Store auto-updates back on" if off else "Turn Store auto-updates off")
        tb.clicked.connect(lambda: self.jobs.run(lambda: admin.store_auto_updates(off), lambda r, e: self.render_health()))
        row.addWidget(tb)
        lay.addLayout(row)

        lay.addWidget(label("Clean-up", "H2"))
        cbox = QVBoxLayout()
        lay.addLayout(cbox)
        cbox.addWidget(label("Measuring...", "Muted"))
        lay.addStretch()

        def got(c, err):
            clear(cbox)
            if err or c is None:
                return
            for key, text in (("downloads", "Download cache (leftover / paused downloads)"), ("rollback", "Saved previous versions (roll back)"),
                              ("images", "Store pictures cache")):
                r = QHBoxLayout()
                r.addWidget(label(f"  {text}:  {fmt_size(c[key])}", "Muted"), 1)
                b = button("Clear")
                b.setEnabled(c[key] > 0)
                b.clicked.connect(lambda _, k=key: self.jobs.run(lambda: cleanup.clear_cache(k), lambda f, e: (
                    self.statusBar().showMessage(f"Freed {fmt_size(f or 0)}", 6000), self.render_health())))
                r.addWidget(b)
                cbox.addLayout(r)
            r = QHBoxLayout()
            r.addWidget(label("  Old app versions Windows failed to delete (WindowsApps\\Deleted) - needs one admin prompt", "Muted"), 1)
            b = button("Clean up")
            b.clicked.connect(lambda: self.jobs.run(cleanup.windows_leftovers, lambda res, e: (
                QMessageBox.information(self, "My Store", f"Freed {fmt_size((res or {}).get('freed', 0))} "
                                        f"({fmt_size((res or {}).get('left', 0))} still in use)" if res and res.get("ok")
                                        else f"Clean-up didn't finish: {e or (res or {}).get('errors')}"), self.render_health())))
            r.addWidget(b)
            cbox.addLayout(r)
        self.jobs.run(cleanup.caches, got)

    # ------------------------------------------------------------------ settings
    def _set(self, key, value):
        self.settings[key] = value
        settings_mod.save(self.settings)

    def _toggle(self, lay, key, text, hint, after=None):
        cb = QCheckBox(text)
        cb.setChecked(bool(self.settings.get(key)))

        def changed(v):
            self._set(key, bool(v))
            if after:
                after()
        cb.toggled.connect(changed)
        lay.addWidget(cb)
        lay.addWidget(label("      " + hint, "Muted", wrap=True))
        return cb

    def render_settings(self):
        _, lay = self.pages["settings"]
        clear(lay)
        lay.addWidget(label("Settings", "H1"))
        s = self.settings

        lay.addWidget(label("Background updates", "H2"))
        bg = QVBoxLayout()
        lay.addLayout(bg)
        bg.addWidget(label("Checking...", "Muted"))

        def got(st, err):
            clear(bg)
            st = st or {}
            on = st.get("registered")
            row = QHBoxLayout()
            row.addWidget(label(("ON - runs at sign-in and every 6 hours, even when My Store is closed."
                                 if on else "OFF - updates only happen while My Store is open."), wrap=True), 1)
            b = button("Turn off" if on else "Turn on", accent=not on)
            b.clicked.connect(lambda: self.jobs.run(background.unregister if on else background.register,
                                                    lambda r, e: self.render_settings()))
            row.addWidget(b)
            bg.addLayout(row)
            run = st.get("run") or {}
            if run:
                when = datetime.fromtimestamp(run.get("started", 0)).strftime("%d %b %H:%M")
                summary = f"Last run {when}: updated {len(run.get('updated', [])) + len(run.get('desktop', []))}, " \
                          f"failed {len(run.get('failed', []))}, skipped (open) {len(run.get('skipped_open', []))}" + \
                          (f", needs admin {len(run.get('needs_admin', []))}" if run.get("needs_admin") else "")
                bg.addWidget(label("      " + summary, "Muted"))
            if on and st.get("next"):
                bg.addWidget(label(f"      Next run: {st['next']}", "Muted"))
            mode = QComboBox()
            mode.addItems(["Only apps I tick (⋯ > Update automatically)", "All apps"])
            mode.setCurrentIndex(1 if s.get("background_mode") == "all" else 0)
            mode.currentIndexChanged.connect(lambda i: self._set("background_mode", "all" if i else "ticked"))
            r2 = QHBoxLayout()
            r2.addWidget(label("      What to update:", "Muted"))
            r2.addWidget(mode)
            r2.addStretch()
            bg.addLayout(r2)
            bg.addWidget(label("      Runs as you (no admin). Apps that are open are skipped. Updates that need admin "
                               "(e.g. Codex's service) wait for you to open My Store.", "Muted", wrap=True))
        self.jobs.run(background.status, got)
        self._toggle(lay, "background_desktop", "Also update desktop apps installed from the Store",
                     "Discord, Teams and the like - using the Store's own installer recipe (SHA-256 checked).")

        lay.addWidget(label("Updating", "H2"))
        self._toggle(lay, "check_on_start", "Check for updates when My Store opens", "Asks Microsoft for new versions of every app (~10 s).")
        self._toggle(lay, "close_apps", "Close apps automatically to update them", "Otherwise you're asked when an app is open.")
        self._toggle(lay, "keep_rollback", "Keep the previous version so I can roll back",
                     "Saves each installed package (uses disk space - Codex is ~900 MB).",
                     lambda: setattr(self.engine, "keep_rollback", s["keep_rollback"]))
        self._toggle(lay, "pause_on_metered", "Wait for an unmetered connection",
                     "Downloads pause on metered or capped connections (phone hotspot) and carry on later.")
        self._toggle(lay, "notify", "Notifications", "Tell me when updates finish, fail, or the installer jams.")
        self._toggle(lay, "watchdog", "Watch for installer jams", "Checks every 5 minutes.")

        holds = s.get("holds") or {}
        lay.addWidget(label("Held-back apps", "H2"))
        if not holds:
            lay.addWidget(label("None. Use ⋯ > Hold on any app to stop it updating, or to skip one bad version.", "Muted"))
        for fam, what in list(holds.items()):
            a = self.engine.apps.get(fam)
            r = QHBoxLayout()
            r.addWidget(label(f"  {a.title if a else fam}  -  " + ("never update" if what == "all" else f"skip version {what}"), "Muted"), 1)
            b = button("Release")
            b.clicked.connect(lambda _, f=fam: self.set_hold(f, None))
            r.addWidget(b)
            lay.addLayout(r)

        lay.addWidget(label("Region", "H2"))
        mk = QComboBox()
        mk.addItems(["GB", "US", "IE", "AU", "CA", "DE", "FR"])
        mk.setCurrentText(s["market"])
        mk.currentTextChanged.connect(lambda v: self._set("market", v))
        mk.setFixedWidth(120)
        lay.addWidget(mk)
        if FROZEN:
            lay.addWidget(label("Store links", "H2"))
            r = QHBoxLayout()
            r.addWidget(label("Links to the Microsoft Store (on websites, in Settings, in other apps) open in "
                              + ("My Store." if store_links_ours() else "the Microsoft Store. Pick My Store for "
                                 "'ms-windows-store' to open them here instead."), "Muted", wrap=True), 1)
            b = button("Choose in Windows Settings...")
            b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("ms-settings:defaultapps?registeredAppMachine=My%20Store")))
            r.addWidget(b)
            lay.addLayout(r)
        lay.addWidget(label("Files", "H2"))
        b = button("Open My Store's data folder (logs, history, cache)")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR))))
        lay.addWidget(b, 0, Qt.AlignLeft)
        lay.addWidget(label("About", "H2"))
        bad = admin.untrusted_code()
        lay.addWidget(label(f"My Store {__version__}  ·  Python {sys.version.split()[0]}  ·  PySide6 {PySide6.__version__}\n"
                            f"Installed in {ROOT}\n"
                            + ("Admin actions: ready (only admins can change these files)." if not bad else
                               "Admin actions: off - this copy can be changed without admin rights. Use the installed My Store.")
                            + "\nUses Microsoft's own Store catalogue and delivery servers; not affiliated with Microsoft.",
                            "Muted", wrap=True))
        lay.addStretch()
