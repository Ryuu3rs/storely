"""Small Windows helpers: a PC-wide install lock, metered-connection check, toast notifications."""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

from . import APP_ID, DATA_DIR, FROZEN

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = wintypes.HANDLE
_k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.ReleaseMutex.argtypes = [wintypes.HANDLE]
WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT = 0, 0x80, 0x102


class InstallLock:
    """One install at a time across the app, the background updater and the CLI (Windows' installer jams when
    jobs overlap). A named mutex, so it also covers other processes; re-entrant within a thread."""

    def __init__(self, name: str = "Local\\Storely-Install", max_wait: float = 2 * 3600):
        self._h = _k32.CreateMutexW(None, False, name)
        self._local = threading.RLock()
        self._depth = threading.local()
        self.max_wait = max_wait

    def locked(self) -> bool:
        r = _k32.WaitForSingleObject(self._h, 0)
        if r in (WAIT_OBJECT_0, WAIT_ABANDONED):
            _k32.ReleaseMutex(self._h)
            return False
        return True

    def __enter__(self):
        self._local.acquire()
        d = getattr(self._depth, "n", 0)
        if d == 0:
            end = time.monotonic() + self.max_wait
            while _k32.WaitForSingleObject(self._h, 1000) not in (WAIT_OBJECT_0, WAIT_ABANDONED):
                if time.monotonic() > end:
                    self._local.release()
                    raise RuntimeError("another install has been holding Windows' installer for over "
                                       f"{self.max_wait / 3600:.0f} hours - try again later")
        self._depth.n = d + 1
        return self

    def __exit__(self, *exc):
        self._depth.n -= 1
        if self._depth.n == 0:
            _k32.ReleaseMutex(self._h)
        self._local.release()


def need_space(where, needed: int, what: str) -> None:
    """Fail early, in plain words, instead of halfway through a download or an install."""
    import os
    import shutil
    drive = os.path.splitdrive(os.path.abspath(str(where)))[0] or str(where)
    free = shutil.disk_usage(str(where)).free
    if free < needed:
        gb = lambda n: f"{n / 1073741824:.1f} GB"     # noqa: E731
        raise RuntimeError(f"Not enough space on {drive} for {what}: needs about {gb(needed)}, {gb(free)} free")


STORE_LINK_PROGID = "Storely.StoreLink"   # registered by the installer


def store_links_ours() -> bool:
    """Has the user picked Storely for ms-windows-store:// links (Settings > Default apps)?"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations"
                                                      r"\ms-windows-store\UserChoice") as k:
            return winreg.QueryValueEx(k, "ProgId")[0] == STORE_LINK_PROGID
    except OSError:
        return False


def metered() -> bool:
    """True on a metered/capped connection (phone hotspot etc.) - big downloads should wait."""
    try:
        from winrt.windows.networking.connectivity import NetworkInformation
        prof = NetworkInformation.get_internet_connection_profile()
        if prof is None:
            return False
        cost = prof.get_connection_cost()
        return int(cost.network_cost_type) not in (0, 1) or bool(cost.approaching_data_limit or cost.over_data_limit)
    except Exception:
        return False


# installed: our own identity (the Start menu shortcut carries it), so toasts say "Storely" with our icon;
# from source there's no shortcut, so borrow PowerShell's
AUMID = APP_ID if FROZEN else "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"


def toast(title: str, body: str, actions: list[tuple[str, str]] | None = None, launch: str = "") -> bool:
    """Windows notification (works without a window - used by the background updater). actions = [(label,
    storely://... link)]; buttons only work in the installed app, which registers that link type."""
    try:
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import ToastNotification, ToastNotificationManager
        from xml.sax.saxutils import escape, quoteattr
        acts = "".join(f"<action content={quoteattr(lbl)} activationType='protocol' arguments={quoteattr(url)}/>"
                       for lbl, url in (actions or []) if FROZEN)
        head = f"<toast activationType='protocol' launch={quoteattr(launch)}>" if launch and FROZEN else "<toast>"
        doc = XmlDocument()
        doc.load_xml(f"{head}<visual><binding template='ToastGeneric'><text>{escape(title)}</text>"
                     f"<text>{escape(body)}</text></binding></visual>" + (f"<actions>{acts}</actions>" if acts else "")
                     + "</toast>")
        ToastNotificationManager.create_toast_notifier_with_id(AUMID).show(ToastNotification(doc))
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------------- one-time action links
# storely:// links can be opened by any web page, so links that DO something (not just open a page) carry a
# random token that only Storely's own notifications know, valid once and for a day.
TOKEN_FILE = DATA_DIR / "action_token.json"


def action_link(action: str) -> str:
    import json
    import secrets
    tok = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(json.dumps({"token": tok, "action": action, "expires": time.time() + 86400}), encoding="utf-8")
    return f"storely://{action}?token={tok}"


def take_action_token(action: str, token: str) -> bool:
    import hmac
    import json
    try:
        d = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    ok = (d.get("action") == action and time.time() < d.get("expires", 0)
          and hmac.compare_digest(str(d.get("token", "")), token or ""))
    if ok:
        TOKEN_FILE.unlink(missing_ok=True)
    return ok


# ----------------------------------------------------------------------------- when not to work
def on_battery() -> bool:
    try:
        import psutil
        b = psutil.sensors_battery()
        return bool(b and not b.power_plugged)
    except Exception:
        return False


def in_quiet_hours(settings: dict, now: float | None = None) -> bool:
    """settings['quiet_hours'] = [start_hour, end_hour] (e.g. [23, 7]); [] = off."""
    q = settings.get("quiet_hours") or []
    if len(q) != 2 or q[0] == q[1]:
        return False
    h = time.localtime(now).tm_hour
    start, end = int(q[0]), int(q[1])
    return start <= h < end if start < end else (h >= start or h < end)
