"""Carrying data over from the app's earlier names (My Store, Unjammed)."""

import storemgr


def setup(tmp_path, monkeypatch):
    new, old = tmp_path / "Storely", tmp_path / "MyStore"
    monkeypatch.setattr(storemgr, "DATA_DIR", new)
    monkeypatch.setattr(storemgr, "OLD_DATA_DIRS", (tmp_path / "Unjammed", old))
    old.mkdir()
    (old / "settings.json").write_text('{"theme": "light"}')
    (old / "history.json").write_text("[1]")
    (old / "downloads").mkdir()
    (old / "downloads" / "huge.msixbundle").write_bytes(b"x" * 1000)
    return new, old


def test_whole_folder_moves_when_nothing_holds_it(tmp_path, monkeypatch):
    new, old = setup(tmp_path, monkeypatch)
    storemgr._migrate()
    assert (new / "settings.json").read_text() == '{"theme": "light"}' and not old.exists()


def test_existing_storely_folder_still_gets_missing_records(tmp_path, monkeypatch):
    new, old = setup(tmp_path, monkeypatch)
    new.mkdir()
    (new / "history.json").write_text("[2]")           # Storely's own copy wins
    storemgr._migrate()
    assert (new / "settings.json").read_text() == '{"theme": "light"}'
    assert (new / "history.json").read_text() == "[2]"
    assert not (new / "downloads").exists()             # never gigabytes of re-creatable downloads
    assert old.exists()                                  # the old folder is left alone
