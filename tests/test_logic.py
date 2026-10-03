"""Pure logic: version lines, publisher hash, Store links."""

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
])
def test_same_line(new, old, offered, ok):
    assert fe3.same_line(new, old, offered) is ok


def test_best_finds_date_style_update():
    files = [pkg("Microsoft.GamingApp", "2609.1001.16.0")]
    assert fe3.best(files, "Microsoft.GamingApp", "x64", (2608, 1001, 17, 0)).version_str == "2609.1001.16.0"


def test_best_stays_on_realtek_line():
    files = [pkg("Realtek", "1.54.398.0"), pkg("Realtek", "2.54.397.0")]
    assert fe3.best(files, "Realtek", "x64", (1, 54, 398, 0)).version_str == "1.54.398.0"


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
    ("unjammed://updates", ("updates", "")),
    ("unjammed://update-all?token=abc", ("update-all", "abc")),
    ("unjammed://format-c", ("home", "")),
])
def test_parse_store_link(link, expected):
    assert parse_store_link(link) == expected
