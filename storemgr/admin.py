"""Admin actions through one UAC prompt. The elevated side is this same program (storemgr.helper) - no scripts are
written or run from disk - and it is only ever started from a copy that standard users can't modify (the installed
one under Program Files). Results come back through a folder only SYSTEM/Administrators can write to."""

from __future__ import annotations

import ctypes
import json
import secrets
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from . import FROZEN, RESULTS_DIR, ROOT, launcher, secure
from .winapps import FAMILY_RE

ERROR_CANCELLED = 1223
WAIT_TIMEOUT = 0x102
SEE_MASK_NOCLOSEPROCESS, SEE_MASK_FLAG_NO_UI = 0x40, 0x400


class _SEI(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SEI)]
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]


def code_locations() -> list[Path]:
    if FROZEN:
        exe = Path(sys.executable)
        return [exe, exe.parent, Path(getattr(sys, "_MEIPASS", exe.parent)), exe.parent.parent]
    return [Path(sys.executable), ROOT, ROOT / "main.py", ROOT / "storemgr"]


def untrusted_code() -> list[str]:
    """Why this copy must not be run as admin/SYSTEM (empty = safe: only admins can change its files)."""
    bad = []
    for p in code_locations():
        try:
            who = secure.untrusted_writers(p)
        except OSError as e:
            who = [str(e)]
        if who or secure.is_reparse(p):
            bad.append(f"{p} ({', '.join(who) or 'link'})")
    return bad


def _fail(msg: str) -> dict:
    return {"ok": False, "steps": [], "errors": [msg]}


def _elevated(action: str, *args: str, timeout: float = 300) -> dict:
    bad = untrusted_code()
    if bad:
        return _fail("Admin actions only run from the installed Unjammed, because this copy's files can be changed "
                     f"without admin rights: {bad[0]}")
    job = secrets.token_hex(16)
    cmd = launcher("--elevated", action, "--job", job, *args)
    ole32 = ctypes.WinDLL("ole32")
    co = ole32.CoInitializeEx(None, 0x2 | 0x4)    # ShellExecuteEx wants COM on the calling thread
    try:
        sei = _SEI(cbSize=ctypes.sizeof(_SEI), fMask=SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI, lpVerb="runas",
                   lpFile=cmd[0], lpParameters=subprocess.list2cmdline(cmd[1:]), lpDirectory=str(ROOT), nShow=0)
        if not _shell32.ShellExecuteExW(ctypes.byref(sei)):
            err = ctypes.get_last_error()
            return _fail("cancelled at the admin prompt" if err == ERROR_CANCELLED else f"couldn't start the admin helper ({err})")
    finally:
        if co in (0, 1):
            ole32.CoUninitialize()
    try:
        if _k32.WaitForSingleObject(sei.hProcess, int(timeout * 1000)) == WAIT_TIMEOUT:
            return _fail("timed out")
        code = wintypes.DWORD()
        _k32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    finally:
        _k32.CloseHandle(sei.hProcess)
    out = RESULTS_DIR / f"{job}.json"
    if not out.exists():
        return _fail(f"the admin helper ended without a result (exit code {code.value})")
    if not secure.protected(RESULTS_DIR) or secure.untrusted_writers(out):
        return _fail(f"ignored the admin helper's result: {RESULTS_DIR} is not protected")
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _fail(f"unreadable result from the admin helper: {e}")


def unjam(family: str | None = None) -> dict:
    if family and not FAMILY_RE.match(family):
        return _fail(f"not a Windows app family name: {family!r}")
    return _elevated("unjam", *(["--family", family] if family else []))


def install(path: Path, deps: list[Path] | None = None, close_app: bool = False, publisher: str | None = None) -> dict:
    args = ["--path", str(path)]
    for d in deps or []:
        args += ["--dep", str(d)]
    if close_app:
        args.append("--close")
    if publisher:
        args += ["--publisher", publisher]
    return _elevated("install", *args, timeout=1800)


def cleanup() -> dict:
    return _elevated("cleanup", timeout=600)


def store_auto_updates(enabled: bool) -> dict:
    return _elevated("store-auto-update", "--value", "on" if enabled else "off", timeout=120)


def app_volume(drive: str) -> dict:
    """Add a drive for Store apps (if needed) and make it Windows' default install drive."""
    if not isinstance(drive, str) or len(drive) != 1 or not ("A" <= drive <= "Z"):
        return _fail(f"not a drive letter: {drive!r}")
    return _elevated("app-volume", "--drive", drive, timeout=600)


def store_auto_updates_off() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\WindowsStore") as k:
            return winreg.QueryValueEx(k, "AutoDownload")[0] == 2
    except OSError:
        return False
