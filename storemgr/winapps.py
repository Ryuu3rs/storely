"""Installed Windows apps (MSIX/AppX): list, install, repair, reset, uninstall, launch, verify, dependencies."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import psutil

from .fe3 import vtuple

NO_WINDOW = 0x08000000
ARCH = "x64" if os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() in ("AMD64", "") else \
    os.environ.get("PROCESSOR_ARCHITECTURE", "x64").lower()
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
# family names are Name_PublisherId: letters/digits/dots/dashes, then 13 base32 characters
FAMILY_RE = re.compile(r"\A[A-Za-z0-9.\-]{3,50}_[0-9a-hjkmnp-tv-z]{13}\Z")


def _powershell() -> str:
    """PowerShell 7 if it's installed in its normal (admin-only) place, else Windows PowerShell 5.1 - always by
    full path, never whatever 'pwsh' a PATH entry happens to point at."""
    pwsh = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PowerShell" / "7" / "pwsh.exe"
    return str(pwsh) if pwsh.exists() else str(SYSTEM32 / "WindowsPowerShell" / "v1.0" / "powershell.exe")


PWSH = _powershell()
_PRELUDE = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; if ($PSStyle) { $PSStyle.OutputRendering = 'PlainText' }; "
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def ps(script: str, timeout: float = 120) -> subprocess.CompletedProcess:
    # an inherited PSModulePath from PowerShell 7 makes 5.1 load 7's modules and fail; 5.1 rebuilds its default when
    # it's absent (7 needs it kept: that's how it finds the Appx module in System32)
    env = None if PWSH.lower().endswith("pwsh.exe") else \
        {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _PRELUDE + script],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       creationflags=NO_WINDOW, env=env)
    r.stdout, r.stderr = _ANSI.sub("", r.stdout or ""), _ANSI.sub("", r.stderr or "")
    return r


KNOWN_ERRORS = {
    "0x80073CF1": "This version has no build for this PC's processor/Windows edition - nothing to install",
    "0x80073D02": "The app (or something using it) is open - close it and try again",
    "0x80073D28": "This app installs a Windows service, which needs admin rights",
    "0x80073CF3": "A framework this app needs is missing or too old",
    "0x80073CFB": "This exact version is already installed",
    "0x80073CF8": "Another install of the same app cancelled this one - try again",
    "0x80073CF9": "Windows' installer refused it",
    "0x80070490": "Windows' package records for this app are damaged - try Repair, or Unjam (deep clean)",
    "0x80073CFA": "Windows won't remove this app - it's part of Windows or needed by another app",
    "0x80073D0B": "This app came with Windows and can't be moved to another drive",
    "0x800703EE": "That drive's app storage is mixed up with another drive's - see Settings > Where apps install",
    "0x80070005": "Windows said no - that needs admin rights",
}


def explain(err: str) -> str:
    """Short plain-English reason (+ code) for a Windows install error, keeping the raw text for the log."""
    for code, text in KNOWN_ERRORS.items():
        if code.lower() in err.lower():
            return f"{text} ({code})"
    first = next((ln.strip() for ln in err.splitlines() if ln.strip()), err)
    return first.replace("Add-AppxPackage: ", "")[:200]


def q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


@dataclass
class Installed:
    name: str
    full_name: str
    family: str
    version: str
    arch: str
    publisher: str
    is_framework: bool
    is_resource: bool
    is_store: bool
    location: str
    status: str
    removable: bool
    is_bundle: bool = False

    @property
    def vt(self) -> tuple:
        return vtuple(self.version)


def installed() -> list[Installed]:
    r = ps("Get-AppxPackage -PackageTypeFilter Main, Framework, Bundle | ForEach-Object { [pscustomobject]@{ n=$_.Name;"
           " f=$_.PackageFullName; fam=$_.PackageFamilyName; v=$_.Version; a=\"$($_.Architecture)\"; p=$_.Publisher;"
           " fw=$_.IsFramework; res=$_.IsResourcePackage; b=$_.IsBundle; sk=\"$($_.SignatureKind)\"; loc=$_.InstallLocation;"
           " st=\"$($_.Status)\"; nr=$_.NonRemovable } } | ConvertTo-Json -Compress -Depth 2", timeout=120)
    data = json.loads(r.stdout or "[]")
    if isinstance(data, dict):
        data = [data]
    return [Installed(name=d["n"], full_name=d["f"], family=d["fam"], version=d["v"], arch=(d["a"] or "").lower(),
                      publisher=d["p"], is_framework=bool(d["fw"]), is_resource=bool(d["res"]), is_store=d["sk"] == "Store",
                      location=d["loc"] or "", status=d["st"], removable=not d["nr"], is_bundle=bool(d["b"])) for d in data]


def newest(pkgs: list[Installed], name: str) -> Installed | None:
    mine = [p for p in pkgs if p.name.lower() == name.lower() and not p.is_bundle]
    native = [p for p in mine if p.arch in (ARCH, "neutral")] or mine
    return max(native, key=lambda p: p.vt, default=None)


# ----------------------------------------------------------------------------- manifest info

@dataclass
class AppEntry:
    app_id: str
    display_name: str
    logo: str | None


def manifest_apps(location: str) -> list[AppEntry]:
    """Launchable entries + logo of an installed package (read straight from its AppxManifest.xml)."""
    path = Path(location) / "AppxManifest.xml"
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return []
    props_logo = root.find("{*}Properties/{*}Logo")
    out = []
    for app in root.findall("{*}Applications/{*}Application"):
        ve = app.find("{*}VisualElements")
        if ve is not None and ve.get("AppListEntry") == "none":
            continue
        logo = (ve.get("Square44x44Logo") or ve.get("Square150x150Logo")) if ve is not None else None
        logo = logo or (props_logo.text if props_logo is not None else None)
        out.append(AppEntry(app.get("Id", ""), (ve.get("DisplayName") if ve is not None else "") or "",
                            _resolve_logo(location, logo)))
    return out


def _resolve_logo(location: str, rel: str | None) -> str | None:
    if not rel:
        return None
    p = Path(location) / rel
    if p.exists():
        return str(p)
    cands = sorted(p.parent.glob(p.stem + "*" + p.suffix)) if p.parent.exists() else []
    pref = [c for c in cands if "targetsize-48" in c.name or "scale-200" in c.name]
    return str((pref or cands)[0]) if cands else None


def launch(family: str, app_id: str) -> None:
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{family}!{app_id}"], creationflags=NO_WINDOW)


def running(location: str) -> list[psutil.Process]:
    if not location:
        return []
    root = os.path.normcase(location.rstrip("\\") + "\\")
    out = []
    for p in psutil.process_iter(["exe"]):
        exe = p.info.get("exe")
        if exe and os.path.normcase(exe).startswith(root):
            out.append(p)
    return out


# ----------------------------------------------------------------------------- package files

def publisher_id(publisher: str) -> str:
    """The 13-char publisher hash used in package family names (e.g. 8wekyb3d8bbwe for Microsoft)."""
    digest = hashlib.sha256(publisher.encode("utf-16-le")).digest()[:8]
    bits = "".join(f"{b:08b}" for b in digest) + "0"
    alphabet = "0123456789abcdefghjkmnpqrstvwxyz"
    return "".join(alphabet[int(bits[i:i + 5], 2)] for i in range(0, 65, 5))


@dataclass
class Dependency:
    name: str
    min_version: tuple
    publisher: str

    @property
    def family(self) -> str:
        return f"{self.name}_{publisher_id(self.publisher)}"


def package_dependencies(path: Path, arch: str = ARCH) -> list[Dependency]:
    """Framework dependencies declared by a .msix/.appx or the matching package inside a bundle."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "AppxMetadata/AppxBundleManifest.xml" in names:
            bm = ET.fromstring(z.read("AppxMetadata/AppxBundleManifest.xml"))
            # skip stub packages (AppxMetadata\Stub\...) - placeholders, not the real app
            pkgs = [p for p in bm.iter() if p.tag.endswith("}Package") and p.get("Type", "application") == "application"
                    and "stub" not in (p.get("FileName") or "").replace("\\", "/").lower().split("/")[:-1]]
            # explicit "is None" checks: an XML element with no children is falsy, so `or` would skip a real match
            pick = next((p for p in pkgs if (p.get("Architecture") or "").lower() == arch), None)
            if pick is None:
                pick = next((p for p in pkgs if (p.get("Architecture") or "").lower() == "neutral"), None)
            if pick is None and pkgs:
                pick = pkgs[0]
            if pick is None:
                return []
            inner_name = pick.get("FileName").replace("\\", "/")
            if inner_name not in names:
                return []   # can't see inside: let Windows' installer report any missing dependency itself
            with zipfile.ZipFile(io.BytesIO(z.read(inner_name))) as inner:
                manifest = inner.read("AppxManifest.xml")
        else:
            manifest = z.read("AppxManifest.xml")
    root = ET.fromstring(manifest)
    return [Dependency(d.get("Name"), vtuple(d.get("MinVersion", "0")), d.get("Publisher", ""))
            for d in root.iter() if d.tag.endswith("}PackageDependency")]


def is_framework_package(path: Path) -> bool:
    """A framework (shared runtime) package rather than an app - those install first."""
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("AppxManifest.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return False
    fw = root.find("{*}Properties/{*}Framework")
    return fw is not None and (fw.text or "").strip().lower() == "true"


def dn(s: str) -> dict[str, str]:
    """'CN=Microsoft Corporation, O="Contoso, Ltd", C=US' -> {'CN': ..., 'O': 'Contoso, Ltd', 'C': 'US'}."""
    out = {}
    for m in re.finditer(r'\s*([A-Za-z0-9.]+)=("(?:[^"]|"")*"|[^,]*)\s*(?:,|$)', s or ""):
        v = m.group(2).strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1].replace('""', '"')
        out.setdefault(m.group(1).upper(), v)
    return out


MS = "Microsoft Corporation"
# Microsoft's own package/code-signing CAs. Exact names on purpose: Microsoft also runs CAs that sign other people's
# code ("Microsoft ID Verified ..."), so "the issuer mentions Microsoft" is not enough.
MS_CODE_CAS = {"Microsoft Code Signing PCA", "Microsoft Code Signing PCA 2010", "Microsoft Code Signing PCA 2011",
               "Microsoft Code Signing PCA 2024", "Microsoft Windows Production PCA 2011", "Microsoft Windows PCA 2010",
               "Microsoft Windows Third Party Component CA 2012", "Microsoft Windows Third Party Component CA 2014"}


def _marketplace(issuer: dict) -> bool:
    return issuer.get("O") == MS and re.fullmatch(r"Microsoft Marketplace CA( G \d+)?", issuer.get("CN", "")) is not None


def signature_trusted(status: str, signer: str, issuer: str, expected_publisher: str | None) -> bool:
    s, i = dn(signer), dn(issuer)
    if status != "Valid":
        return False
    store_signed = _marketplace(i)
    ms_signed = i.get("O") == MS and i.get("CN") in MS_CODE_CAS and s.get("O") == MS
    if expected_publisher:   # update: Store-signed for the same publisher as the copy already installed, or Microsoft
        return (store_signed and dn(expected_publisher) == s) or ms_signed or (store_signed and s.get("O") == MS)
    return store_signed or ms_signed    # new install: the Store signed it, or Microsoft itself did


def verify_signature(path: Path, expected_publisher: str | None) -> tuple[bool, str]:
    r = ps(f"$s = Get-AuthenticodeSignature -LiteralPath {q(path)}; [pscustomobject]@{{ st=\"$($s.Status)\";"
           " sub=$s.SignerCertificate.Subject; iss=$s.SignerCertificate.Issuer } | ConvertTo-Json -Compress", timeout=120)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return False, f"could not read signature: {r.stderr.strip()[:200]}"
    signer, issuer = d.get("sub") or "", d.get("iss") or ""
    ok = signature_trusted(d.get("st") or "", signer, issuer, expected_publisher)
    return ok, f"{d.get('st')} signer={signer.split(',')[0]} issuer={issuer.split(',')[0]}"


def authenticode_valid(path: Path) -> tuple[bool, str]:
    """Any valid, trusted Authenticode signature (desktop installers from other publishers)."""
    r = ps(f"$s = Get-AuthenticodeSignature -LiteralPath {q(path)}; \"$($s.Status)|$($s.SignerCertificate.Subject)\"",
           timeout=120)
    st, _, signer = (r.stdout or "").strip().partition("|")
    return st == "Valid", f"{st or 'unknown'} signer={signer.split(',')[0]}"


# ----------------------------------------------------------------------------- actions

def _run(script: str, timeout: float) -> tuple[bool, str]:
    try:
        r = ps(script + "; 'OK'", timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT after {int(timeout)}s - Windows' installer is probably jammed"
    out = (r.stdout or "").strip()
    if r.returncode == 0 and out.endswith("OK"):
        return True, ""
    err = (r.stderr or out).strip()
    return False, err[:1500]


def install(path: Path, deps: list[Path] | None = None, close_app: bool = False, timeout: float = 900,
            volume_args: str = "") -> tuple[bool, str]:
    dep = f" -DependencyPath {','.join(q(d) for d in deps)}" if deps else ""
    force = " -ForceApplicationShutdown" if close_app else ""
    return _run(f"$ErrorActionPreference='Stop'; Add-AppxPackage -Path {q(path)}{dep} -ForceUpdateFromAnyVersion{force}"
                f"{volume_args}", timeout)


def repair(pkg: Installed, timeout: float = 600) -> tuple[bool, str]:
    return _run(f"$ErrorActionPreference='Stop'; Add-AppxPackage -Register {q(Path(pkg.location) / 'AppxManifest.xml')}"
                " -DisableDevelopmentMode -ForceApplicationShutdown", timeout)


def reset(pkg: Installed, timeout: float = 300) -> tuple[bool, str]:
    return _run(f"$ErrorActionPreference='Stop'; Reset-AppxPackage -Package {q(pkg.full_name)}", timeout)


def uninstall(pkg: Installed, timeout: float = 600) -> tuple[bool, str]:
    return _run(f"$ErrorActionPreference='Stop'; Remove-AppxPackage -Package {q(pkg.full_name)}", timeout)
