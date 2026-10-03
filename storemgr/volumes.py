"""Which drive Store apps install to, and moving installed apps between drives.

What needs admin (checked on Windows 11 24H2 from a normal, non-elevated window):
  Get-AppxVolume / Get-AppxDefaultVolume   no admin
  Add-AppxVolume (a new drive)             admin (Microsoft docs: "The caller must be a member of the administrators group")
  Mount-AppxVolume                         admin (0x80070005 Access is denied)
  Set-AppxDefaultVolume                    admin - and without it the cmdlet reports success but Windows' deployment
                                           log shows 0x80070005, so the result is always re-read
  Move-AppxPackage                         runs as the user (the deployment service accepts and runs it); apps that
                                           came with Windows can't be moved (0x80073D0B)
Windows identifies volumes by their volume GUID, and a stale record can carry another disk's GUID (here an old J:
record carries G:'s), so volumes are matched by store path and checked against the drive's real GUID."""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
from dataclasses import dataclass

from . import DATA_DIR
from .winapps import ps, q

PREF_FILE = DATA_DIR / "volume.json"
DRIVE_RE = re.compile(r"\A([A-Za-z]):?\\?\Z")
FULL_NAME_RE = re.compile(r"\A[A-Za-z0-9.\-]{3,50}_\d{1,5}(\.\d{1,5}){3}_(x86|x64|arm|arm64|neutral)_[A-Za-z0-9.\-~]{0,30}"
                          r"_[0-9a-hjkmnp-tv-z]{13}\Z")
DRIVE_REMOVABLE, DRIVE_FIXED = 2, 3

_ERRORS = {
    "0x80073D0B": "Windows can't move apps that came with Windows",
    "0x80070005": "Windows needs admin rights for this",
    "0x80073D02": "The app is open - close it and try again",
    "0x80070070": "Not enough free space on that drive",
}


@dataclass
class Volume:
    name: str           # \\?\Volume{guid} as Windows' app installer knows it
    path: str           # package store, e.g. F:\WindowsApps or C:\Program Files\WindowsApps
    drive: str          # "F" ("" when mounted without a letter)
    is_default: bool
    is_offline: bool
    is_system: bool
    wrong_disk: bool = False      # the record's GUID isn't the disk now at that letter: a stale record
    free: int | None = None
    total: int | None = None

    @property
    def usable(self) -> bool:
        return not self.is_offline and not self.wrong_disk

    @property
    def label(self) -> str:
        return f"{self.drive}:" if self.drive else self.path


def drive_letter(value: str) -> str:
    """'g', 'G:', 'G:\\' -> 'G'; anything else raises ValueError."""
    m = DRIVE_RE.match(value or "")
    if not m:
        raise ValueError(f"not a drive letter: {value!r}")
    return m.group(1).upper()


def _drive_of(path: str) -> str:
    m = re.match(r"\A([A-Za-z]):\\", path or "")
    return m.group(1).upper() if m else ""


def volume_guid(letter: str) -> str | None:
    """The real \\\\?\\Volume{guid} of the disk at a drive letter (None when there's no disk there)."""
    buf = ctypes.create_unicode_buffer(64)
    if not ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(f"{letter}:\\", buf, len(buf)):
        return None
    return buf.value.rstrip("\\")


def _usage(letter: str) -> tuple[int | None, int | None]:
    try:
        u = shutil.disk_usage(f"{letter}:\\")
        return u.free, u.total
    except OSError:
        return None, None


def parse(raw: str, guid_of=volume_guid, usage=_usage) -> list[Volume]:
    """Volumes from the JSON written by volumes()' PowerShell (list of {n, p, off, sys, d})."""
    data = json.loads(raw or "[]")
    if isinstance(data, dict):
        data = [data]
    out = []
    for d in data:
        name, path = str(d.get("n") or ""), str(d.get("p") or "")
        drive = _drive_of(path)
        off = bool(d.get("off"))
        real = guid_of(drive) if drive else None
        wrong = bool(drive and real and name and real.lower() != name.rstrip("\\").lower())
        free, total = usage(drive) if drive and not off and not wrong else (None, None)
        out.append(Volume(name, path, drive, bool(d.get("d")), off, bool(d.get("sys")), wrong, free, total))
    return out


_LIST = ("$d = (Get-AppxDefaultVolume).PackageStorePath; ConvertTo-Json -Compress -InputObject @(Get-AppxVolume |"
         " ForEach-Object { [pscustomobject]@{ n=$_.Name; p=$_.PackageStorePath; off=[bool]$_.IsOffline;"
         " sys=[bool]$_.IsSystemVolume; d=($_.PackageStorePath -eq $d) } })")


def volumes() -> list[Volume]:
    r = ps(_LIST, timeout=60)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300] or "Get-AppxVolume failed")
    return parse(r.stdout)


def default(vols: list[Volume] | None = None) -> Volume | None:
    return next((v for v in (vols if vols is not None else volumes()) if v.is_default), None)


def for_drive(letter: str, vols: list[Volume]) -> Volume | None:
    """The usable volume on a drive (records pointing at another disk are ignored)."""
    letter = drive_letter(letter)
    return next((v for v in vols if v.drive == letter and v.usable), None)


def check_drive(letter: str) -> str:
    """Why a drive can't hold Store apps ('' = it can): must be a local NTFS disk."""
    letter = drive_letter(letter)
    kind = ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\")
    if kind not in (DRIVE_FIXED, DRIVE_REMOVABLE):
        return f"{letter}: is not a local disk"
    fs = ctypes.create_unicode_buffer(32)
    if not ctypes.windll.kernel32.GetVolumeInformationW(f"{letter}:\\", None, 0, None, None, None, fs, len(fs)):
        return f"{letter}: can't be read"
    if fs.value.upper() != "NTFS":
        return f"{letter}: is {fs.value or 'not formatted'} - Store apps need an NTFS drive"
    return ""


def _err(text: str) -> str:
    for code, msg in _ERRORS.items():
        if code.lower() in text.lower():
            return f"{msg} ({code})"
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), text)
    return first[:300]


def _run(script: str, timeout: float) -> tuple[bool, str]:
    r = ps("$ErrorActionPreference='Stop'; " + script + "; 'OK'", timeout=timeout)
    out = (r.stdout or "").strip()
    if r.returncode == 0 and out.endswith("OK"):
        return True, ""
    return False, (r.stderr or out).strip()[:1500]


# ----------------------------------------------------------------------------- default install drive (admin)

def add_and_set_default(letter: str) -> tuple[bool, str]:
    """Make a drive Windows' default for new Store apps. Needs admin (one UAC prompt)."""
    try:
        letter = drive_letter(letter)
    except ValueError as e:
        return False, str(e)
    why = check_drive(letter)
    if why:
        return False, why
    vols = volumes()
    cur = default(vols)
    if cur and cur.drive == letter and cur.usable:
        return True, f"New apps already install to {letter}:"
    if any(v.drive == letter and v.wrong_disk for v in vols) and not for_drive(letter, vols):
        return False, (f"Windows has an out-of-date app-storage record for {letter}: that points at a different disk. "
                       "Remove it in Settings > System > Storage > Advanced storage settings > "
                       "Where new content is saved, then try again")
    from . import admin
    r = admin.app_volume(letter)
    if not r.get("ok"):
        return False, "; ".join(r.get("errors", [])) or "couldn't change the install drive"
    return True, f"New apps will install to {letter}:"


def apply_default(letter: str) -> list[str]:
    """The admin side of add_and_set_default (run by storemgr.helper). Returns steps; raises on failure."""
    letter = drive_letter(letter)
    why = check_drive(letter)
    if why:
        raise ValueError(why)
    steps = []
    vols = volumes()
    target = for_drive(letter, vols)
    if target is None:
        if any(v.drive == letter for v in vols):
            raise RuntimeError(f"{letter}: has an out-of-date app-storage record for another disk")
        store = f"{letter}:\\WindowsApps"
        ok, err = _run(f"Add-AppxVolume -Path {q(store)} | Out-Null", 300)
        if not ok:
            raise RuntimeError(f"couldn't add {letter}: for apps: {_err(err)}")
        steps.append(f"added {store}")
        vols = volumes()
        target = for_drive(letter, vols)
        if target is None:
            raise RuntimeError(f"Windows didn't register {letter}: for apps")
    if target.is_offline:
        ok, err = _run(f"Mount-AppxVolume -Volume {q(target.path)}", 300)
        if not ok:
            raise RuntimeError(f"couldn't bring {letter}: online: {_err(err)}")
        steps.append(f"mounted {target.path}")
    ok, err = _run(f"Set-AppxDefaultVolume -Volume {q(target.path)}", 120)
    now = default()
    if not ok or not now or now.path.lower() != target.path.lower():
        raise RuntimeError(f"Windows didn't accept {letter}: as the install drive: {_err(err) if err else 'unchanged'}")
    steps.append(f"default install drive: {target.path}")
    return steps


# ----------------------------------------------------------------------------- moving an installed app (no admin)

def move(full_name: str, volume_path: str, timeout: float = 3600) -> tuple[bool, str]:
    """Move an installed app (and its data) to another app drive Windows already knows about."""
    if not FULL_NAME_RE.match(full_name or ""):
        return False, f"not a Windows app package name: {full_name!r}"
    vols = volumes()
    target = next((v for v in vols if v.path.lower() == (volume_path or "").lower()), None)
    if target is None or not target.usable:
        return False, f"{volume_path} is not an app drive Windows can use right now"
    r = ps(f"(Get-AppxPackage | Where-Object PackageFullName -eq {q(full_name)}).InstallLocation", timeout=60)
    before = (r.stdout or "").strip()
    if not before:
        return False, "that app isn't installed for this user"
    if _drive_of(before) == target.drive:
        return True, f"already on {target.label}"
    ok, err = _run(f"Move-AppxPackage -Package {q(full_name)} -Volume {q(target.path)}", timeout)
    if not ok:
        return False, _err(err)
    r = ps(f"(Get-AppxPackage | Where-Object PackageFullName -eq {q(full_name)}).InstallLocation", timeout=60)
    after = (r.stdout or "").strip()
    if _drive_of(after) != target.drive:
        return False, f"Windows reported success but the app is still at {after or before}"
    return True, f"moved to {target.label}"


# ----------------------------------------------------------------------------- Storely's own install target

def preferred(vols: list[Volume] | None = None) -> Volume | None:
    """The drive the user picked in Storely for new installs (None = Windows' default)."""
    try:
        path = json.loads(PREF_FILE.read_text(encoding="utf-8")).get("path") or ""
    except (OSError, ValueError, AttributeError):
        return None
    if not path:
        return None
    return next((v for v in (vols if vols is not None else volumes()) if v.path.lower() == path.lower()), None)


def set_preferred(volume_path: str | None) -> None:
    """Pick one of Windows' app drives for Storely's fresh installs (None = follow Windows' default)."""
    if volume_path:
        v = next((v for v in volumes() if v.path.lower() == volume_path.lower()), None)
        if v is None or not v.usable:
            raise ValueError(f"{volume_path} is not an app drive Windows can use right now")
        volume_path = v.path
    tmp = PREF_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"path": volume_path or ""}), encoding="utf-8")
    os.replace(tmp, PREF_FILE)


def install_args(vols: list[Volume] | None = None) -> str:
    """' -Volume <path>' for Add-AppxPackage when the user picked a drive other than Windows' default, else ''."""
    try:
        vols = vols if vols is not None else volumes()
    except (RuntimeError, OSError, ValueError):
        return ""
    v = preferred(vols)
    if v is None or not v.usable or v.is_default:
        return ""
    return f" -Volume {q(v.path)}"
