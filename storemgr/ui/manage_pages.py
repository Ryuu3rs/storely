"""Updates, Library, Downloads queue, Wishlist, Health (+ clean-up) and Settings."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QMessageBox,
                               QVBoxLayout)

import sys

import PySide6

from ..winsys import store_links_ours
from .. import DATA_DIR, FROZEN, ROOT, __version__, admin, background, cleanup, debloat, diag, settings as settings_mod, storequeue, volumes, wpm
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
        if self.framework_ups:
            fh = QHBoxLayout()
            fh.addWidget(label(f"Windows runtimes ({len(self.framework_ups)})", "H2"))
            fh.addStretch()
            lay.addLayout(fh)
            lay.addWidget(label("Shared parts that Store apps run on (Visual C++ runtime, UI libraries, .NET Native...). "
                                "Updating them is safe: apps keep working, and Windows tidies up old versions.", "Muted", wrap=True))
            for have, pkg in self.framework_ups:
                lay.addWidget(self._simple_row(have.name, f"{have.arch}  ·  Version {have.version}  →  {pkg.version_str}  ·  "
                                               f"{fmt_size(pkg.size)}", f"{have.name}|{have.arch}",
                                               lambda h=have, p=pkg: self.queue.add_framework(h, p)))
        if self.settings.get("winget", True):
            others = self.winget_ups
            wh = QHBoxLayout()
            wh.addWidget(label(f"Other apps ({len(others)})" if others else "Other apps", "H2"))
            wh.addStretch()
            if others:
                wa = button("Update all other apps", icon="download")
                wa.clicked.connect(lambda: ([self.queue.add_winget(u) for u in others], self.show_page("downloads")))
                wh.addWidget(wa)
            lay.addLayout(wh)
            note = {"missing": "winget (Microsoft's App Installer) isn't on this PC - get 'App Installer' from the Store "
                               "to update your other programs here too.",
                    "": "Checking your other programs (Chrome, 7-Zip, Steam...) with winget..."}.get(self.winget_state, "")
            if self.winget_state.startswith("error"):
                note = f"winget couldn't check: {self.winget_state[7:]}"
            if not others and self.winget_state == "ok":
                note = "Your other programs are up to date."
            if note:
                lay.addWidget(label(note, "Muted", wrap=True))
            for u in others:
                lay.addWidget(self._simple_row(u.name, f"Version {u.version}  →  {u.available}  ·  {u.id}  ·  winget",
                                               u.id, lambda u=u: self.queue.add_winget(u)))
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

    def _simple_row(self, title: str, sub: str, key: str, add) -> QFrame:
        row = QFrame()
        row.setObjectName("Card")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(14, 10, 14, 10)
        ic = AppIcon(self, 40)
        ic.set_app(title)
        rl.addWidget(ic)
        mid = QVBoxLayout()
        mid.addWidget(label(title))
        mid.addWidget(label(sub, "Muted"))
        rl.addLayout(mid, 1)
        qi = self.queue.find(key)
        b = button(qi.msg[:30] if qi else "Update", accent=not qi)
        b.clicked.connect(lambda: self.show_page("downloads") if self.queue.find(key) else
                          (add(), self.refresh_badges(), self.render_updates()))
        rl.addWidget(b)
        return row

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
        off = button("Install from folder", tip="Install an offline copy saved with ⋯ > Save offline copy (no internet needed)")
        off.clicked.connect(self.install_from_folder)
        for w_ in (flt, sort, exp, imp, off):
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

    def install_from_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder with an offline copy (app + frameworks)")
        if not folder:
            return
        self.statusBar().showMessage("Checking signatures and installing...")
        self.jobs.run(lambda: self.engine.install_folder(Path(folder)), lambda res, e: (
            QMessageBox.information(self, "Unjammed", "Installed:\n" + "\n".join(res)) if res else
            QMessageBox.warning(self, "Unjammed", f"Nothing was installed: {e}"), self.rescan()))

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
            QMessageBox.warning(self, "Unjammed", f"Couldn't read that file: {e}")
            return
        missing = [w for w in data.get("apps", []) if w.get("family") not in self.engine.apps and w.get("product_id")]
        desk = [w for w in data.get("desktop", []) if w["product_id"] not in self.desktop_apps]
        if not missing and not desk:
            QMessageBox.information(self, "Unjammed", "Everything in that list is already installed.")
            return
        if QMessageBox.question(self, "Unjammed", f"Install {len(missing)} Store app(s) and {len(desk)} desktop app(s) "
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
        lay.addWidget(label("Stop the Microsoft Store fighting Unjammed", "H2"))
        off = admin.store_auto_updates_off()
        row = QHBoxLayout()
        row.addWidget(label("Microsoft Store automatic updates are " + ("OFF - Unjammed handles updates."
                            if off else "ON - the Store can start its own jobs for the same apps and jam them."), "Muted", wrap=True), 1)
        tb = button("Turn Store auto-updates back on" if off else "Turn Store auto-updates off")
        tb.clicked.connect(lambda: self.jobs.run(lambda: admin.store_auto_updates(off), lambda r, e: self.render_health()))
        row.addWidget(tb)
        lay.addLayout(row)

        lay.addWidget(label("Microsoft's services", "H2"))
        st = QVBoxLayout()
        lay.addLayout(st)
        sr = QHBoxLayout()
        sr.addWidget(label("Unjammed uses the Store's own (undocumented) services. If something stops working, this "
                           "shows whether Microsoft changed or blocked one of them.", "Muted", wrap=True), 1)
        tb2 = button("Test them")
        sr.addWidget(tb2)
        st.addLayout(sr)
        results = QVBoxLayout()
        st.addLayout(results)

        def tested(res, err):
            clear(results)
            for r in res or [{"name": "Test", "ok": False, "ms": 0, "detail": str(err)}]:
                results.addWidget(label(f"  {'✓' if r['ok'] else '✗'}  {r['name']}  -  "
                                        f"{'working' if r['ok'] else 'not working: ' + r['detail']} ({r['ms']} ms)", "Muted"))
        tb2.clicked.connect(lambda: (clear(results), results.addWidget(label("  Testing...", "Muted")),
                                     self.jobs.run(lambda: diag.selftest(self.engine.catalog.market), tested)))

        self._extras(lay)
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
                QMessageBox.information(self, "Unjammed", f"Freed {fmt_size((res or {}).get('freed', 0))} "
                                        f"({fmt_size((res or {}).get('left', 0))} still in use)" if res and res.get("ok")
                                        else f"Clean-up didn't finish: {e or (res or {}).get('errors')}"), self.render_health())))
            r.addWidget(b)
            cbox.addLayout(r)
        self.jobs.run(cleanup.caches, got)

    def _extras(self, lay):
        """Preinstalled apps people usually don't want, removable for you and put back any time."""
        lay.addWidget(label("Preinstalled extras", "H2"))
        found = debloat.installed_clutter(self.engine.all_installed)
        gone = debloat.removed()
        if not found and not gone:
            lay.addWidget(label("None of the usual preinstalled extras are on this PC.", "Muted"))
            return
        boxes = []
        if found:
            hr = QHBoxLayout()
            hr.addWidget(label(f"{len(found)} apps that came with Windows or were pushed onto it. Removing one only affects "
                               "your account, and you can put it back here any time. (New accounts still get them, and a "
                               "big Windows update can bring some back.)", "Muted", wrap=True), 1)
            show = button("Hide list" if getattr(self, "extras_open", False) else "Choose...")
            show.clicked.connect(lambda: (setattr(self, "extras_open", not getattr(self, "extras_open", False)),
                                          self.render_health()))
            hr.addWidget(show)
            lay.addLayout(hr)
            if not getattr(self, "extras_open", False):
                found = []
            for g in debloat.GROUPS:
                mine = [e for e in found if e.group == g]
                if not mine:
                    continue
                lay.addWidget(label(f"  {g}", "Muted"))
                for e in mine:
                    cb = QCheckBox(f"{e.title}  -  {e.description}")
                    boxes.append((cb, e))
                    lay.addWidget(cb)
        if boxes:
            rb = button("Remove selected", icon="delete")

            def remove():
                pick = [e for cb, e in boxes if cb.isChecked()]
                if not pick or QMessageBox.question(self, "Unjammed", f"Remove {len(pick)} app(s) for your account?\n\n"
                                                    + "\n".join(e.title for e in pick)) != QMessageBox.Yes:
                    return
                self.statusBar().showMessage(f"Removing {len(pick)} app(s)...")
                self.jobs.run(lambda: [(e.title, *debloat.remove(e, self.engine.all_installed)) for e in pick],
                              lambda res, err: (QMessageBox.information(self, "Unjammed", "\n".join(
                                  f"{t}: {'removed' if ok else msg}" for t, ok, msg in res or []) or str(err)), self.rescan()))
            rb.clicked.connect(remove)
            lay.addWidget(rb, 0, Qt.AlignLeft)
        if gone:
            lay.addWidget(label("  Removed by Unjammed - put back:", "Muted"))
            for r in gone:
                row = QHBoxLayout()
                row.addWidget(label(f"      {r['title']}", "Muted"), 1)
                pb = button("Put back")
                pb.clicked.connect(lambda _, r=r: self.jobs.run(
                    lambda: self.engine.app_for_product(self.engine.catalog.product(r["product_id"])),
                    lambda a, e: (self.queue.add_store(a), self.show_page("downloads")) if a else
                    QMessageBox.warning(self, "Unjammed", f"Couldn't find it in the Store: {e}")))
                fg = button("Forget", flat=True)
                fg.clicked.connect(lambda _, f=r["family"]: (debloat.forget(f), self.render_health()))
                row.addWidget(pb)
                row.addWidget(fg)
                lay.addLayout(row)

    def _drives(self, lay):
        lay.addWidget(label("Where apps install", "H2"))
        box = QVBoxLayout()
        lay.addLayout(box)
        box.addWidget(label("Reading drives...", "Muted"))

        def got(vols, err):
            clear(box)
            if err or not vols:
                box.addWidget(label(f"Couldn't read Windows' app drives: {err}", "Muted"))
                return
            pref = volumes.preferred(vols)
            usable = [v for v in vols if v.usable]
            for v in vols:
                state = ("Windows' default" if v.is_default else "") + (" · offline" if v.is_offline else "") + \
                        (" · stale record (another disk has this drive's ID - fix in Settings > Apps > Advanced app settings)"
                         if v.wrong_disk else "")
                free = f"{fmt_size(v.free)} free" if v.free is not None else ""
                box.addWidget(label(f"  {v.label}  {free}  {state}".rstrip(), "Muted"))
            row = QHBoxLayout()
            row.addWidget(label("Unjammed installs new apps to:"))
            dc = QComboBox()
            dc.addItems(["Windows' default"] + [f"{v.label} ({fmt_size(v.free)} free)" for v in usable])
            dc.setCurrentIndex(1 + usable.index(pref) if pref in usable else 0)

            def pick(i):
                volumes.set_preferred(usable[i - 1].path if i else None)
                self.engine.install_root = Path(usable[i - 1].path if i else os.environ.get("SystemDrive", "C:") + "\\")
            dc.currentIndexChanged.connect(pick)
            row.addWidget(dc)
            row.addStretch()
            box.addLayout(row)
            box.addWidget(label("Updates stay wherever the app already is. Big games are the usual reason to pick another "
                                "drive. To move an installed app: ⋯ > Move to another drive.", "Muted", wrap=True))
            others = [v for v in usable if not v.is_default and v.drive]
            if others:
                row2 = QHBoxLayout()
                mk = QComboBox()
                mk.addItems([v.label for v in others])
                b = button("Make it Windows' default for every app (admin)")
                b.clicked.connect(lambda: self.jobs.run(lambda: volumes.add_and_set_default(others[mk.currentIndex()].drive),
                                                        lambda r, e: (QMessageBox.information(self, "Unjammed", (r or (False, str(e)))[1]
                                                                      or "Done"), self.render_settings())))
                row2.addWidget(mk)
                row2.addWidget(b)
                row2.addStretch()
                box.addLayout(row2)
        self.jobs.run(volumes.volumes, got)

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
            row.addWidget(label(("ON - runs at sign-in and every 6 hours, even when Unjammed is closed."
                                 if on else "OFF - updates only happen while Unjammed is open."), wrap=True), 1)
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
                               "(e.g. Codex's service) wait for you to open Unjammed.", "Muted", wrap=True))
        self.jobs.run(background.status, got)
        self._toggle(lay, "background_desktop", "Also update desktop apps installed from the Store",
                     "Discord, Teams and the like - using the Store's own installer recipe (SHA-256 checked).")

        lay.addWidget(label("Updating", "H2"))
        self._toggle(lay, "check_on_start", "Check for updates when Unjammed opens", "Asks Microsoft for new versions of every app (~10 s).")
        self._toggle(lay, "close_apps", "Close apps automatically to update them", "Otherwise you're asked when an app is open.")
        self._toggle(lay, "keep_rollback", "Keep the previous version so I can roll back",
                     "Saves each installed package (uses disk space - Codex is ~900 MB).",
                     lambda: setattr(self.engine, "keep_rollback", s["keep_rollback"]))
        self._toggle(lay, "pause_on_metered", "Wait for an unmetered connection",
                     "Downloads pause on metered or capped connections (phone hotspot) and carry on later.")
        self._toggle(lay, "pause_on_battery", "Wait until the PC is plugged in",
                     "On a laptop running on battery, downloads and background updates wait for the charger.")
        self._toggle(lay, "ask_new_permissions", "Ask me before updates that add permissions",
                     "If a new version wants more access (camera, microphone, your files, full desktop access...), it "
                     "waits in Downloads for your OK. The Microsoft Store never tells you this.")
        self._toggle(lay, "winget", "Also update my other programs (winget)",
                     "Chrome, 7-Zip, Steam, Zoom... through winget, Microsoft's package manager. Installers that need admin "
                     "ask for it themselves.", lambda: setattr(self, "winget_ups", self.winget_ups if s["winget"] else []))
        self._toggle(lay, "notify", "Notifications", "Tell me when updates finish, fail, or the installer jams.")
        self._toggle(lay, "watchdog", "Watch for installer jams", "Checks every 5 minutes.")
        qh = QHBoxLayout()
        qon = QCheckBox("Quiet hours: no background installs or notifications from")
        hours = [f"{h:02d}:00" for h in range(24)]
        q = s.get("quiet_hours") or []
        qon.setChecked(len(q) == 2)
        qa, qb = QComboBox(), QComboBox()
        for c, v in ((qa, q[0] if len(q) == 2 else 23), (qb, q[1] if len(q) == 2 else 7)):
            c.addItems(hours)
            c.setCurrentIndex(int(v))

        def save_quiet(*_):
            self._set("quiet_hours", [qa.currentIndex(), qb.currentIndex()] if qon.isChecked() else [])
        for w_ in (qon, qa, label("to"), qb):
            qh.addWidget(w_)
        qh.addStretch()
        qon.toggled.connect(save_quiet)
        qa.currentIndexChanged.connect(save_quiet)
        qb.currentIndexChanged.connect(save_quiet)
        lay.addLayout(qh)

        self._drives(lay)
        lay.addWidget(label("Appearance", "H2"))
        th = QHBoxLayout()
        theme = QComboBox()
        theme.addItems(["Same as Windows", "Dark", "Light"])
        theme.setCurrentIndex({"system": 0, "dark": 1, "light": 2}.get(s.get("theme", "system"), 0))
        theme.currentIndexChanged.connect(lambda i: self._set("theme", ["system", "dark", "light"][i]))
        th.addWidget(theme)
        th.addWidget(label("  takes effect the next time Unjammed opens", "Muted"))
        th.addStretch()
        lay.addLayout(th)

        lay.addWidget(label("Unjammed updates", "H2"))
        ur = QHBoxLayout()
        rel = getattr(self, "self_update", None)
        ur.addWidget(label(f"Unjammed {rel.version} is available." if rel else
                           f"You have Unjammed {__version__}. New versions come from GitHub, checked against Unjammed's "
                           "own signature before they install.", "Muted", wrap=True), 1)
        if rel:
            gi = button("Install now", accent=True)
            gi.clicked.connect(self.install_self_update)
            sk = button("Skip this version")
            sk.clicked.connect(lambda: (self._set("skipped_update", rel.version), setattr(self, "self_update", None),
                                        self.render_settings()))
            ur.addWidget(gi)
            ur.addWidget(sk)
        else:
            cn = button("Check now")
            cn.clicked.connect(lambda: self.check_self_update(manual=True))
            ur.addWidget(cn)
        lay.addLayout(ur)
        upd = QCheckBox("Tell me when there's a new Unjammed")
        upd.setChecked(s.get("self_update", "notify") != "off")
        upd.toggled.connect(lambda v: self._set("self_update", "notify" if v else "off"))
        lay.addWidget(upd)

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
                              + ("Unjammed." if store_links_ours() else "the Microsoft Store. Pick Unjammed for "
                                 "'ms-windows-store' to open them here instead."), "Muted", wrap=True), 1)
            b = button("Choose in Windows Settings...")
            b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("ms-settings:defaultapps?registeredAppMachine=Unjammed")))
            r.addWidget(b)
            lay.addLayout(r)
        lay.addWidget(label("Files", "H2"))
        b = button("Open Unjammed's data folder (logs, history, cache)")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR))))
        lay.addWidget(b, 0, Qt.AlignLeft)
        lay.addWidget(label("About", "H2"))
        bad = admin.untrusted_code()
        lay.addWidget(label(f"Unjammed {__version__}  ·  Python {sys.version.split()[0]}  ·  PySide6 {PySide6.__version__}\n"
                            f"Installed in {ROOT}\n"
                            + ("Admin actions: ready (only admins can change these files)." if not bad else
                               "Admin actions: off - this copy can be changed without admin rights. Use the installed Unjammed.")
                            + "\nUses Microsoft's own Store catalogue and delivery servers; not affiliated with Microsoft.",
                            "Muted", wrap=True))
        lay.addStretch()
