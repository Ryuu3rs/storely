"""Reusable pieces: icons, store tiles, shelves, wrapping grid, star ratings, app rows, queue rows."""

from __future__ import annotations

import html
import os

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout, QProgressBar, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .. import ui_kit as K


def fmt_size(b) -> str:
    b = b or 0
    return f"{b / 1073741824:.1f} GB" if b >= 1073741824 else f"{b / 1048576:.0f} MB" if b >= 1048576 else f"{b / 1024:.0f} KB"


def label(text="", obj=None, wrap=False) -> QLabel:
    lb = QLabel(text)
    lb.setTextFormat(Qt.PlainText)      # Store text comes from publishers: never render it as HTML
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def button(text, accent=False, flat=False, icon=None, tip=None) -> QPushButton:
    b = QPushButton(text)
    if accent:
        b.setProperty("accent", True)
    if flat:
        b.setProperty("flat", True)
    if icon:
        b.setIcon(K.glyph_icon(icon, K.ACCENT_TEXT if accent else K.TEXT, 16))
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def set_accent(b: QPushButton, on: bool):
    b.setProperty("accent", on)
    b.style().unpolish(b)
    b.style().polish(b)


def clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w:
            w.hide()             # gone from the screen now, not when Qt gets round to deleting it
            w.setParent(None)
            w.deleteLater()
        elif it.layout():
            clear(it.layout())


def stars(rating, count="") -> str:
    if not rating:
        return ""
    return f"★ {rating:.1f}" + (f"  ({count})" if count else "")


class FlowLayout(QLayout):
    """Wraps tiles onto as many rows as the width allows (like the Store's grids)."""

    def __init__(self, parent=None, spacing=12):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self.items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line_h, sp = rect.x(), rect.y(), 0, self.spacing()
        for it in self.items:
            hint = it.sizeHint()
            nx = x + hint.width() + sp
            if nx - sp > rect.right() and line_h > 0:
                x, y = rect.x(), y + line_h + sp
                nx, line_h = x + hint.width() + sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x, line_h = nx, max(line_h, hint.height())
        return y + line_h - rect.y()


class AppIcon(QLabel):
    def __init__(self, win, size=40):
        super().__init__()
        self.win, self.sz, self.url, self.bg = win, size, None, None
        self.setFixedSize(size, size)
        win.images.loaded.connect(self._loaded)

    def set_app(self, title, url=None, local=None, bg=None):
        self.url, self.bg = url, bg
        path = self.win.images.get(url) if url else None
        if path:
            self.setPixmap(K.rounded(QPixmap(path), self.sz, max(6, self.sz // 8), bg))
        elif local and os.path.exists(local):
            self.setPixmap(K.rounded(QPixmap(local), self.sz, max(6, self.sz // 8), "#3a3a3a"))
        else:
            self.setPixmap(K.letter_tile(title, self.sz))

    def _loaded(self, url, path):
        if url == self.url:
            self.setPixmap(K.rounded(QPixmap(path), self.sz, max(6, self.sz // 8), self.bg))


class Clickable(QFrame):
    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class StoreTile(Clickable):
    """A Store product tile: icon, name, rating, price - plus Installed / Update badge for apps on this PC."""

    def __init__(self, win, card, w=168, h=228):
        super().__init__()
        self.setObjectName("Card")
        self.setFixedSize(w, h)
        self.setCursor(Qt.PointingHandCursor)
        self.card = card
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(6)
        ic = AppIcon(win, 84)
        ic.set_app(card.title, card.icon_url, None, card.tile_color)
        lay.addWidget(ic, 0, Qt.AlignHCenter)
        t = label(card.title, wrap=True)
        f = t.font()
        f.setWeight(QFont.DemiBold)
        t.setFont(f)
        t.setMaximumHeight(40)
        lay.addWidget(t)
        lay.addWidget(label(card.categories[0] if card.categories else card.publisher, "Muted"))
        bottom = QHBoxLayout()
        bottom.addWidget(label(stars(card.rating), "Muted"))
        bottom.addStretch()
        state = win.card_state(card)
        badge = label(state or card.price_text or "", "Chip")
        if state == "Update":
            badge.setStyleSheet(f"background:{K.ACCENT};color:black;border-radius:10px;padding:2px 8px")
        elif state == "Installed":
            badge.setStyleSheet(f"background:#25402a;color:{K.GOOD};border-radius:10px;padding:2px 8px")
        bottom.addWidget(badge)
        lay.addLayout(bottom)
        self.clicked.connect(lambda: win.open_product(card.product_id, card))


class Shelf(QWidget):
    """Title + 'See all' + one horizontally scrolling row of tiles."""

    def __init__(self, win, title, see_all=None):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(label(title, "H2"))
        head.addStretch()
        if see_all:
            b = button("See all", flat=True)
            b.setStyleSheet(f"color:{K.ACCENT}")
            b.clicked.connect(see_all)
            head.addWidget(b)
        v.addLayout(head)
        self.sa = QScrollArea()
        self.sa.setWidgetResizable(True)
        self.sa.setFixedHeight(250)
        self.sa.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.row = QHBoxLayout(inner)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(12)
        self.loading = label("Loading...", "Muted")
        self.row.addWidget(self.loading)
        self.row.addStretch()
        self.sa.setWidget(inner)
        v.addWidget(self.sa)

    def fill(self, cards):
        try:
            self.row.count()
        except RuntimeError:     # this shelf was replaced while its chart was loading
            return
        clear(self.row)
        if not cards:
            self.row.addWidget(label("Nothing here right now.", "Muted"))
        for c in cards:
            self.row.addWidget(StoreTile(self.win, c))
        self.row.addStretch()

    def fail(self, error):
        try:
            clear(self.row)
        except RuntimeError:
            return
        self.row.addWidget(label(f"Couldn't load: {error}", "Muted"))


class Grid(QWidget):
    def __init__(self):
        super().__init__()
        self.flow = FlowLayout(self)

    def add(self, w):
        self.flow.addWidget(w)


class AppRow(QFrame):
    """An installed app: icon, name, version / progress, primary button, more menu."""

    def __init__(self, win, app):
        super().__init__()
        self.win, self.app = win, app
        self.setObjectName("Card")
        self.setMinimumHeight(68)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(14)
        self.icon = AppIcon(win, 40)
        lay.addWidget(self.icon)
        mid = QVBoxLayout()
        mid.setSpacing(2)
        self.title = label()
        f = self.title.font()
        f.setWeight(QFont.DemiBold)
        self.title.setFont(f)
        self.sub = label(obj="Muted")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        mid.addWidget(self.title)
        mid.addWidget(self.sub)
        mid.addWidget(self.bar)
        lay.addLayout(mid, 1)
        self.status = label(obj="Muted")
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.status)
        self.primary = button("Update", accent=True)
        self.primary.setFixedWidth(104)
        self.primary.clicked.connect(lambda: win.row_primary(self.app))
        lay.addWidget(self.primary)
        self.more = button("", flat=True, icon="more", tip="More: Unjam, Repair, Hold, Reset, Uninstall...")
        self.more.setFixedWidth(36)
        self.more.clicked.connect(lambda: win.app_menu(self.app, self.more.mapToGlobal(self.more.rect().bottomLeft())))
        lay.addWidget(self.more)
        self.setCursor(Qt.PointingHandCursor)
        self.refresh()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.win.open_app(self.app)

    def refresh(self):
        w, a = self.win, self.app
        p = a.product
        q = w.queue.find(a.family)
        job = w.jobs.active.get(a.family)
        self.title.setText(a.title)
        pub = p.publisher if p else (a.installed.publisher.split(",")[0].replace("CN=", "") if a.installed else "")
        ver = (f"Version {a.current_str}" + (f"  →  {a.latest.version_str}" if a.update_available else "")) if a.installed else "Not installed"
        if a.is_held:
            ver += "   ·   held" if a.held == "all" else f"   ·   skipping {a.held}"
        size = w.sizes.get(a.family)
        if size and w.current == "library":
            ver += f"   ·   {fmt_size(size)}"
        self.sub.setText(f"{pub}  ·  {ver}" if pub else ver)
        local = a.entries[0].logo if a.entries else None
        self.icon.set_app(a.title, p.icon_url if p else None, local, p.tile_color if p else None)
        self.status.setToolTip("")
        self.status.setStyleSheet("")
        if q or job:
            st = q.msg if q else job["msg"]
            done, total = (q.done, q.total) if q else (job["done"], job["total"])
            self.bar.setVisible(True)
            if total and (not q or q.state == "downloading"):
                self.bar.setRange(0, 1000)
                self.bar.setValue(int(1000 * done / max(total, 1)))
            else:
                self.bar.setRange(0, 0)
            self.status.setText(st[:60])
            self.primary.setText("Pause" if q and q.state == "downloading" else "Resume" if q and q.state == "paused" else "Cancel")
            set_accent(self.primary, False)
        elif a.family in w.failures:
            short, full = w.failures[a.family]
            self.bar.setVisible(False)
            self.status.setText(f"⚠ {short[:70]}")
            self.status.setStyleSheet(f"color:{K.BAD}")
            self.status.setToolTip(full[:2000])
            self.primary.setText("Retry")
            set_accent(self.primary, True)
        else:
            self.bar.setVisible(False)
            if a.update_available:
                self.status.setText(fmt_size(a.latest.size))
                self.primary.setText("Update")
                set_accent(self.primary, True)
            elif not a.installed:
                self.status.setText(fmt_size(a.latest.size) if a.latest else "")
                self.primary.setText("Get")
                set_accent(self.primary, True)
            else:
                self.status.setText(a.check_error[:60] if a.check_error and a.product and not a.is_held else
                                    "Up to date" if a.latest else "")
                self.primary.setText("Open")
                set_accent(self.primary, False)
        self.primary.setEnabled(bool(q or job) or bool(a.installed and a.entries) or a.update_available or not a.installed
                                or a.family in w.failures)


class QueueRow(QFrame):
    def __init__(self, win, item):
        super().__init__()
        self.win, self.item = win, item
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)
        ic = AppIcon(win, 36)
        ic.set_app(item.title, item.icon_url)
        lay.addWidget(ic)
        mid = QVBoxLayout()
        mid.setSpacing(2)
        self.title = label(item.title)
        f = self.title.font()
        f.setWeight(QFont.DemiBold)
        self.title.setFont(f)
        self.sub = label(obj="Muted")
        self.sub.setTextFormat(Qt.RichText)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        mid.addWidget(self.title)
        mid.addWidget(self.sub)
        mid.addWidget(self.bar)
        lay.addLayout(mid, 1)
        self.btns = QHBoxLayout()
        lay.addLayout(self.btns)
        self.refresh()

    def _btn(self, icon, tip, fn):
        b = button("", flat=True, icon=icon, tip=tip)
        b.setFixedWidth(34)
        b.clicked.connect(fn)
        self.btns.addWidget(b)

    def refresh(self):
        it, q = self.item, self.win.queue
        kind = "Desktop installer" if it.kind == "desktop" else "Store package"
        state = {"queued": "Queued", "downloading": "Downloading", "paused": "Paused", "waiting": "Waiting for installer",
                 "installing": "Installing", "done": "Done", "failed": "Failed", "cancelled": "Cancelled",
                 "skipped": "Not out yet"}.get(it.state, it.state)
        color = {"done": K.GOOD, "failed": K.BAD}.get(it.state, K.TEXT2)
        self.sub.setText(f"<span style='color:{color}'>{state}</span>  ·  {html.escape(it.msg[:110])}  ·  {kind}")
        self.sub.setToolTip(it.error[:2000] if it.error else "")
        self.bar.setVisible(it.state in ("downloading", "waiting", "installing"))
        if it.state == "downloading" and it.total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(1000 * it.done / max(it.total, 1)))
        else:
            self.bar.setRange(0, 0)
        clear(self.btns)
        if it.state in ("queued", "paused"):
            self._btn("back", "Move up", lambda: q.move(it.id, -1))
            self._btn("download", "Move to top", lambda: q.to_top(it.id))
        if it.state == "downloading":
            self._btn("", "Pause (keeps what's downloaded)", lambda: q.pause(it.id))
        if it.state in ("paused", "failed", "cancelled"):
            self._btn("", "Resume / retry", lambda: q.resume(it.id))
        if it.state not in ("done", "failed", "cancelled", "skipped"):
            self._btn("close", "Cancel", lambda: q.cancel(it.id))
