"""Windows Update FE3 delivery service - the same backend the Store uses to find and download packages."""

from __future__ import annotations

import html
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

FE3 = "https://fe3cr.delivery.mp.microsoft.com/ClientWebService/client.asmx"
DEVICE_ATTRS = ("E:BranchReadinessLevel=CBB&amp;DchuNvidiaGrfxExists=1&amp;CurrentBranch=rs4_release&amp;FlightRing=Retail"
                "&amp;AttrDataVer=57&amp;InstallLanguage=en-US&amp;OSUILocale=en-US&amp;InstallationType=Client"
                "&amp;FlightingBranchName=&amp;OSSkuId=48&amp;App=WU&amp;ProcessorManufacturer=GenuineIntel"
                "&amp;AppVer=10.0.17134.471&amp;OSArchitecture=AMD64&amp;UpdateManagementGroup=2&amp;IsDeviceRetailDemo=0"
                "&amp;IsFlightingEnabled=0&amp;TelemetryLevel=1&amp;DefaultUserRegion=244&amp;WuClientVer=10.0.17134.471"
                "&amp;OSVersion=10.0.17134.472&amp;DeviceFamily=Windows.Desktop")
KNOWN_IDS = [1, 2, 3, 11, 19, 544, 549, 2359974, 2359977, 5169044, 8788830, 23110993, 23110994, 54341900, 54343656,
             59830006, 59830007, 59830008, 60484010, 62450018, 62450019, 62450020, 66027979, 66053150, 97657898,
             98822896, 98959022, 98959023, 98959024, 98959025, 98959026, 104433538, 104900364, 105489019, 117765322,
             129905029, 130040030, 132387090, 132393049, 133399034, 138537048, 140377312, 143747671, 158941041,
             158941042, 158941043, 158941044, 159123858, 159130928, 164836897, 164847386, 164848327, 164852241,
             164852246, 164852252, 164852253]

_session = requests.Session()


def _os_version() -> str:
    import sys
    import winreg
    v = sys.getwindowsversion()
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
            ubr = winreg.QueryValueEx(k, "UBR")[0]
    except OSError:
        ubr = 0
    return f"{v.major}.{v.minor}.{v.build}.{ubr}"


_OSV = _os_version()
OS_ULONG = sum(int(x) << s for x, s in zip(_OSV.split("."), (48, 32, 16, 0), strict=True))
PC_PLATFORMS = {"windows.desktop", "windows.universal"}


PC_TARGETS = {0, 3}     # Windows.Universal, Windows.Desktop (5 = Xbox, 10 = HoloLens ...)
RUNNABLE = {"amd64": {"x64", "x86", "neutral"}, "x64": {"x64", "x86", "neutral"},
            "arm64": {"arm64", "x64", "x86", "arm", "neutral"}}


def for_this_pc(files: list[PackageFile], platforms: dict, arch: str = "x64") -> list[PackageFile]:
    """Drop builds that can't run here: other devices (Xbox '.70' builds, HoloLens), a newer Windows, or bundles
    whose contents are only for other processors (e.g. an ARM-only bundle under the same name)."""
    runnable = RUNNABLE.get(arch, {arch, "neutral"})
    out = []
    for f in files:
        plats = platforms.get(f.identity)
        if plats is not None and not any(p.lower() in PC_PLATFORMS and mv <= OS_ULONG for p, mv in plats):
            continue
        if f.targets and not any(t in PC_TARGETS and mv <= OS_ULONG for t, mv in f.targets):
            continue
        if f.bundled_archs and not runnable & set(f.bundled_archs):
            continue
        out.append(f)
    return out
DEVICE_ATTRS = (DEVICE_ATTRS.replace("10.0.17134.472", _OSV).replace("10.0.17134.471", _OSV)
                .replace("CurrentBranch=rs4_release", "CurrentBranch=ge_release"))


@dataclass(frozen=True)
class PackageFile:
    identity: str          # e.g. OpenAI.Codex_26.930.2377.0_x64__2p2nqsd0c76g0
    name: str
    version: tuple
    arch: str
    ext: str
    size: int
    digest: str            # base64 SHA1, as published by Microsoft
    update_id: str
    revision: str
    bundled_archs: tuple = ()     # processor types actually inside a bundle (from Microsoft's applicability blob)
    targets: tuple = ()           # ((platform code, min Windows version ulong), ...): 0 universal, 3 desktop, 5 Xbox

    @property
    def filename(self) -> str:
        return f"{self.identity}.{self.ext}"

    @property
    def version_str(self) -> str:
        return ".".join(map(str, self.version))


def vtuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def _envelope(action: str, to: str, body: str) -> str:
    now = datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    return f"""<s:Envelope xmlns:a="http://www.w3.org/2005/08/addressing" xmlns:s="http://www.w3.org/2003/05/soap-envelope">
<s:Header>
 <a:Action s:mustUnderstand="1">http://www.microsoft.com/SoftwareDistribution/Server/ClientWebService/{action}</a:Action>
 <a:MessageID>urn:uuid:{uuid.uuid4()}</a:MessageID>
 <a:To s:mustUnderstand="1">{to}</a:To>
 <o:Security s:mustUnderstand="1" xmlns:o="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
  <Timestamp xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"><Created>{now.strftime(fmt)}</Created><Expires>{(now + timedelta(minutes=5)).strftime(fmt)}</Expires></Timestamp>
  <wuws:WindowsUpdateTicketsToken wsu:id="ClientMSA" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd" xmlns:wuws="http://schemas.microsoft.com/msus/2014/10/WindowsUpdateAuthorization">
   <TicketType Name="MSA" Version="1.0" Policy="MBI_SSL"></TicketType>
  </wuws:WindowsUpdateTicketsToken>
 </o:Security>
</s:Header>
<s:Body>{body}</s:Body>
</s:Envelope>"""


def _soap(action: str, url: str, body: str) -> str:
    r = _session.post(url, data=_envelope(action, url, body).encode("utf-8"),
                      headers={"Content-Type": "application/soap+xml; charset=utf-8"}, timeout=60)
    r.raise_for_status()
    return r.text


def _cookie() -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    x = _soap("GetCookie", FE3, '<GetCookie xmlns="http://www.microsoft.com/SoftwareDistribution/Server/ClientWebService">'
              f"<oldCookie></oldCookie><lastChange>2015-10-21T17:01:07.1472913Z</lastChange><currentTime>{now}</currentTime>"
              "<protocolVersion>1.40</protocolVersion></GetCookie>")
    m = re.search(r"<EncryptedData>(.*?)</EncryptedData>", x)
    if not m:
        raise RuntimeError("delivery service gave no cookie")
    return m.group(1)


_RE_UPDATE = re.compile(r"<Update><ID>(\d+)</ID><Xml>(.*?)</Xml></Update>", re.S)
_RE_INFO = re.compile(r"<UpdateInfo><ID>(\d+)</ID>.*?<Xml>(.*?)</Xml></UpdateInfo>", re.S)
_RE_FILE = re.compile(r'<File FileName="[^"]+\.((?:e?appx|e?msix)(?:bundle)?)"[^>]*?Digest="([^"]+)"[^>]*?Size="(\d+)"'
                      r'[^>]*?InstallerSpecificIdentifier="([^"]+)"', re.I)
_RE_IDENT = re.compile(r'UpdateID="([^"]+)" RevisionNumber="(\d+)"')
_RE_PKG = re.compile(r"^([^_]+)_([\d.]+)_([^_]*)_")
_RE_BLOB = re.compile(r"<ApplicabilityBlob>(\{.*?\})</ApplicabilityBlob>", re.S)


def packages(wu_category: str) -> list[PackageFile]:
    """Every package file the delivery service offers for a Store category (the app and usually its frameworks)."""
    ids = "".join(f"<int>{i}</int>" for i in KNOWN_IDS)
    body = f"""<SyncUpdates xmlns="http://www.microsoft.com/SoftwareDistribution/Server/ClientWebService">
 <cookie><Expiration>2045-03-11T02:02:48Z</Expiration><EncryptedData>{_cookie()}</EncryptedData></cookie>
 <parameters>
  <ExpressQuery>false</ExpressQuery>
  <InstalledNonLeafUpdateIDs>{ids}</InstalledNonLeafUpdateIDs>
  <OtherCachedUpdateIDs></OtherCachedUpdateIDs>
  <SkipSoftwareSync>false</SkipSoftwareSync>
  <NeedTwoGroupOutOfScopeUpdates>true</NeedTwoGroupOutOfScopeUpdates>
  <FilterAppCategoryIds><CategoryIdentifier><Id>{wu_category}</Id></CategoryIdentifier></FilterAppCategoryIds>
  <TreatAppCategoryIdsAsInstalled>true</TreatAppCategoryIdsAsInstalled>
  <AlsoPerformRegularSync>false</AlsoPerformRegularSync>
  <ComputerSpec/>
  <ExtendedUpdateInfoParameters>
   <XmlUpdateFragmentTypes><XmlUpdateFragmentType>Extended</XmlUpdateFragmentType></XmlUpdateFragmentTypes>
   <Locales><string>en-US</string><string>en</string></Locales>
  </ExtendedUpdateInfoParameters>
  <ClientPreferredLanguages><string>en-US</string></ClientPreferredLanguages>
  <ProductsParameters>
   <SyncCurrentVersionOnly>false</SyncCurrentVersionOnly>
   <DeviceAttributes>{DEVICE_ATTRS}</DeviceAttributes>
   <CallerAttributes>E:Interactive=1&amp;IsSeeker=1&amp;</CallerAttributes>
   <Products/>
  </ProductsParameters>
 </parameters>
</SyncUpdates>"""
    sync = html.unescape(_soap("SyncUpdates", FE3, body))
    files = {}
    for m in _RE_UPDATE.finditer(sync):
        f = _RE_FILE.search(m.group(2))
        if f:
            files[m.group(1)] = f
    out = []
    for m in _RE_INFO.finditer(sync):
        x = m.group(2)
        f = files.get(m.group(1))
        ident = _RE_IDENT.search(x)
        if "SecuredFragment" not in x or not f or not ident:
            continue
        p = _RE_PKG.match(f.group(4))
        if not p:
            continue
        archs, targets = (), ()
        blob = _RE_BLOB.search(x)
        if blob:
            try:
                b = json.loads(blob.group(1))
                archs = tuple(sorted({s.split("_")[2].lower() for s in b.get("content.bundledPackages") or [] if s.count("_") >= 2}))
                targets = tuple((int(t.get("platform.target", -1)), int(t.get("platform.minVersion") or 0))
                                for t in b.get("content.targetPlatforms") or [])
            except (ValueError, TypeError):
                pass
        out.append(PackageFile(identity=f.group(4), name=p.group(1), version=vtuple(p.group(2)), arch=p.group(3).lower(),
                               ext=f.group(1).lower(), size=int(f.group(3)), digest=f.group(2),
                               update_id=ident.group(1), revision=ident.group(2), bundled_archs=archs, targets=targets))
    return out


def same_line(v: tuple, line: tuple, offered_majors: set | frozenset = frozenset()) -> bool:
    """Is version v an update on the installed version's line? Microsoft serves parallel lines under one name:
    builds for other Windows editions (2019.x Groove next to the 11.x Media Player) and per-hardware lines
    (Realtek Audio Control 1.x and 2.x, both still updated). So while Microsoft still offers builds with your first
    number, stay on it. Once it doesn't, the line has moved on - date-style versions roll their first number every
    release (XBOX 2608 -> 2609, Store host 22606 -> 22608) - follow it upward, same number of digits only."""
    if not v or not line:
        return True
    old, new = line[0], v[0]
    if old == new:
        return True
    if old in offered_majors:
        return False
    return new > old and len(str(new)) == len(str(old))


def majors(files: list[PackageFile]) -> frozenset:
    return frozenset(f.version[0] for f in files if f.version)


def best(files: list[PackageFile], name: str, arch: str, line: tuple | None = None) -> PackageFile | None:
    """Newest package for this PC. line = installed version: stay on its version line (see same_line)."""
    ok = [f for f in files if f.name.lower() == name.lower() and f.arch in (arch, "neutral", "")]
    if line:
        offered = majors(ok)
        ok = [f for f in ok if same_line(f.version, line, offered)]
    return max(ok, key=lambda f: (f.version, f.arch == arch), default=None)


def download_url(pkg: PackageFile) -> str:
    sec = FE3 + "/secured"
    x = _soap("GetExtendedUpdateInfo2", sec,
              '<GetExtendedUpdateInfo2 xmlns="http://www.microsoft.com/SoftwareDistribution/Server/ClientWebService">'
              f"<updateIDs><UpdateIdentity><UpdateID>{pkg.update_id}</UpdateID><RevisionNumber>{pkg.revision}</RevisionNumber>"
              "</UpdateIdentity></updateIDs><infoTypes><XmlUpdateFragmentType>FileUrl</XmlUpdateFragmentType>"
              "<XmlUpdateFragmentType>FileDecryption</XmlUpdateFragmentType></infoTypes>"
              f"<deviceAttributes>{DEVICE_ATTRS}</deviceAttributes></GetExtendedUpdateInfo2>")
    # one update carries several files (package + block-map cab): take the one whose digest is the package's
    for m in re.finditer(r"<FileLocation><FileDigest>(.*?)</FileDigest><Url>(.*?)</Url>", x, re.S):
        url = html.unescape(m.group(2))
        host = requests.utils.urlparse(url).hostname or ""
        if m.group(1) == pkg.digest and (host == "microsoft.com" or host.endswith(".microsoft.com")):
            return url
    raise NotPublished(f"Microsoft has announced {pkg.name} {pkg.version_str} but hasn't published its download yet")


class NotPublished(RuntimeError):
    """The delivery service lists a version but gives no download for it (rolling out / not live yet)."""
