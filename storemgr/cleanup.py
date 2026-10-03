"""Clean-up and disk usage: Storely's own caches, Windows' leftover 'Deleted' app folders, size of each app."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import DOWNLOAD_DIR, ROLLBACK_DIR, CACHE_DIR, admin


def folder_size(path: str | Path) -> int:
    total = 0
    for root, _, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def caches() -> dict[str, int]:
    return {"downloads": folder_size(DOWNLOAD_DIR), "rollback": folder_size(ROLLBACK_DIR),
            "images": folder_size(CACHE_DIR / "img")}


def clear_cache(which: str) -> int:
    d = {"downloads": DOWNLOAD_DIR, "rollback": ROLLBACK_DIR, "images": CACHE_DIR / "img"}[which]
    freed = folder_size(d)
    for p in d.iterdir():
        try:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
        except OSError:
            pass
    return freed - folder_size(d)


def windows_leftovers() -> dict:
    """Old app versions Windows failed to delete (C:\\Program Files\\WindowsApps\\Deleted). Needs admin; the
    folder belongs to SYSTEM, so the admin helper removes it through a one-off SYSTEM task."""
    return admin.cleanup()


def app_sizes(apps) -> dict[str, int]:
    return {a.family: folder_size(a.installed.location) for a in apps if a.installed and a.installed.location}
