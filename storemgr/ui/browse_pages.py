"""Home, search, categories, charts and the app page."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from .. import engine as engine_mod
from .. import ui_kit as K
from .. import winapps, wpm
from ..browse import CATEGORIES, CHARTS, Card
from .widgets import AppIcon, Grid, Shelf, StoreTile, button, clear, fmt_size, label, stars


class BrowsePages:
    # ------------------------------------------------------------------ home
    def render_home(self):
        _, lay = self.pages["home"]
        clear(lay)
        self._reset_rows()
        apps = list(self.engine.apps.values())
        ups = [a for a in apps if a.update_available]
        hero = QFrame()
        hero.setObjectName("Hero")
        hero.setMinimumHeight(150)
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(30, 22, 30, 22)
        left = QVBoxLayout()
        hour = datetime.now().hour
        left.addWidget(label(("Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening") + self.greeting_name(), "H1"))
        bits = [f"{len(apps)} Store apps"] if apps else ["Reading your apps..."]
        if apps:
            bits.append(f"{len(ups)} update(s)" if ups else "all up to date")
        h = self.health
        if h:
            bits.append("⚠ installer jammed" if h["stuck"] else "installer healthy")
        pend = len(self.queue.pending())
        if pend:
            bits.append(f"{pend} in Downloads")
        left.addWidget(label("   ·   ".join(bits), "Muted"))
        left.addStretch()
        btns = QHBoxLayout()
        ua = button(f"Update all ({len(ups)})", accent=True, icon="download")
        ua.setEnabled(bool(ups))
        ua.clicked.connect(self.update_all)
        btns.addWidget(ua)
        for text, page in (("Downloads", "downloads"), ("Library", "library"), ("Health", "health")):
            b = button(text)
            b.clicked.connect(lambda _, p=page: self.show_page(p))
            btns.addWidget(b)
        btns.addStretch()
        left.addLayout(btns)
        hl.addLayout(left, 1)
        lay.addWidget(hero)
        if h and h["stuck"]:
            warn = QFrame()
            warn.setObjectName("Card")
            warn.setStyleSheet("QFrame#Card{background:#3b2427;border:1px solid #6b3a40}")
            wl = QHBoxLayout(warn)
            wl.addWidget(label(f"⚠  Windows' app installer is jammed - {len(h['stuck'])} job(s) stuck."))
            wl.addStretch()
            b = button("Unjam now", accent=True, icon="unjam")
            b.clicked.connect(lambda: self.jobs.unjam(None))
            wl.addWidget(b)
            lay.addWidget(warn)
        lay.addWidget(self._category_chips())
        if ups:
            sh = Shelf(self, f"Updates for your apps ({len(ups)})", lambda: self.show_page("updates"))
            sh.fill([self._card_for_app(a) for a in sorted(ups, key=lambda a: -a.latest.size)[:12]])
            lay.addWidget(sh)
        wl = self.settings.get("wishlist") or []
        if wl:
            sh = Shelf(self, "Your wishlist", lambda: self.show_page("wishlist"))
            sh.fill([Card(w["product_id"], w["title"], icon_url=w.get("icon_url"), tile_color=w.get("tile_color"),
                          price_text=w.get("price_text", "")) for w in wl])
            lay.addWidget(sh)
        for key in ("top_free_apps", "top_free_games", "trending_apps", "best_games", "top_paid_apps"):
            sh = Shelf(self, CHARTS[key][2], lambda k=key: self.open_chart(k))
            lay.addWidget(sh)
            self.jobs.run(lambda k=key: self.browse.chart(k, size=16)[1],
                          lambda cards, err, sh=sh: sh.fail(err) if err else sh.fill(cards))
        lay.addStretch()

    def greeting_name(self) -> str:
        """', <first name>' from the Windows account (or settings 'display_name'), '' if unknown."""
        name = self.settings.get("display_name")
        if name is None:
            try:
                import ctypes
                buf, size = ctypes.create_unicode_buffer(256), ctypes.c_ulong(256)
                ctypes.windll.secur32.GetUserNameExW(3, buf, ctypes.byref(size))   # 3 = display name
                name = buf.value.split()[0] if buf.value.strip() else ""
            except (AttributeError, OSError, IndexError):
                name = ""
            if not name:
                import getpass
                name = getpass.getuser().split(".")[0].capitalize()
        return f", {name[:1].upper()}{name[1:]}" if name else ""

    def _card_for_app(self, a) -> Card:
        p = a.product
        return Card(p.product_id if p else a.family, a.title, p.publisher if p else "", p.icon_url if p else None,
                    p.tile_color if p else None, fmt_size(a.latest.size) if a.latest else "", 0,
                    p.rating if p else None, "", [p.category] if p and p.category else [], "WindowsUpdate", [a.family])

    def _category_chips(self) -> QWidget:
        w = QWidget()
        g = QHBoxLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(6)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFixedHeight(46)
        sa.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        row = QHBoxLayout(inner)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(6)
        for c in CATEGORIES:
            b = button(c.replace("&", "&&"))   # '&' marks a keyboard shortcut in Qt buttons
            b.setStyleSheet("QPushButton{border-radius:14px;padding:4px 14px}")
            b.clicked.connect(lambda _, c=c: self.open_category(c))
            row.addWidget(b)
        row.addStretch()
        sa.setWidget(inner)
        g.addWidget(sa)
        return w

    def card_state(self, card: Card) -> str:
        """'Update' / 'Installed' / '' for a Store tile, using what's on this PC."""
        for fam in card.families or []:
            a = self.engine.apps.get(fam)
            if a:
                return "Update" if a.update_available else "Installed"
        if card.installer == "WPM" and card.product_id in self.desktop_state:
            return self.desktop_state[card.product_id]
        return ""

    # ------------------------------------------------------------------ charts & categories
    def open_chart(self, key, category=None):
        self.chart_args = (key, category)
        self.show_page("chart")

    def render_chart(self):
        _, lay = self.pages["chart"]
        clear(lay)
        key, cat = getattr(self, "chart_args", ("top_free_apps", None))
        title = CHARTS[key][2] if not cat else f"{CHARTS[key][2]} - {cat}"
        lay.addWidget(label(title, "H1"))
        grid = Grid()
        holder = QVBoxLayout()
        holder.addWidget(label("Loading...", "Muted"))
        lay.addLayout(holder)
        lay.addWidget(grid)
        lay.addStretch()

        def done(res, err):
            clear(holder)
            if err:
                holder.addWidget(label(f"Couldn't load: {err}", "Muted"))
                return
            t, cards = res
            for i, c in enumerate(cards, 1):
                grid.add(StoreTile(self, c))
        self.jobs.run(lambda: self.browse.chart(key, cat, size=60), done)

    def open_category(self, cat):
        self.category = cat
        self.show_page("category")

    def render_category(self):
        _, lay = self.pages["category"]
        clear(lay)
        cat = getattr(self, "category", CATEGORIES[0])
        lay.addWidget(label(cat, "H1"))
        lay.addWidget(self._category_chips())
        for key in ("top_free_apps", "top_paid_apps", "trending_apps"):
            sh = Shelf(self, f"{CHARTS[key][2]}", lambda k=key: self.open_chart(k, cat))
            lay.addWidget(sh)
            self.jobs.run(lambda k=key: self.browse.chart(k, cat, size=20)[1],
                          lambda cards, err, sh=sh: sh.fail(err) if err else sh.fill(cards))
        lay.addStretch()

    # ------------------------------------------------------------------ search
    def render_search(self):
        _, lay = self.pages["search"]
        clear(lay)
        self._reset_rows()
        q = getattr(self, "search_query", "")
        lay.addWidget(label(f"Results for “{q}”", "H1"))
        mine = [a for a in self.engine.apps.values() if q.lower() in a.title.lower()]
        if mine:
            lay.addWidget(label("On this PC", "H2"))
            self._rows_for(lay, mine[:5])
        filt = QHBoxLayout()
        dept = QComboBox()
        dept.addItems(["All", "Apps", "Games"])
        price = QComboBox()
        price.addItems(["Any price", "Free", "Paid"])
        sortb = QComboBox()
        sortb.addItems(["Best match", "Highest rated", "Name"])
        dept.setCurrentIndex(getattr(self, "s_dept", 0))
        price.setCurrentIndex(getattr(self, "s_price", 0))
        sortb.setCurrentIndex(getattr(self, "s_sort", 0))
        for w_ in (label("Microsoft Store", "H2"), dept, price, sortb):
            filt.addWidget(w_)
        filt.addStretch()
        lay.addLayout(filt)
        grid = Grid()
        status = label("Searching...", "Muted")
        more = button("Load more results")
        more.setVisible(False)
        lay.addWidget(grid)
        lay.addWidget(status)
        lay.addWidget(more, 0, Qt.AlignHCenter)
        lay.addStretch()
        st = {"cursor": None, "cards": []}

        def show():
            clear(grid.flow)
            cards = list(st["cards"])
            if sortb.currentIndex() == 1:
                cards.sort(key=lambda c: -(c.rating or 0))
            elif sortb.currentIndex() == 2:
                cards.sort(key=lambda c: c.title.lower())
            for c in cards:
                grid.add(StoreTile(self, c))
            status.setText(f"{len(cards)} result(s)" if cards else "Nothing found")

        def got(res, err):
            if err:
                status.setText(f"Search failed: {err}")
                return
            cards, nxt = res
            have = {c.product_id for c in st["cards"]}
            st["cards"] += [c for c in cards if c.product_id not in have]
            st["cursor"] = nxt
            more.setVisible(bool(nxt))
            more.setEnabled(True)
            show()

        def load(cursor=None):
            media = ["all", "apps", "games"][dept.currentIndex()]
            pr = ["all", "Free", "Paid"][price.currentIndex()]
            self.jobs.run(lambda: self.browse.search(q, media, pr, cursor), got)

        def refilter():
            self.s_dept, self.s_price, self.s_sort = dept.currentIndex(), price.currentIndex(), sortb.currentIndex()
            st["cards"], st["cursor"] = [], None
            status.setText("Searching...")
            load()

        dept.currentIndexChanged.connect(lambda _: refilter())
        price.currentIndexChanged.connect(lambda _: refilter())
        sortb.currentIndexChanged.connect(lambda _: (setattr(self, "s_sort", sortb.currentIndex()), show()))
        more.clicked.connect(lambda: (more.setEnabled(False), load(st["cursor"])))
        load()

    # ------------------------------------------------------------------ app page
    def open_product(self, product_id, card: Card | None = None):
        self.statusBar().showMessage("Loading...")
        self.detail_card = card

        def load():
            try:
                p = self.engine.catalog.product(product_id)
            except Exception:       # desktop-installer apps aren't in Microsoft's catalogue
                p = self.browse.as_product(product_id)
                return ("desktop", p, wpm.resolve(self.browse, product_id, self.engine.catalog.market))
            kind = card.installer if card and card.installer else ""
            if not kind:
                try:
                    kind = self.browse.details(product_id).get("installer", "")
                except Exception:
                    kind = ""
            if kind == "WPM" or (not p.wu_category and not p.pfn):
                return ("desktop", p, wpm.resolve(self.browse, product_id, self.engine.catalog.market))
            a = self.engine.app_for_product(p)
            if not a.latest and not a.check_error:
                self.engine.check(a)
            return ("store", p, a)

        def done(res, err):
            if err:
                self.statusBar().showMessage(f"Could not load: {err}")
                return
            kind, p, obj = res
            self.statusBar().clearMessage()
            if kind == "store":
                self.open_app(obj)
            else:
                self.detail_desktop = (p, obj)
                self.detail_app = None
                self.show_page("app")
        self.jobs.run(load, done)

    def open_app(self, app):
        self.detail_app = app
        self.detail_desktop = None
        self.show_page("app")

    def render_app(self):
        _, lay = self.pages["app"]
        clear(lay)
        self._reset_rows()
        a = getattr(self, "detail_app", None)
        desk = getattr(self, "detail_desktop", None)
        if not a and not desk:
            return
        p = a.product if a else desk[0]
        d = desk[1] if desk else None
        title = a.title if a else (p.title if p else d.title)
        top = QHBoxLayout()
        top.setSpacing(24)
        ic = AppIcon(self, 120)
        ic.set_app(title, p.icon_url if p else None, a.entries[0].logo if a and a.entries else None, p.tile_color if p else None)
        top.addWidget(ic, 0, Qt.AlignTop)
        info = QVBoxLayout()
        info.addWidget(label(title, "H1"))
        info.addWidget(label(p.publisher if p else "", "Muted"))
        if p and p.rating:
            info.addWidget(label(f"{stars(p.rating, f'{p.rating_count:,} ratings')}   ·   {p.category or ''}"))
        price = ("Free" if p.is_free else f"{p.price:.2f} {p.currency}") if p else ""
        line = []
        if a:
            if a.installed:
                line.append(f"Installed {a.current_str}")
            if a.latest:
                line.append(f"Latest {a.latest.version_str} ({fmt_size(a.latest.size)})")
        else:
            line.append(f"Desktop installer  ·  version {d.version}")
            line.append(f"Installed {d.installed_version}" if d.installed_version else "Not installed")
        if price:
            line.append(price)
        info.addWidget(label("   ·   ".join(line), "Muted"))
        btns = QHBoxLayout()
        key = a.family if a else d.product_id
        qi = self.queue.find(key)
        if qi:
            b = button(f"In Downloads - {qi.msg[:40]}")
            b.clicked.connect(lambda: self.show_page("downloads"))
        elif a:
            if a.update_available:
                b = button("Update", accent=True, icon="download")
                b.clicked.connect(lambda: self.start_update(a))
            elif not a.installed:
                b = button("Get" if (not p or p.is_free) else f"Get ({price})", accent=True, icon="download")
                b.setEnabled(bool(a.latest) and (not p or p.is_free))
                if p and not p.is_free:
                    b.setToolTip("Paid apps need a licence from the Microsoft Store")
                b.clicked.connect(lambda: self.start_update(a))
            else:
                b = button("Open", accent=True, icon="open")
                b.setEnabled(bool(a.entries))
                b.clicked.connect(lambda: winapps.launch(a.family, a.entries[0].app_id))
        else:
            label_ = "Update" if d.update_available else ("Reinstall" if d.installed_version else "Get")
            b = button(label_, accent=not d.installed_version or d.update_available, icon="download")
            b.setEnabled(bool(d.installer) and (not p or p.is_free))
            b.clicked.connect(lambda: self.get_desktop(d, p))
        btns.addWidget(b)
        if a:
            unj = button("Unjam", icon="unjam", tip="Cancel the Store's stuck job for this app, clear stuck installer jobs, then update")
            unj.clicked.connect(lambda: self.jobs.unjam(a))
            btns.addWidget(unj)
        pid = p.product_id if p else (d.product_id if d else "")
        wished = any(w["product_id"] == pid for w in self.settings.get("wishlist", []))
        wb = button("★ On wishlist" if wished else "☆ Wishlist")
        wb.clicked.connect(lambda: (self.toggle_wish(pid, title, p), self.render_app()))
        btns.addWidget(wb)
        if a:
            more = button("", icon="more")
            more.clicked.connect(lambda: self.app_menu(a, more.mapToGlobal(more.rect().bottomLeft())))
            btns.addWidget(more)
        btns.addStretch()
        info.addLayout(btns)
        job = self.jobs.active.get(key)
        self.detail_status = label(job["msg"] if job else (a.check_error if a and a.check_error and p else (d.error if d else "")), "Muted")
        info.addWidget(self.detail_status)
        top.addLayout(info, 1)
        lay.addLayout(top)

        # what's new + facts (filled from the Store's app page)
        facts = QVBoxLayout()
        lay.addLayout(facts)
        facts.addWidget(label("Loading details...", "Muted"))
        shots_box = QVBoxLayout()
        lay.addLayout(shots_box)
        if p and p.screenshots:
            shots_box.addWidget(label("Screenshots", "H2"))
            sa = QScrollArea()
            sa.setFixedHeight(230)
            sa.setWidgetResizable(True)
            sa.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            strip = QWidget()
            sl = QHBoxLayout(strip)
            sl.setContentsMargins(0, 0, 0, 0)
            for url in p.screenshots:
                shot = QLabel()
                shot.setFixedSize(360, 210)
                shot.setStyleSheet("background:#1f1f1f;border-radius:8px")
                shot.setAlignment(Qt.AlignCenter)
                path = self.images.get(url)

                def put(path, shot=shot):
                    try:
                        shot.setPixmap(QPixmap(path).scaled(360, 210, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    except RuntimeError:
                        pass
                if path:
                    put(path)
                else:
                    self.images.loaded.connect(lambda u, pth, url=url, put=put: put(pth) if u == url else None)
                sl.addWidget(shot)
            sl.addStretch()
            sa.setWidget(strip)
            shots_box.addWidget(sa)
        desc = (p.description or p.short_description) if p else ""
        if desc:
            lay.addWidget(label("Description", "H2"))
            dl = label(desc[:3500], wrap=True)
            dl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(dl)
        reviews_box = QVBoxLayout()
        lay.addLayout(reviews_box)
        lay.addStretch()

        fam = a.family if a else None

        def got_details(det, err):
            clear(facts)
            if err or not det:
                facts.addWidget(label("", "Muted"))
                return
            facts.addWidget(label("What's new", "H2"))
            lines = []
            if det.get("updated"):
                lines.append(f"Last updated by the publisher: {det['updated']:%d %b %Y}")
            if a and a.update_available:
                lines.append(f"New version {a.latest.version_str} (you have {a.current_str}) - {fmt_size(a.latest.size)} download")
            hist = engine_mod.changelog(fam) if fam else []
            for h in reversed(hist[-5:]):
                lines.append(f"{datetime.fromtimestamp(h['t']):%d %b %Y %H:%M}  -  Unjammed updated it {h['from'] or 'new'} → {h['to']}")
            if not lines:
                lines.append("Microsoft doesn't publish release notes for this app.")
            facts.addWidget(label("\n".join(lines), "Muted", wrap=True))
            links = QHBoxLayout()
            for text, url in (("Publisher website", det.get("website")), ("Support", det.get("support")),
                              ("Privacy policy", det.get("privacy"))):
                if url and QUrl(url).scheme().lower() in ("http", "https"):   # publisher-supplied: web links only
                    lb = button(text, flat=True)
                    lb.setStyleSheet(f"color:{K.ACCENT}")
                    lb.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
                    links.addWidget(lb)
            links.addStretch()
            facts.addLayout(links)
            facts.addWidget(label("Details", "H2"))
            rows = []
            if det.get("age"):
                rows.append(("Age rating", det["age"]))
            if det.get("size"):
                rows.append(("Approximate size", fmt_size(det["size"])))
            if det.get("released"):
                rows.append(("Released", f"{det['released']:%d %b %Y}"))
            rows.append(("Installs as", "Desktop installer (Store recipe, SHA-256 checked)" if det.get("installer") == "WPM"
                         else "Store package (Microsoft signed, hash checked)"))
            for lvl, n, v in det.get("requirements", [])[:8]:
                rows.append((f"{lvl}: {n}", v))
            if fam:
                rows.append(("Package family", fam))
                if a.installed:
                    rows.append(("Installed at", a.installed.location))
            facts.addWidget(label("\n".join(f"{k}:   {v}" for k, v in rows), "Muted", wrap=True))

        def got_reviews(res, err):
            clear(reviews_box)
            if err or not res or not res[0]:
                return
            revs, token = res
            reviews_box.addWidget(label("Ratings and reviews", "H2"))
            for r in revs[:8]:
                card = QFrame()
                card.setObjectName("Card")
                cl = QVBoxLayout(card)
                cl.setContentsMargins(14, 10, 14, 10)
                cl.addWidget(label(f"{'★' * int(r['rating'])}{'☆' * (5 - int(r['rating']))}   {r['title']}   ·   {r['date']}"))
                cl.addWidget(label(r["text"][:600], "Muted", wrap=True))
                reviews_box.addWidget(card)

        if pid:
            self.jobs.run(lambda: self.browse.details(pid), got_details)
            self.jobs.run(lambda: self.browse.reviews(pid), got_reviews)

    def get_desktop(self, d: wpm.DesktopApp, p):
        terms = "\n".join(f"• {lbl}: {(txt or url)[:200]}" for lbl, txt, url in d.agreements if lbl) or "None listed."
        inst = d.installer
        note = "" if inst and inst.silent else "\n\nThis installer has no silent mode - its own window will appear."
        msg = (f"Install {d.title} {d.version}?\n\nThis app uses a desktop installer. Unjammed downloads it from the "
               f"address in the Store's recipe and only runs it if its SHA-256 matches.{note}\n\nPublisher terms:\n{terms}")
        if QMessageBox.question(self, "Unjammed", msg) == QMessageBox.Yes:
            self.queue.add_desktop(d, p.icon_url if p else None)
            self.statusBar().showMessage(f"{d.title} added to Downloads", 6000)
            self.render_current()
