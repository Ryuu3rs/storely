"""Capabilities an update adds: manifest parsing (packages + bundles), labels, diff, summary."""

import io
import zipfile

from storemgr import perms

NS = ('xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10" '
      'xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10" '
      'xmlns:uap3="http://schemas.microsoft.com/appx/manifest/uap/windows10/3" '
      'xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"')


def manifest(caps: str) -> str:
    return (f'<?xml version="1.0" encoding="utf-8"?><Package {NS}><Identity Name="Test.App" Version="1.0.0.0"/>'
            f'<Capabilities>{caps}</Capabilities></Package>')


def msix(path, caps: str):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AppxManifest.xml", manifest(caps))
    return path


def inner(caps: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("AppxManifest.xml", manifest(caps))
    return buf.getvalue()


def bundle(path, packages):
    """packages: (FileName, Architecture, Type, caps)."""
    rows = "".join(f'<Package Type="{t}" Architecture="{a}" FileName="{f}"/>' for f, a, t, _ in packages)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AppxMetadata/AppxBundleManifest.xml",
                   f'<Bundle xmlns="http://schemas.microsoft.com/appx/2013/bundle"><Packages>{rows}</Packages></Bundle>')
        for f, _, _, caps in packages:
            z.writestr(f.replace("\\", "/"), inner(caps))
    return path


def test_namespaces_and_case(tmp_path):
    (tmp_path / "AppxManifest.xml").write_text(manifest(
        '<Capability Name="internetClient"/><uap:Capability Name="PicturesLibrary"/>'
        '<uap3:Capability Name="backgroundMediaPlayback"/><rescap:Capability Name="runFullTrust"/>'
        '<DeviceCapability Name="WEBCAM"/><DeviceCapability Name="microphone"/>'
        '<uap4:CustomCapability xmlns:uap4="http://schemas.microsoft.com/appx/manifest/uap/windows10/4" Name="X.y_abc"/>'),
        encoding="utf-8")
    assert perms.capabilities_installed(str(tmp_path)) == {
        "internetClient", "picturesLibrary", "backgroundMediaPlayback", "runFullTrust", "webcam", "microphone"}


def test_missing_or_broken_manifest(tmp_path):
    assert perms.capabilities_installed(str(tmp_path)) == set()
    (tmp_path / "AppxManifest.xml").write_text("<not xml", encoding="utf-8")
    assert perms.capabilities_installed(str(tmp_path)) == set()


def test_plain_package(tmp_path):
    p = msix(tmp_path / "a.msix", '<rescap:Capability Name="broadFileSystemAccess"/><Capability Name="internetClient"/>')
    assert perms.capabilities_package(p, "x64") == {"broadFileSystemAccess", "internetClient"}


def test_bundle_picks_arch_and_skips_stub(tmp_path):
    b = bundle(tmp_path / "a.msixbundle", [
        ("AppxMetadata\\Stub\\App_x64_stub.msix", "x64", "application", '<DeviceCapability Name="location"/>'),
        ("App_arm64.msix", "arm64", "application", '<DeviceCapability Name="microphone"/>'),
        ("App_x64.msix", "x64", "application", '<DeviceCapability Name="webcam"/>'),
        ("App_scale-200.msix", "neutral", "resource", '<DeviceCapability Name="contacts"/>'),
    ])
    assert perms.capabilities_package(b, "x64") == {"webcam"}
    assert perms.capabilities_package(b, "arm64") == {"microphone"}


def test_bundle_falls_back_to_neutral(tmp_path):
    b = bundle(tmp_path / "a.appxbundle", [
        ("App_arm64.appx", "arm64", "application", '<DeviceCapability Name="microphone"/>'),
        ("App_neutral.appx", "neutral", "application", '<Capability Name="internetClient"/>'),
    ])
    assert perms.capabilities_package(b, "x64") == {"internetClient"}


def test_bundle_inner_missing_is_empty(tmp_path):
    p = tmp_path / "a.msixbundle"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("AppxMetadata/AppxBundleManifest.xml",
                   '<Bundle xmlns="http://schemas.microsoft.com/appx/2013/bundle"><Packages>'
                   '<Package Type="application" Architecture="x64" FileName="gone.msix"/></Packages></Bundle>')
    assert perms.capabilities_package(p, "x64") == set()


def test_not_a_zip(tmp_path):
    p = tmp_path / "bad.msix"
    p.write_bytes(b"nope")
    assert perms.capabilities_package(p, "x64") == set()


def test_describe_known_and_unknown():
    p = perms.describe("RUNFULLTRUST")
    assert (p.name, p.risk) == ("runFullTrust", "high")
    assert "full access" in p.label
    assert perms.describe("packagedServices").label == "installs a Windows service"
    assert perms.describe("internetClient").risk == "low"
    u = perms.describe("extendedSuperPowersV2")
    assert (u.label, u.risk) == ("extended super powers v2", "medium")
    assert perms.describe("bluetooth.genericAttributeProfile").label == "bluetooth generic attribute profile"
    assert perms.describe("{6bdd1fc6-810f-11d0-bec7-08002be2092f}").label == "a specific hardware device"


def test_diff_orders_riskiest_first_and_ignores_case():
    old = {"internetClient", "Webcam", "musicLibrary"}
    new = {"internetclient", "webcam", "location", "bluetooth", "runFullTrust", "microphone", "fooBar"}
    ch = perms.diff(old, new)
    assert [p.name for p in ch.added] == ["runFullTrust", "fooBar", "location", "microphone", "bluetooth"]
    assert ch.removed == ["musicLibrary"]
    assert perms.has_risky(ch)


def test_summary_and_risky():
    assert perms.summary(perms.diff(set(), set())) == ""
    ch = perms.diff({"internetClient"}, {"internetClient", "webcam", "microphone", "location", "contacts"})
    assert perms.summary(ch) == "Adds: contacts, location, +2 more"
    ch = perms.diff(set(), {"runFullTrust", "webcam"})
    assert perms.summary(ch) == "Adds: full desktop access, webcam"
    low = perms.diff({"webcam"}, {"internetClient", "bluetooth"})
    assert not perms.has_risky(low)
    assert low.removed == ["webcam"]
    assert perms.summary(low) == "Adds: Bluetooth, internet"
