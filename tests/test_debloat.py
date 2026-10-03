"""Preinstalled-clutter presets: table sanity, protected packages, removal guard rails, the 'Put back' record."""

import pytest

from storemgr import debloat, winapps


def _pkg(family, removable=True, version="1.0.0.0", bundle=False, framework=False):
    name = family.rsplit("_", 1)[0]
    return winapps.Installed(name=name, full_name=f"{name}_{version}_x64__{family.rsplit('_', 1)[1]}", family=family,
                             version=version, arch="x64", publisher="CN=Test", is_framework=framework,
                             is_resource=False, is_store=True, location="", status="Ok", removable=removable,
                             is_bundle=bundle)


@pytest.fixture
def removed_file(tmp_path, monkeypatch):
    f = tmp_path / "removed.json"
    monkeypatch.setattr(debloat, "REMOVED_FILE", f)
    return f


def test_every_family_is_a_valid_family_name():
    for e in debloat.PRESETS:
        assert winapps.FAMILY_RE.match(e.family), e.family


def test_no_duplicates():
    fams = [e.family.lower() for e in debloat.PRESETS]
    pids = [e.product_id for e in debloat.PRESETS]
    assert len(fams) == len(set(fams))
    assert len(pids) == len(set(pids))


def test_every_entry_is_complete():
    for e in debloat.PRESETS:
        assert e.title and e.description and e.group in debloat.GROUPS
        assert len(e.product_id) == 12 and e.product_id.isalnum() and e.product_id.upper() == e.product_id
        assert not {chr(0x2013), chr(0x2014)} & set(e.description + e.title)


def test_no_protected_packages_in_the_table():
    for e in debloat.PRESETS:
        assert not debloat.protected(e.family), e.family
        assert not e.family.endswith("_cw5n1h2txyewy")


@pytest.mark.parametrize("fam", [
    "Microsoft.WindowsStore_8wekyb3d8bbwe", "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe",
    "Microsoft.StorePurchaseApp_8wekyb3d8bbwe", "Microsoft.SecHealthUI_8wekyb3d8bbwe",
    "Microsoft.WindowsTerminal_8wekyb3d8bbwe", "Microsoft.WindowsNotepad_8wekyb3d8bbwe",
    "Microsoft.WindowsCalculator_8wekyb3d8bbwe", "Microsoft.Windows.Photos_8wekyb3d8bbwe",
    "Microsoft.Paint_8wekyb3d8bbwe", "Microsoft.ScreenSketch_8wekyb3d8bbwe",
    "Microsoft.XboxIdentityProvider_8wekyb3d8bbwe", "Microsoft.GamingServices_8wekyb3d8bbwe",
    "Microsoft.MicrosoftEdge.Stable_8wekyb3d8bbwe", "MicrosoftWindows.Client.WebExperience_cw5n1h2txyewy",
    "Microsoft.VCLibs.140.00_8wekyb3d8bbwe", "Microsoft.UI.Xaml.2.8_8wekyb3d8bbwe",
    "MicrosoftCorporationII.WinAppRuntime.Main.1.5_8wekyb3d8bbwe", "Microsoft.Windows.ShellExperienceHost_cw5n1h2txyewy",
    "Microsoft.HEVCVideoExtensions_8wekyb3d8bbwe",
])
def test_protected_packages_are_recognised(fam):
    assert debloat.protected(fam)


def test_installed_clutter_matches_case_insensitively():
    pkgs = [_pkg("Microsoft.OutlookforWindows_8wekyb3d8bbwe"), _pkg("Microsoft.BingNews_8wekyb3d8bbwe"),
            _pkg("Microsoft.WindowsStore_8wekyb3d8bbwe"), _pkg("Contoso.Thing_8wekyb3d8bbwe")]
    found = [e.title for e in debloat.installed_clutter(pkgs)]
    assert found == ["Microsoft News", "Outlook (new)"]


def test_remove_refuses_entries_not_in_the_table(monkeypatch, removed_file):
    monkeypatch.setattr(winapps, "uninstall", lambda *a, **k: pytest.fail("must not uninstall"))
    fake = debloat.Entry("Microsoft.WindowsStore_8wekyb3d8bbwe", "Store", "x", "9WZDNCRFJBMP", debloat.MS_EXTRAS)
    ok, why = debloat.remove(fake, [_pkg(fake.family)])
    assert not ok and "presets" in why
    evil = debloat.Entry("x'; whoami; '_8wekyb3d8bbwe", "Evil", "x", "9WZDNCRFJBMP", debloat.MS_EXTRAS)
    assert not debloat.remove(evil, [])[0]
    assert not removed_file.exists()


def test_remove_refuses_non_removable(monkeypatch, removed_file):
    monkeypatch.setattr(winapps, "uninstall", lambda *a, **k: pytest.fail("must not uninstall"))
    e = debloat.preset("Microsoft.BingNews_8wekyb3d8bbwe")
    ok, why = debloat.remove(e, [_pkg(e.family, removable=False)])
    assert not ok and "not removable" in why


def test_remove_uninstalls_main_package_and_records_it(monkeypatch, removed_file):
    calls = []
    monkeypatch.setattr(winapps, "uninstall", lambda p, *a, **k: (calls.append(p.full_name), (True, ""))[1])
    e = debloat.preset("Clipchamp.Clipchamp_yxz26nhyzhsrt")
    pkgs = [_pkg(e.family, version="4.6.0.0"), _pkg(e.family, version="4.6.0.0", bundle=True)]
    ok, msg = debloat.remove(e, pkgs)
    assert ok and msg == "Removed Microsoft Clipchamp"
    assert calls == ["Clipchamp.Clipchamp_4.6.0.0_x64__yxz26nhyzhsrt"]
    [r] = debloat.removed()
    assert r["family"] == e.family and r["product_id"] == "9P1J8S7CCWWT" and r["version"] == "4.6.0.0"


def test_remove_reports_windows_errors_without_recording(monkeypatch, removed_file):
    monkeypatch.setattr(winapps, "uninstall", lambda *a, **k: (False, "Remove-AppxPackage: failed 0x80073CFA blah"))
    e = debloat.preset("Microsoft.BingWeather_8wekyb3d8bbwe")
    ok, why = debloat.remove(e, [_pkg(e.family)])
    assert not ok and "0x80073CFA" in why
    assert debloat.removed() == []


def test_remove_when_not_installed_is_a_no_op(monkeypatch, removed_file):
    monkeypatch.setattr(winapps, "uninstall", lambda *a, **k: pytest.fail("must not uninstall"))
    ok, msg = debloat.remove(debloat.PRESETS[0], [])
    assert ok and "not installed" in msg and not removed_file.exists()


def test_removed_list_and_forget(removed_file):
    a, b = debloat.PRESETS[0], debloat.PRESETS[1]
    debloat._record(a, "1.0")
    debloat._record(b, "2.0")
    assert [r["family"] for r in debloat.removed()][0] == b.family
    debloat.forget(a.family.upper())
    assert [r["family"] for r in debloat.removed()] == [b.family]
    debloat.forget("Nothing.Here_8wekyb3d8bbwe")


def test_removed_survives_a_corrupt_file(removed_file):
    removed_file.write_text("{not json", encoding="utf-8")
    assert debloat.removed() == []
    removed_file.write_text("[1, 2]", encoding="utf-8")
    assert debloat.removed() == []
