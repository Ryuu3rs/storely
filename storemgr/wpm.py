"""Store apps that ship as normal desktop installers (Discord, Teams, Zoom...): install and update them using the
Store's own install recipe (packageManifests) - right installer for this PC, SHA-256 checked, run silently."""

from __future__ import annotations

import json
import re
import subprocess
import threading
import winreg
from dataclasses import dataclass, field

from . import DATA_DIR, DOWNLOAD_DIR, winapps
from .download import fetch
from .fe3 import vtuple
from .winapps import ARCH, NO_WINDOW

TRACK_FILE = DATA_DIR / "desktop_apps.json"
SILENT_DEFAULTS = {"inno": "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-", "nullsoft": "/S",
                   "burn": "/quiet /norestart", "exe": ""}
OK_CODES = {0, 3010, 1641}


@dataclass
class Installer:
    url: str
    sha256: str
    kind: str
    arch: str
    scope: str
    silent: str
    product_code: str = ""
    success_codes: set = field(default_factory=set)


@dataclass
class DesktopApp:
    product_id: str
    title: str
    publisher: str
    version: str
    installer: Installer | None
    names: list               # display names the app registers under in "Installed apps"
    agreements: list          # [(label, text, url)]
    installed_version: str = ""
    error: str = ""

    @property
    def update_available(self) -> bool:
        return bool(self.installed_version and self.version and vtuple(_num(self.version)) > vtuple(_num(self.installed_version)))


def _num(v: str) -> str:
    return ".".join(re.findall(r"\d+", v or "")[:4]) or "0"


def resolve(browse, product_id: str, market: str = "GB") -> DesktopApp:
    data = browse.manifest(product_id)
    v = (data.get("Versions") or [{}])[0]
    loc = v.get("DefaultLocale") or {}
    inst = _pick(v.get("Installers") or [], market)
    names = [loc.get("PackageName") or ""]
    for i in v.get("Installers") or []:
        for e in i.get("AppsAndFeaturesEntries") or []:
            if e.get("DisplayName"):
                names.append(e["DisplayName"])
    agreements = [(a.get("AgreementLabel") or "", a.get("Agreement") or "", a.get("AgreementUrl") or "")
                  for a in loc.get("Agreements") or []]
    app = DesktopApp(product_id, loc.get("PackageName") or product_id, loc.get("Publisher") or "",
                     v.get("PackageVersion") or "", inst, [n for n in dict.fromkeys(names) if n], agreements)
    if not inst:
        app.error = "no installer for this PC in the Store's recipe"
    app.installed_version = installed_version(app)
    return app


def _pick(installers: list, market: str) -> Installer | None:
    allowed = ("x64", "x86", "neutral") if ARCH == "x64" else (ARCH, "x64", "x86", "neutral")

    def ok_market(i):
        m = i.get("Markets") or {}
        if m.get("AllowedMarkets"):
            return market in m["AllowedMarkets"]
        return market not in (m.get("ExcludedMarkets") or [])

    cands = [i for i in installers if (i.get("Architecture") or "neutral").lower() in allowed and ok_market(i)]
    if not cands:
        return None
    cands.sort(key=lambda i: (allowed.index((i.get("Architecture") or "neutral").lower()),
                              0 if (i.get("Scope") or "user") == "user" else 1,
                              0 if (i.get("InstallerLocale") or "").lower().startswith("en") else 1))
    i = cands[0]
    kind = (i.get("InstallerType") or "exe").lower()
    sw = i.get("InstallerSwitches") or {}
    silent = sw.get("Silent") or sw.get("SilentWithProgress") or SILENT_DEFAULTS.get(kind, "")
    return Installer(url=i.get("InstallerUrl") or "", sha256=(i.get("InstallerSha256") or "").lower(), kind=kind,
                     arch=(i.get("Architecture") or "neutral").lower(), scope=i.get("Scope") or "",
                     silent=silent, product_code=i.get("ProductCode") or "",
                     success_codes=set(i.get("InstallerSuccessCodes") or []))


# ----------------------------------------------------------------------------- what's installed

def _arp_entries():
    roots = [(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in roots:
        try:
            with winreg.OpenKey(hive, path) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    sub = winreg.EnumKey(k, i)
                    try:
                        with winreg.OpenKey(k, sub) as s:
                            def val(n):
                                try:
                                    return str(winreg.QueryValueEx(s, n)[0])
                                except OSError:
                                    return ""
                            yield sub, val("DisplayName"), val("DisplayVersion")
                    except OSError:
                        continue
        except OSError:
            continue


def installed_version(app: DesktopApp) -> str:
    code = (app.installer.product_code if app.installer else "").lower()
    names = [n.lower() for n in app.names]
    for key, name, ver in _arp_entries():
        if code and key.lower() == code:
            return ver or "installed"
        n = name.lower()
        if n and any(n == x or n.startswith(x + " ") for x in names):
            return ver or "installed"
    return ""


# ----------------------------------------------------------------------------- install

def install(app: DesktopApp, report=lambda *a: None, cancel: threading.Event | None = None) -> str:
    inst = app.installer
    if not inst or not inst.url or not inst.sha256:
        raise RuntimeError(app.error or "the Store's recipe has no verifiable installer for this PC")
    ext = {"msi": ".msi", "wix": ".msi", "msix": ".msix", "appx": ".appx"}.get(inst.kind, ".exe")
    dest = DOWNLOAD_DIR / f"{re.sub(r'[^A-Za-z0-9._-]', '_', app.title)}_{_num(app.version)}{ext}"
    report("download", 0, 0, f"Downloading {app.title} {app.version}")
    fetch(inst.url, dest, 0, inst.sha256, algo="sha256", cancel=cancel,
          progress=lambda d, t, s: report("download", d, t, f"{d / 1048576:.0f} / {t / 1048576:.0f} MB  ({s / 1048576:.1f} MB/s)"))
    report("verify", 0, 0, "Checking the installer's signature")
    signed, why = winapps.authenticode_valid(dest)
    if not signed:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"the installer isn't validly signed - deleted ({why})")
    report("install", 0, 0, "Installing (SHA-256 matched the Store's recipe, signature valid)")
    if inst.kind in ("msix", "appx"):
        ok, err = winapps.install(dest, timeout=1800)
        if not ok:
            raise RuntimeError(err)
    else:
        if inst.kind in ("msi", "wix"):
            cmd = [str(winapps.SYSTEM32 / "msiexec.exe"), "/i", str(dest), "/qn", "/norestart"]
        else:
            cmd = f'"{dest}" {inst.silent}'.strip()
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, creationflags=NO_WINDOW)
        if r.returncode not in OK_CODES | inst.success_codes:
            raise RuntimeError(f"installer exited with code {r.returncode}: {(r.stderr or r.stdout or '').strip()[:300]}")
    dest.unlink(missing_ok=True)
    track(app)
    app.installed_version = installed_version(app) or app.version
    report("done", 1, 1, f"Installed {app.installed_version}")
    return app.installed_version


def tracked() -> dict:
    try:
        return json.loads(TRACK_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def track(app: DesktopApp) -> None:
    t = tracked()
    t[app.product_id] = {"title": app.title, "publisher": app.publisher, "names": app.names}
    TRACK_FILE.write_text(json.dumps(t, indent=1), encoding="utf-8")
