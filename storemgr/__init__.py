"""My Store - a Microsoft Store replacement: Microsoft's own catalog + delivery servers, our own queue."""

import os
import sys
from pathlib import Path

import truststore

# Microsoft's delivery servers chain to Microsoft roots that are in Windows' certificate store but not in
# Python's bundled list - verify against Windows' store (still full certificate checking).
truststore.inject_into_ssl()

APP_NAME = "My Store"
__version__ = "1.1.1"
APP_ID = "MyStore.App"     # Windows AppUserModelID: groups the taskbar button under our icon
FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
RES_DIR = Path(getattr(sys, "_MEIPASS", ROOT))
ICON_FILE = RES_DIR / "assets" / "icon.ico"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MyStore"
CACHE_DIR = DATA_DIR / "cache"
DOWNLOAD_DIR = DATA_DIR / "downloads"
ROLLBACK_DIR = DATA_DIR / "rollback"
LOG_FILE = DATA_DIR / "mystore.log"
# admin/SYSTEM work area: only SYSTEM + Administrators can write here (see secure.ensure_protected_dir)
MACHINE_DIR = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "MyStore"
RESULTS_DIR = MACHINE_DIR / "results"
for _d in (DATA_DIR, CACHE_DIR, DOWNLOAD_DIR, ROLLBACK_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def launcher(*args: str) -> list[str]:
    """Command line that starts this copy of My Store with `args` (installed exe, or python + main.py from source)."""
    if FROZEN:
        return [sys.executable, *args]
    return [sys.executable, str(ROOT / "main.py"), *args]
