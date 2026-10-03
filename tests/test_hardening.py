"""Free-space check, one-time action tokens, quiet hours, crash logging."""

import logging
import sys
import time

import pytest

from storemgr import diag, winsys


def test_need_space_raises_in_plain_words(tmp_path):
    with pytest.raises(RuntimeError, match=r"Not enough space on .* for the download: needs about"):
        winsys.need_space(tmp_path, 10**18, "the download")
    winsys.need_space(tmp_path, 1, "the download")


def test_action_token_is_one_time_and_action_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(winsys, "TOKEN_FILE", tmp_path / "t.json")
    link = winsys.action_link("update-all")
    tok = link.split("token=")[1]
    assert not winsys.take_action_token("other-action", tok)
    assert not winsys.take_action_token("update-all", "guess")
    assert not winsys.take_action_token("update-all", "")
    assert winsys.take_action_token("update-all", tok)
    assert not winsys.take_action_token("update-all", tok)      # used up


def test_action_token_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(winsys, "TOKEN_FILE", tmp_path / "t.json")
    tok = winsys.action_link("update-all").split("token=")[1]
    later = time.time() + 2 * 86400
    monkeypatch.setattr(winsys.time, "time", lambda: later)
    assert not winsys.take_action_token("update-all", tok)


@pytest.mark.parametrize("hours,hour,quiet", [
    ([23, 7], 23, True), ([23, 7], 3, True), ([23, 7], 7, False), ([23, 7], 12, False),
    ([9, 17], 12, True), ([9, 17], 17, False), ([], 3, False), ([5, 5], 5, False),
])
def test_quiet_hours(hours, hour, quiet):
    now = time.mktime((2026, 10, 3, hour, 30, 0, 0, 0, -1))
    assert winsys.in_quiet_hours({"quiet_hours": hours}, now) is quiet


def test_uncaught_errors_are_logged(caplog):
    old = sys.excepthook
    try:
        diag.install_crash_handlers(gui=False)
        with caplog.at_level(logging.CRITICAL, logger="storely"):
            try:
                raise ValueError("boom")
            except ValueError:
                sys.excepthook(*sys.exc_info())
        assert "boom" in caplog.text and "ValueError" in caplog.text
    finally:
        sys.excepthook = old
