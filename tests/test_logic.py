"""Pure logic: version lines, publisher hash, Store links, bundle vs app versions."""

from dataclasses import replace

import pytest

from app import parse_store_link
from storemgr import fe3, winapps
from storemgr.fe3 import PackageFile


def pkg(name, version, arch="x64", ext="msix"):
    return PackageFile(identity=f"{name}_{version}_{arch}__8wekyb3d8bbwe", name=name, version=fe3.vtuple(version),
                       arch=arch, ext=ext, size=1, digest="", update_id="", revision="1")


def test_publisher_id_matches_windows():
    assert winapps.publisher_id("CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US") \
        == "8wekyb3d8bbwe"


def test_best_stays_on_installed_version_line():
    files = [pkg("Microsoft.ZuneMusic", "2019.22.1"), pkg("Microsoft.ZuneMusic", "11.2409.5"),
             pkg("Microsoft.ZuneMusic", "11.2410.1"), pkg("Microsoft.ZuneMusic", "11.2411.0", arch="arm64")]
    assert fe3.best(files, "Microsoft.ZuneMusic", "x64", (11, 2400)).version_str == "11.2410.1"
    assert fe3.best(files, "Microsoft.ZuneMusic", "x64").version_str == "2019.22.1"


@pytest.mark.parametrize("new,old,offered,ok", [
    ((2609, 1001, 16), (2608, 1001, 17), {2609}, True),         # XBOX: date-style first number rolled
    ((22608, 1401, 1), (22606, 1401, 3), {22608}, True),        # Store Experience Host
    ((11, 2410), (11, 2409), {11}, True),
    ((2, 54, 397), (1, 54, 398), {1, 2}, False),                # Realtek: 1.x line still served -> stay
    ((2019, 22), (11, 2409), {11, 2019}, False),                # Groove next to Media Player
    ((2019, 22), (11, 2409), {2019}, False),                    # ...even when 11.x is gone (digits differ)
    ((1, 21), (2024, 203), {1}, False),                         # Xbox Speech: older line
    ((2, 0), (1, 9), {2}, True),                                # 1.x retired, 2.x is the line now
    ((10, 0), (9, 5), {10}, True),                              # 9.x retired, 10.x: digits differ but a small step
    ((10, 0), (9, 5), {9, 10}, False),                          # ...but not while 9.x is still offered
])
def test_same_line(new, old, offered, ok):
    assert fe3.same_line(new, old, offered) is ok


def test_best_finds_date_style_update():
    files = [pkg("Microsoft.GamingApp", "2609.1001.16.0")]
    assert fe3.best(files, "Microsoft.GamingApp", "x64", (2608, 1001, 17, 0)).version_str == "2609.1001.16.0"


def test_best_stays_on_realtek_line():
    files = [pkg("Realtek", "1.54.398.0"), pkg("Realtek", "2.54.397.0")]
    assert fe3.best(files, "Realtek", "x64", (1, 54, 398, 0)).version_str == "1.54.398.0"


def bundle(version, inner):
    return PackageFile(identity=f"Microsoft.BingNews_{version}_neutral_~_8wekyb3d8bbwe", name="Microsoft.BingNews",
                       version=fe3.vtuple(version), arch="neutral", ext="appxbundle", size=1, digest="", update_id="",
                       revision="1", bundled=tuple((a, fe3.vtuple(inner)) for a in ("x64", "x86", "arm")))


def news_app(pool):
    from storemgr.engine import App
    from storemgr.winapps import Installed

    def inst(v, bundle_):
        return Installed("Microsoft.BingNews", f"Microsoft.BingNews_{v}", "Microsoft.BingNews_8wekyb3d8bbwe", v,
                         "neutral" if bundle_ else "x64", "CN=Microsoft Corporation", False, False, True, "C:\\x", "Ok",
                         True, bundle_)
    a = App("Microsoft.BingNews_8wekyb3d8bbwe", inst("4.56.21872.0", False), None, bundle=inst("4.7.6002.0", True))
    a.pool = pool
    a.latest = max(pool, key=lambda f: a.target(f))
    return a


def test_bundle_number_is_not_the_app_version():
    # live case: bundle 4.7 holds app 4.56; Microsoft offers bundle 4.31 holding app 4.31 - a downgrade, not an update
    a = news_app([bundle("4.31.12124.0", "4.31.12124.0")])
    assert a.target(a.latest) == (4, 31, 12124, 0) and a.current == (4, 56, 21872, 0)
    assert not a.update_available


def test_real_update_inside_a_bundle_is_offered():
    a = news_app([bundle("4.31.12124.0", "4.31.12124.0"), bundle("4.58.1.0", "4.58.1.0")])
    assert a.update_available and a.latest_str == "4.58.1.0"


def test_unknown_bundle_contents_fall_back_to_bundle_numbers():
    f = replace(bundle("4.8.0.0", "1.0"), bundled=())
    a = news_app([f])
    assert f.app_version("x64") is None and a.current == (4, 7, 6002, 0) and a.update_available


def test_inner_version_prefers_this_pcs_processor():
    f = replace(bundle("1.0.0.0", "1.0"), bundled=(("x86", (1, 1)), ("x64", (1, 2)), ("arm", (1, 3))))
    assert f.app_version("x64") == (1, 2)


def test_for_this_pc_drops_xbox_and_arm_only():
    xbox = PackageFile("A_1.0.0.0_x64__x", "A", (1, 0), "x64", "msix", 1, "", "", "1", targets=((5, 0),))
    arm = PackageFile("A_1.0.0.0_neutral__x", "A", (1, 0), "neutral", "msixbundle", 1, "", "", "1", bundled_archs=("arm64",))
    ok = PackageFile("A_1.0.0.0_x64__x", "A", (1, 0), "x64", "msix", 1, "", "", "1", targets=((3, 0),))
    assert fe3.for_this_pc([xbox, arm, ok], {}, "x64") == [ok]


@pytest.mark.parametrize("link,expected", [
    ("ms-windows-store://pdp/?ProductId=9wzdncrfjbmp", ("product", "9WZDNCRFJBMP")),
    ("ms-windows-store://pdp/?PFN=Microsoft.WindowsCalculator_8wekyb3d8bbwe",
     ("family", "Microsoft.WindowsCalculator_8wekyb3d8bbwe")),
    ("ms-windows-store://downloadsandupdates", ("updates", "")),
    ("ms-windows-store://search/?query=notepad", ("search", "notepad")),
    ("ms-windows-store://home", ("home", "")),
    ("ms-windows-store://pdp/?ProductId=../../etc", ("home", "")),
    ("ms-windows-store://pdp/?PFN=x';calc;'_8wekyb3d8bbwe", ("home", "")),
    ("https://evil.example/", ("", "")),
    ("https://evil.example/detail/9WZDNCRFJBMP", ("", "")),
    ("show", ("", "")),
    ("https://apps.microsoft.com/detail/9wzdncrfjbmp?hl=en-gb&gl=GB", ("product", "9WZDNCRFJBMP")),
    ("https://apps.microsoft.com/store/detail/microsoft-store/9WZDNCRFJBMP", ("product", "9WZDNCRFJBMP")),
    ("https://www.microsoft.com/store/productId/9NBLGGH4NNS1", ("product", "9NBLGGH4NNS1")),
    ("storely://updates", ("updates", "")),
    ("storely://update-all?token=abc", ("update-all", "abc")),
    ("storely://format-c", ("home", "")),
    ("https://apps.microsoft.com/detail/xp8bt8dw290mpq?hl=en-gb", ("product", "XP8BT8DW290MPQ")),
    ("https://apps.microsoft.com/collections/productivity", ("", "")),
    ("https://www.microsoft.com/en-gb/p/spotify/9ncbcszsjrsb", ("product", "9NCBCSZSJRSB")),
    ("ms-windows-store://pdp/?ProductId=XP8BT8DW290MPQ", ("product", "XP8BT8DW290MPQ")),
    ("ms-windows-store://pdp/?ProductId=12345678", ("home", "")),
])
def test_parse_store_link(link, expected):
    assert parse_store_link(link) == expected
