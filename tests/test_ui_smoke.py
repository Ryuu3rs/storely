"""The real window must build and every page must render, before any data has arrived (a crash here means
Storely doesn't open at all - unit tests of the parts don't catch it)."""

import pytest
from PySide6.QtCore import Qt

PAGES = ["home", "updates", "library", "downloads", "wishlist", "health", "settings", "search"]


@pytest.fixture(scope="module")
def window(qapp):
    qa = qapp
    import app as A
    from storemgr import ui_kit as K
    K.apply_theme("dark")
    qa.setStyleSheet(K.STYLE)
    w = A.Main()
    w.setAttribute(Qt.WA_DontShowOnScreen)
    yield w
    w.jobs.pool.waitForDone(20000)     # background work started by the window finishes before it goes away
    w.queue.timer.stop()
    w.watchdog.stop()


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_before_data_arrives(window, page):
    window.search_query = "notepad"
    window.show_page(page)


def test_counts_start_at_zero(window):
    assert window.update_counts() == (0, 0)


def test_settings_shows_each_self_update_state(window, monkeypatch):
    from storemgr import updater
    rel = updater.Release("9.9.9", "", "https://github.com/x", 1, "https://github.com/s", "https://github.com/g",
                          "https://github.com/p")
    for ready in (None, ("9.9.9", "x")):
        window.self_update, window.ready_update = rel, ready
        window.show_page("settings")
    window.self_update = window.ready_update = None


def test_ready_update_installs_on_close_without_reopening(window, monkeypatch):
    from storemgr import updater
    calls = []
    monkeypatch.setattr(updater, "install", lambda p, relaunch=True: calls.append((p, relaunch)))
    window.ready_update = ("9.9.9", "setup.exe")
    window._install_ready_update()
    assert calls == [("setup.exe", False)] and window.ready_update is None
    window._install_ready_update()          # nothing ready any more: nothing launched
    assert len(calls) == 1
