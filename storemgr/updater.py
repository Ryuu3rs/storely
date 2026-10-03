"""Self-update from GitHub releases. The installers aren't Authenticode-signed, so each release carries a SHA256SUMS
file signed with our own Ed25519 key (tools/sign_release.py); the installer is only used if its hash is in a file whose
signature checks out against PUBLIC_KEY below.

Settings (read by the caller): self_update = "notify" (default, ask when a new version is out) | "off";
skipped_update = a version string the user chose to skip."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import platform
import re
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import APP_NAME, DATA_DIR, __version__, secure
from .download import Cancelled, file_digest

PUBLIC_KEY = "ubvt+a62M+KViQMsqAg8PqL3P0ru7s65A/DzH/B/3rM="
REPO = "Ryuu3rs/unjammed"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ALLOWED_HOSTS = frozenset({"github.com", "api.github.com", "objects.githubusercontent.com",
                           "release-assets.githubusercontent.com"})
UPDATE_DIR = DATA_DIR / "updates"
SUMS_NAME, SIG_NAME = "SHA256SUMS", "SHA256SUMS.sig"
INSTALLER_RE = re.compile(r"Unjammed-Setup-(\d+\.\d+\.\d+)\.0-(x64|arm64)\.exe")
INSTALLER_ARGS = "/SP- /SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"
MAX_REDIRECTS = 5
MAX_SMALL = 64 * 1024
CHUNK = 256 * 1024
_HEADERS = {"User-Agent": f"{APP_NAME}/{__version__}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    installer_url: str
    size: int
    sums_url: str
    sig_url: str
    page_url: str

    @property
    def installer_name(self) -> str:
        return unquote(urlsplit(self.installer_url).path.rsplit("/", 1)[-1])


def parse_version(s: str) -> tuple[int, int, int] | None:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (s or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def is_newer(candidate: str, current: str = __version__) -> bool:
    c, cur = parse_version(candidate), parse_version(current)
    return bool(c and cur and c > cur)


def machine_arch() -> str:
    """'arm64' on an ARM PC (even when this copy runs under x64 emulation), else 'x64'."""
    try:
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.IsWow64Process2.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.USHORT), ctypes.POINTER(wintypes.USHORT)]
        proc, native = wintypes.USHORT(), wintypes.USHORT()
        if k32.IsWow64Process2(k32.GetCurrentProcess(), ctypes.byref(proc), ctypes.byref(native)):
            return "arm64" if native.value == 0xAA64 else "x64"
    except (OSError, AttributeError):
        pass
    names = (platform.machine(), os.environ.get("PROCESSOR_ARCHITEW6432", ""), os.environ.get("PROCESSOR_ARCHITECTURE", ""))
    return "arm64" if any(n.upper() == "ARM64" for n in names) else "x64"


def allowed_url(url: str) -> bool:
    try:
        u = urlsplit(url)
        return (u.scheme == "https" and (u.hostname or "") in ALLOWED_HOSTS and u.username is None
                and u.password is None and u.port in (None, 443))
    except ValueError:
        return False


def _get(url: str, timeout: float, stream: bool = False, headers: dict | None = None) -> requests.Response:
    """GET that follows redirects itself, refusing any hop (and the final address) outside ALLOWED_HOSTS."""
    for _ in range(MAX_REDIRECTS + 1):
        if not allowed_url(url):
            raise RuntimeError(f"the update came from an unexpected address ({urlsplit(url).hostname or url}) - not used")
        r = requests.get(url, headers=headers or _HEADERS, timeout=timeout, stream=stream, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            r.close()
            url = urljoin(url, r.headers["Location"])
            continue
        if not allowed_url(r.url or url):
            r.close()
            raise RuntimeError(f"the update came from an unexpected address ({urlsplit(r.url).hostname}) - not used")
        return r
    raise RuntimeError("too many redirects while fetching the update")


def parse_release(data: dict, current: str = __version__, arch: str | None = None) -> Release | None:
    """The release in a GitHub API answer, if it is newer than `current` and has everything needed for `arch`."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    version = parse_version(str(data.get("tag_name", "")))
    if not version or not is_newer(".".join(map(str, version)), current):
        return None
    ver, arch = ".".join(map(str, version)), arch or machine_arch()
    assets = {a.get("name"): a for a in data.get("assets") or [] if isinstance(a, dict)}
    inst = assets.get(f"Unjammed-Setup-{ver}.0-{arch}.exe")
    sums, sig = assets.get(SUMS_NAME), assets.get(SIG_NAME)
    if not (inst and sums and sig):
        return None
    urls = [str(x.get("browser_download_url", "")) for x in (inst, sums, sig)]
    if not all(allowed_url(u) for u in urls):
        return None
    page = str(data.get("html_url") or f"https://github.com/{REPO}/releases/tag/v{ver}")
    return Release(version=ver, notes=str(data.get("body") or "").strip()[:4000], installer_url=urls[0],
                   size=int(inst.get("size") or 0), sums_url=urls[1], sig_url=urls[2],
                   page_url=page if allowed_url(page) else f"https://github.com/{REPO}/releases")


def check(timeout: float = 15) -> Release | None:
    """The newest release if it is newer than this copy and has an installer for this PC. None when there is
    nothing newer, no releases yet, GitHub is rate-limiting us, or we're offline."""
    try:
        with _get(LATEST_URL, timeout) as r:
            if r.status_code != 200:
                return None
            data = r.json()
    except (requests.RequestException, RuntimeError, ValueError):
        return None
    return parse_release(data)


def _small(url: str, what: str) -> bytes:
    try:
        with _get(url, 30, stream=True, headers={"User-Agent": _HEADERS["User-Agent"]}) as r:
            if r.status_code != 200:
                raise RuntimeError(f"couldn't download the update's {what} (HTTP {r.status_code})")
            out = b""
            for chunk in r.iter_content(16 * 1024):
                out += chunk
                if len(out) > MAX_SMALL:
                    raise RuntimeError(f"the update's {what} is unexpectedly large - not used")
            return out
    except requests.RequestException as e:
        raise RuntimeError(f"couldn't download the update's {what}: {e}") from None


def verify_sums(sums: bytes, sig: bytes) -> None:
    """Raise unless `sig` (base64) is PUBLIC_KEY's signature of `sums`."""
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY, validate=True))
        key.verify(base64.b64decode(b"".join(sig.split()), validate=True), sums)
    except (InvalidSignature, ValueError):
        raise RuntimeError("the update's signature doesn't check out, so it was not used") from None


def sha256_for(sums: bytes, name: str) -> str:
    """The hash listed for `name` in a (verified) SHA256SUMS file."""
    for line in sums.decode("utf-8", "replace").splitlines():
        m = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line.strip())
        if m and m[2] == name:
            return m[1].lower()
    raise RuntimeError(f"{name} isn't listed in the update's signed checksum file - not used")


def _clear_others(keep: str) -> None:
    for p in UPDATE_DIR.iterdir():
        if p.name != keep and p.is_file():
            try:
                p.unlink()
            except OSError:
                pass


def download(rel: Release, progress=None, cancel: threading.Event | None = None) -> Path:
    """Download and verify `rel`'s installer into UPDATE_DIR; returns its path. progress(done, total, bytes_per_s).
    Raises RuntimeError (or download.Cancelled) - nothing unverified is left behind."""
    cancel = cancel or threading.Event()
    name = rel.installer_name
    m = INSTALLER_RE.fullmatch(name)
    if not m or m[1] != rel.version:
        raise RuntimeError(f"unexpected installer name {name!r} - not used")
    sums, sig = _small(rel.sums_url, "checksum file"), _small(rel.sig_url, "signature")
    verify_sums(sums, sig)
    digest = sha256_for(sums, name)

    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    if secure.is_reparse(UPDATE_DIR):
        raise RuntimeError(f"{UPDATE_DIR} is a link, not a folder - not downloading there")
    _clear_others(name)
    dest, part = UPDATE_DIR / name, UPDATE_DIR / (name + ".part")
    if dest.is_file() and file_digest(dest, "sha256") == digest:
        return dest
    dest.unlink(missing_ok=True)
    h, got = hashlib.sha256(), 0
    try:
        with _get(rel.installer_url, 60, stream=True, headers={"User-Agent": _HEADERS["User-Agent"]}) as r:
            if r.status_code != 200:
                raise RuntimeError(f"couldn't download the update (HTTP {r.status_code})")
            total = rel.size or int(r.headers.get("Content-Length") or 0)
            last_t, last_b = time.monotonic(), 0
            with open(part, "wb") as f:
                for chunk in r.iter_content(CHUNK):
                    if cancel.is_set():
                        raise Cancelled()
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    if rel.size and got > rel.size:
                        raise RuntimeError("the update is bigger than GitHub said it would be - deleted")
                    now = time.monotonic()
                    if progress and now - last_t >= 0.5:
                        progress(got, total, (got - last_b) / (now - last_t))
                        last_t, last_b = now, got
        if h.hexdigest() != digest:
            raise RuntimeError("the downloaded update doesn't match its signed checksum - deleted")
        part.replace(dest)
    except requests.RequestException as e:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"couldn't download the update: {e}") from None
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    if progress:
        progress(got, got, 0)
    return dest


class _SEI(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


def _shell_open(file: str, params: str, cwd: str) -> int:
    """ShellExecuteEx "open" (Windows shows the installer's own UAC prompt); 0 or a Win32 error code."""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SEI)]
    sei = _SEI(cbSize=ctypes.sizeof(_SEI), fMask=0x400, lpVerb="open", lpFile=file, lpParameters=params,
               lpDirectory=cwd, nShow=1)     # 0x400 = SEE_MASK_FLAG_NO_UI
    return 0 if shell32.ShellExecuteExW(ctypes.byref(sei)) else (ctypes.get_last_error() or 1)


def install(path: Path) -> None:
    """Start a downloaded installer silently (it shows its own admin prompt and closes Unjammed); the caller should
    quit right after."""
    root = UPDATE_DIR.resolve()
    p = Path(path).resolve()
    if (p.parent != root or not INSTALLER_RE.fullmatch(p.name) or not p.is_file() or secure.is_reparse(path)
            or secure.is_reparse(UPDATE_DIR)):
        raise RuntimeError(f"not a downloaded Unjammed update: {path}")
    err = _shell_open(str(p), INSTALLER_ARGS, str(root))
    if err:
        raise RuntimeError("the update was cancelled at the admin prompt" if err == 1223
                           else f"couldn't start the update installer (error {err})")
