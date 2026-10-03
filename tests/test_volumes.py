"""App drives: Get-AppxVolume parsing (incl. a stale record carrying another disk's GUID), drive-letter validation,
the elevated 'app-volume' action's argument checks, and the -Volume install argument."""

import json

import pytest

from storemgr import admin, helper, volumes

JOB = "0123456789abcdef0123456789abcdef"
C = r"\\?\Volume{00064d99-7f70-3605-411d-f901329b0c00}"
G = r"\\?\Volume{919f721f-56d1-46da-8b73-3c88262047b2}"
F = r"\\?\Volume{5f71f1d8-d16f-421f-96d3-6674b0e2bc53}"
J_REAL = r"\\?\Volume{5ab887c0-79cf-11f0-a7f4-010101010000}"
REAL = {"C": C, "G": G, "F": F, "J": J_REAL}

RAW = json.dumps([
    {"n": C, "p": r"C:\Program Files\WindowsApps", "off": False, "sys": True, "d": True},
    {"n": G, "p": r"J:\WindowsApps", "off": True, "sys": False, "d": False},
    {"n": F, "p": r"F:\WindowsApps", "off": False, "sys": False, "d": False},
    {"n": G, "p": r"G:\WindowsApps", "off": False, "sys": False, "d": False},
    {"n": r"\\?\Volume{aaaaaaaa-0000-0000-0000-000000000000}", "p": r"K:\WindowsApps", "off": True, "sys": False,
     "d": False},
])


def _parse(raw=RAW):
    return volumes.parse(raw, guid_of=REAL.get, usage=lambda d: (100 * ord(d), 1000 * ord(d)))


def test_parse_reads_every_volume():
    vols = _parse()
    assert [v.drive for v in vols] == ["C", "J", "F", "G", "K"]
    c = vols[0]
    assert c.is_default and c.is_system and c.usable and c.free == 100 * ord("C") and c.label == "C:"


def test_parse_flags_a_record_carrying_another_disks_guid():
    by = {v.drive: v for v in _parse()}
    assert by["J"].wrong_disk and not by["J"].usable and by["J"].free is None
    assert not by["G"].wrong_disk and by["G"].usable


def test_parse_unplugged_drive_is_offline_not_wrong():
    k = {v.drive: v for v in _parse()}["K"]
    assert k.is_offline and not k.wrong_disk and not k.usable


def test_parse_single_object_and_empty():
    one = json.dumps({"n": F, "p": r"F:\WindowsApps", "off": False, "sys": False, "d": True})
    [v] = _parse(one)
    assert v.drive == "F" and v.is_default
    assert _parse("") == [] and _parse("[]") == []


def test_parse_volume_without_drive_letter():
    raw = json.dumps([{"n": F, "p": r"\\?\Volume{5f71f1d8-d16f-421f-96d3-6674b0e2bc53}\WindowsApps", "off": False,
                       "sys": False, "d": False}])
    [v] = _parse(raw)
    assert v.drive == "" and v.free is None and v.label.endswith("WindowsApps")


def test_default_and_for_drive_skip_stale_records():
    vols = _parse()
    assert volumes.default(vols).drive == "C"
    assert volumes.for_drive("g", vols).path == r"G:\WindowsApps"
    assert volumes.for_drive("J:", vols) is None


@pytest.mark.parametrize("value,letter", [("g", "G"), ("G", "G"), ("G:", "G"), ("g:\\", "G"), ("z", "Z")])
def test_drive_letter_accepts(value, letter):
    assert volumes.drive_letter(value) == letter


@pytest.mark.parametrize("value", ["", "GG", "1", "G:\\WindowsApps", "G;", "'G'", "G:\\\\", "\\\\?\\G:", "G\n",
                                   "C:\\Program Files", "é", None])
def test_drive_letter_rejects(value):
    with pytest.raises(ValueError):
        volumes.drive_letter(value)


@pytest.mark.parametrize("name", ["40459File-New-Project.EarTrumpet_2.3.0.0_x86__1sdd7yawvg6ne",
                                  "Microsoft.BingWeather_4.54.63045.0_x64__8wekyb3d8bbwe",
                                  "Microsoft.LanguageExperiencePacken-GB_26100.137.259.0_neutral__8wekyb3d8bbwe",
                                  "Microsoft.VCLibs.140.00_14.0.33519.0_x64_~_8wekyb3d8bbwe"])
def test_full_name_re_accepts_real_names(name):
    assert volumes.FULL_NAME_RE.match(name)


@pytest.mark.parametrize("name", ["x'; whoami; '_1.0.0.0_x64__8wekyb3d8bbwe", "Foo_1.0_x64__8wekyb3d8bbwe",
                                  "Foo_1.0.0.0_x64__8wekyb3d8bbwe\n", "Foo_8wekyb3d8bbwe", "*"])
def test_full_name_re_rejects_junk(name):
    assert not volumes.FULL_NAME_RE.match(name)


def test_move_validates_before_touching_windows(monkeypatch):
    monkeypatch.setattr(volumes, "ps", lambda *a, **k: pytest.fail("must not run PowerShell"))
    ok, why = volumes.move("x'; whoami; '_1.0.0.0_x64__8wekyb3d8bbwe", r"F:\WindowsApps")
    assert not ok and "package name" in why


def test_move_refuses_unknown_or_stale_volume(monkeypatch):
    monkeypatch.setattr(volumes, "volumes", _parse)
    monkeypatch.setattr(volumes, "ps", lambda *a, **k: pytest.fail("must not run PowerShell"))
    name = "Foo.Bar_1.0.0.0_x64__8wekyb3d8bbwe"
    assert not volumes.move(name, r"J:\WindowsApps")[0]
    assert not volumes.move(name, r"Q:\WindowsApps")[0]


def test_install_args(monkeypatch, tmp_path):
    monkeypatch.setattr(volumes, "PREF_FILE", tmp_path / "volume.json")
    vols = _parse()
    assert volumes.install_args(vols) == ""
    (tmp_path / "volume.json").write_text(json.dumps({"path": r"F:\WindowsApps"}), encoding="utf-8")
    assert volumes.install_args(vols) == r" -Volume 'F:\WindowsApps'"
    (tmp_path / "volume.json").write_text(json.dumps({"path": r"J:\WindowsApps"}), encoding="utf-8")
    assert volumes.install_args(vols) == ""
    (tmp_path / "volume.json").write_text(json.dumps({"path": r"C:\Program Files\WindowsApps"}), encoding="utf-8")
    assert volumes.install_args(vols) == ""
    (tmp_path / "volume.json").write_text("junk", encoding="utf-8")
    assert volumes.install_args(vols) == ""


def test_set_preferred_only_accepts_usable_volumes(monkeypatch, tmp_path):
    monkeypatch.setattr(volumes, "PREF_FILE", tmp_path / "volume.json")
    monkeypatch.setattr(volumes, "volumes", _parse)
    with pytest.raises(ValueError):
        volumes.set_preferred(r"J:\WindowsApps")
    volumes.set_preferred(r"f:\windowsapps")
    assert volumes.preferred().path == r"F:\WindowsApps"
    volumes.set_preferred(None)
    assert volumes.preferred() is None


def test_add_and_set_default_rejects_bad_letters_without_prompting(monkeypatch):
    monkeypatch.setattr(admin, "_elevated", lambda *a, **k: pytest.fail("must not elevate"))
    for bad in ["", "GG", "G; rm", "1"]:
        assert not volumes.add_and_set_default(bad)[0]


def test_add_and_set_default_refuses_a_stale_record(monkeypatch):
    monkeypatch.setattr(admin, "_elevated", lambda *a, **k: pytest.fail("must not elevate"))
    monkeypatch.setattr(volumes, "check_drive", lambda letter: "")
    monkeypatch.setattr(volumes, "volumes", _parse)
    ok, why = volumes.add_and_set_default("J")
    assert not ok and "out-of-date" in why


def test_add_and_set_default_elevates_with_just_the_letter(monkeypatch):
    seen = []
    monkeypatch.setattr(admin, "_elevated", lambda *a, **k: (seen.append(a), {"ok": True, "steps": [], "errors": []})[1])
    monkeypatch.setattr(volumes, "check_drive", lambda letter: "")
    monkeypatch.setattr(volumes, "volumes", _parse)
    assert volumes.add_and_set_default("f:")[0]
    assert seen == [("app-volume", "--drive", "F")]
    assert volumes.add_and_set_default("c")[1] == "New apps already install to C:"


@pytest.mark.parametrize("drive", ["", "g", "GG", "G:", "G:\\", "1", "'G'"])
def test_admin_app_volume_validates_before_prompting(monkeypatch, drive):
    monkeypatch.setattr(admin, "_elevated", lambda *a, **k: pytest.fail("must not elevate"))
    assert not admin.app_volume(drive)["ok"]


@pytest.mark.parametrize("argv", [
    ["app-volume", "--job", JOB],
    ["app-volume", "--job", JOB, "--drive", "g"],
    ["app-volume", "--job", JOB, "--drive", "G:"],
    ["app-volume", "--job", JOB, "--drive", "GG"],
    ["app-volume", "--job", JOB, "--drive", "G; whoami"],
    ["app-volume", "--job", "../../evil", "--drive", "G"],
])
def test_elevated_main_refuses_bad_app_volume_input(argv):
    assert helper.elevated_main(argv) == 2


def test_helper_accepts_good_app_volume_arguments():
    p = helper._parser("--elevated", ["unjam", "install", "cleanup", "store-auto-update", "app-volume"])
    p.add_argument("--drive", default="")
    a = helper._parse(p, ["app-volume", "--job", JOB, "--drive", "G"])
    assert a.drive == "G" and helper.DRIVE_RE.match(a.drive)


def test_live_volumes_read_without_admin():
    vols = volumes.volumes()
    assert vols and sum(v.is_default for v in vols) == 1
    assert all(v.path for v in vols)
