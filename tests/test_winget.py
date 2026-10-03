"""winget table parsing, id validation, error words, and refusing bad ids before running anything."""

import subprocess

import pytest

from storemgr import winget

TABLE = (
    "   - \\ | /\r"
    "Name                         Id                          Version         Available      Source\n"
    "-----------------------------------------------------------------------------------------------\n"
    "Ubisoft Connect              Ubisoft.Connect             < 174.0.0.13368 174.0.0.13368  winget\n"
    "Zoom Workplace               Zoom.Zoom.EXE               7.0.6 (43848)   7.2.1 (48556)  winget\n"
    "Café Über App                Cafe.Uber                   1.0             1.1            winget\n"
    "Some Store App               9NBLGGH4NNS1                1.0.0.0         1.0.1.0        msstore\n"
    "A Very Long Name Cut Off Wi… Publisher.LongNameProgra…   2.0             2.1            winget\n"
    "WinRAR 6.22 (64-bit)         RARLab.WinRAR               6.22.0          7.23.0         winget\n"
    "65 upgrades available.\n"
    "6 package(s) have version numbers that cannot be determined. Use --include-unknown to see all results.\n"
)


def test_parse_reads_rows_and_skips_noise():
    rows = winget.parse_upgrades(TABLE)
    ids = [r.id for r in rows]
    assert ids == ["Ubisoft.Connect", "Zoom.Zoom.EXE", "Cafe.Uber", "9NBLGGH4NNS1", "RARLab.WinRAR"]
    zoom = rows[1]
    assert (zoom.name, zoom.version, zoom.available, zoom.source) == ("Zoom Workplace", "7.0.6 (43848)", "7.2.1 (48556)", "winget")
    assert rows[0].version == "< 174.0.0.13368"


def test_truncated_ids_are_dropped_not_guessed():
    assert not any("…" in r.id for r in winget.parse_upgrades(TABLE))


def test_shifted_columns_fall_back_to_splitting():
    text = ("Name      Id        Version   Available  Source\n---\n"
            "Wide Name Here For Sure   Some.Id   1.0   2.0   winget\n")
    rows = winget.parse_upgrades(text)
    assert [(r.name, r.id, r.available) for r in rows] == [("Wide Name Here For Sure", "Some.Id", "2.0")]


def test_no_table():
    assert winget.parse_upgrades("No installed package found matching input criteria.") == []


def test_list_keeps_only_winget_source(monkeypatch):
    monkeypatch.setattr(winget, "_run", lambda args, timeout: subprocess.CompletedProcess(args, 0, TABLE.encode(), b""))
    assert "9NBLGGH4NNS1" not in [u.id for u in winget.list_upgrades()]


def test_list_times_out_in_plain_words(monkeypatch):
    def slow(args, timeout):
        raise subprocess.TimeoutExpired(args, timeout)
    monkeypatch.setattr(winget, "_run", slow)
    with pytest.raises(RuntimeError, match="didn't answer"):
        winget.list_upgrades(timeout=1)


@pytest.mark.parametrize("bad", ["", "a b", "x;calc", "--source", "Some.Id\n", "Cut.Off…", "-x"])
def test_upgrade_refuses_bad_ids_without_running(monkeypatch, bad):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("must not run winget"))
    with pytest.raises(RuntimeError, match="not a winget package id"):
        winget.upgrade(bad)


def test_explain_known_and_unknown():
    assert "checksum" in winget.explain(0x8A150011)
    assert "checksum" in winget.explain(-1978335215)          # same code as a signed exit status
    assert winget.explain(0x8A15FFFF, "some output\nInstaller failed with exit code: 5\n").endswith("exit code: 5")
