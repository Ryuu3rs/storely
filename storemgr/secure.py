"""Who can change a file or folder? Used to make sure admin/SYSTEM work only ever runs code and reads results that
standard users cannot tamper with (installed copy under Program Files, protected ProgramData folder)."""

from __future__ import annotations

import ctypes
import os
import re
import time
from ctypes import wintypes
from pathlib import Path

_adv = ctypes.WinDLL("advapi32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

_adv.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_adv.GetNamedSecurityInfoW.restype = wintypes.DWORD
_adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
_adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
_k32.LocalFree.argtypes = [ctypes.c_void_p]
_k32.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]

SE_FILE_OBJECT = 1
OWNER_SECURITY_INFORMATION, DACL_SECURITY_INFORMATION = 0x1, 0x4
SDDL_REVISION_1 = 1
FILE_ATTRIBUTE_REPARSE_POINT = 0x400

SYSTEM, ADMINS = "S-1-5-18", "S-1-5-32-544"
TRUSTED_INSTALLER = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
TRUSTED = {SYSTEM, ADMINS, TRUSTED_INSTALLER}
_ALIASES = {"SY": SYSTEM, "BA": ADMINS, "AU": "S-1-5-11", "BU": "S-1-5-32-545", "WD": "S-1-1-0", "IU": "S-1-5-4",
            "CO": "S-1-3-0", "OW": "S-1-3-4", "AC": "S-1-15-2-1"}
_RIGHTS = {"GA": 0x10000000, "GW": 0x40000000, "GR": 0x80000000, "GX": 0x20000000, "RC": 0x20000, "SD": 0x10000,
           "WD": 0x40000, "WO": 0x80000, "FA": 0x1F01FF, "FR": 0x120089, "FW": 0x120116, "FX": 0x1200A0,
           "CC": 0x1, "DC": 0x2, "LC": 0x4, "SW": 0x8, "RP": 0x10, "WP": 0x20, "DT": 0x40, "LO": 0x80, "CR": 0x100}
# write data / append (= add file / add folder), write EA, delete child, delete, change permissions, take ownership
WRITE_MASK = 0x2 | 0x4 | 0x10 | 0x40 | 0x10000 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000

# owner Administrators; SYSTEM + Administrators full; Users read; inheritance from ProgramData blocked
PROTECTED_SDDL = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)"
_ACE = re.compile(r"\(([^;()]*);([^;()]*);([^;()]*);[^;()]*;[^;()]*;([^;()]*)(?:;[^()]*)?\)")


def _sddl(path: str | Path) -> str:
    psd = ctypes.c_void_p()
    err = _adv.GetNamedSecurityInfoW(str(path), SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                                     None, None, None, None, ctypes.byref(psd))
    if err:
        raise OSError(err, f"can't read permissions of {path}")
    try:
        s = wintypes.LPWSTR()
        if not _adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                psd, SDDL_REVISION_1, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION, ctypes.byref(s), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return s.value
        finally:
            _k32.LocalFree(s)
    finally:
        _k32.LocalFree(psd)


def _sid(token: str) -> str:
    return _ALIASES.get(token, token)


def _mask(rights: str) -> int:
    if rights.lower().startswith("0x"):
        return int(rights, 16)
    return sum(_RIGHTS.get(rights[i:i + 2], 0) for i in range(0, len(rights), 2))


def untrusted_writers(path: str | Path) -> list[str]:
    """Accounts other than SYSTEM / Administrators / TrustedInstaller that can change `path` (or own it).
    Empty list = only admins can change it."""
    return writers_in(_sddl(path))


def writers_in(sddl: str) -> list[str]:
    out = []
    owner = re.match(r"O:([^:]+?)(?=[DGS]:|$)", sddl)
    if owner and _sid(owner.group(1)) not in TRUSTED:
        out.append(f"owner {_sid(owner.group(1))}")
    dacl = sddl[sddl.find("D:"):] if "D:" in sddl else ""
    if not dacl or dacl.startswith("D:NO_ACCESS_CONTROL"):
        return out + ["no permissions set (everyone has full access)"]
    for kind, flags, rights, sid in _ACE.findall(dacl):
        if kind != "A" or "IO" in flags:      # deny entries / inherit-only entries don't grant anything here
            continue
        who = _sid(sid)
        if who not in TRUSTED and _mask(rights) & WRITE_MASK:
            out.append(who)
    return out


def is_reparse(path: str | Path) -> bool:
    try:
        return bool(os.lstat(path).st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def protected(path: str | Path) -> bool:
    p = Path(path)
    return p.exists() and not is_reparse(p) and not untrusted_writers(p)


def ensure_protected_dir(path: Path) -> list[str]:
    """Create `path` so only SYSTEM/Administrators can write to it (must run elevated). A folder that is already
    there but could have been tampered with (pre-created by a standard user, junction, loose permissions) is moved
    aside untouched - never deleted - and a fresh one made. Returns what was done."""
    notes = []
    if path.exists() or is_reparse(path):
        if protected(path):
            return notes
        aside = path.with_name(f"{path.name}.untrusted-{time.strftime('%Y%m%d-%H%M%S')}")
        os.rename(path, aside)
        notes.append(f"moved an unsafe {path} aside to {aside}")
    psd = ctypes.c_void_p()
    if not _adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(PROTECTED_SDDL, SDDL_REVISION_1, ctypes.byref(psd), None):
        raise ctypes.WinError(ctypes.get_last_error())

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", wintypes.BOOL)]

    try:
        sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), psd, False)
        if not _k32.CreateDirectoryW(str(path), ctypes.byref(sa)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        _k32.LocalFree(psd)
    if not protected(path):
        raise PermissionError(f"{path} was created but is not protected: {untrusted_writers(path)}")
    return notes
