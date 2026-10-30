"""Storely - a Microsoft Store replacement: Microsoft's own catalog + delivery servers, our own queue."""

import os
import sys
from pathlib import Path

import truststore

# Microsoft's delivery servers chain to Microsoft roots that are in Windows' certificate store but not in
# Python's bundled list - verify against Windows' store (still full certificate checking).
truststore.inject_into_ssl()

APP_NAME = "Storely"
__version__ = "1.3.0"
APP_ID = "Storely.App"     # Windows AppUserModelID: groups the taskbar button under our icon
FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
RES_DIR = Path(getattr(sys, "_MEIPASS", ROOT))
ICON_FILE = RES_DIR / "assets" / "icon.ico"
_LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
DATA_DIR = _LOCAL / "Storely"
OLD_DATA_DIRS = (_LOCAL / "Unjammed", _LOCAL / "MyStore")      # this app's earlier names, newest first
CACHE_DIR = DATA_DIR / "cache"
DOWNLOAD_DIR = DATA_DIR / "downloads"
ROLLBACK_DIR = DATA_DIR / "rollback"
LOG_FILE = DATA_DIR / "storely.log"
def _known_folder(guid: str) -> str:
    """A Windows folder straight from Windows (not from environment variables, which the user can change - the
    admin helper must not be steered by them)."""
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]
    u = uuid.UUID(guid)
    g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    out = ctypes.c_wchar_p()
    shell32 = ctypes.WinDLL("shell32")
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                                             ctypes.POINTER(ctypes.c_wchar_p)]
    try:
        if shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) != 0:
            return ""
        return out.value or ""
    finally:
        ctypes.WinDLL("ole32").CoTaskMemFree(out)


def _system_dir() -> str:
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    return buf.value if ctypes.WinDLL("kernel32").GetSystemDirectoryW(buf, 260) else ""


SYSTEM32 = Path(_system_dir() or r"C:\Windows\System32")
PROGRAM_FILES = Path(_known_folder("905e63b6-c1bf-494e-b29c-65b732d3d21a") or r"C:\Program Files")
PROGRAM_DATA = Path(_known_folder("62ab5d82-fdc1-4dc3-a9dd-070d1d495d97") or r"C:\ProgramData")
# admin/SYSTEM work area: only SYSTEM + Administrators can write here (see secure.ensure_protected_dir)
MACHINE_DIR = PROGRAM_DATA / "Storely"
RESULTS_DIR = MACHINE_DIR / "results"


def _migrate() -> None:
    """Carry settings, history, holds and wishlist over from the old name (the whole folder if nothing has it
    open, else a copy of everything but the log)."""
    import shutil
    old = next((d for d in OLD_DATA_DIRS if d.is_dir()), None)
    if old is None:
        return
    if not DATA_DIR.exists():
        try:
            old.rename(DATA_DIR)
            return
        except OSError:      # the old app still has it open: copy what matters instead
            pass
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # only the user's own records - never downloads, rollback copies or caches (can be gigabytes, all re-creatable),
    # and never over something Storely already has
    for name in MIGRATE_FILES:
        src, dst = old / name, DATA_DIR / name
        if src.is_file() and not dst.exists():
            shutil.copy2(src, dst)


MIGRATE_FILES = ("settings.json", "history.json", "changelog.json", "desktop_apps.json", "removed.json", "volume.json",
                 "queue.json")


try:
    _migrate()
except OSError:
    pass
for _d in (DATA_DIR, CACHE_DIR, DOWNLOAD_DIR, ROLLBACK_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def launcher(*args: str) -> list[str]:
    """Command line that starts this copy of Storely with `args` (installed exe, or python + main.py from source)."""
    if FROZEN:
        return [sys.executable, *args]
    return [sys.executable, str(ROOT / "main.py"), *args]
