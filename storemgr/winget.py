"""Your other programs (Chrome, 7-Zip, Steam...) through winget, Microsoft's package manager.

Runs as you, never elevated: an installer that needs admin asks for it itself. winget checks each installer's
SHA-256 against its manifest. Every call has a hard time limit - winget can sit waiting for input forever."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

NO_WINDOW = 0x08000000
ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9.\-_+]{0,127}\Z")
COMMON = ["--accept-source-agreements", "--disable-interactivity"]

# winget's own result codes (APPINSTALLER_CLI_ERROR_* / installer outcomes) -> plain words
ERRORS = {
    0x8A15002B: "No newer version applies to this PC any more",
    0x8A150011: "The download didn't match winget's checksum - not installed",
    0x8A150014: "winget can't find this program any more",
    0x8A150101: "The program is open - close it and try again",
    0x8A150102: "Another installation is already running - try again in a moment",
    0x8A150103: "A file the installer needs is in use - close the program and try again",
    0x8A150104: "The installer needs something else installed first",
    0x8A150105: "Not enough disk space",
    0x8A150107: "No internet connection",
    0x8A150109: "Installed - restart Windows to finish",
    0x8A15010A: "Restart Windows first, then update this",
    0x8A15010C: "Cancelled (the installer's admin prompt was declined?)",
    0x8A15010D: "This version is already installed",
    0x8A15010F: "Blocked by a policy on this PC",
    0x800704C7: "Cancelled at the admin prompt",
    1223: "Cancelled at the admin prompt",
}


@dataclass
class Upgrade:
    name: str
    id: str
    version: str
    available: str
    source: str


def exe() -> str | None:
    """winget by full path: the App Installer alias in your WindowsApps folder, else whatever PATH has."""
    alias = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "winget.exe"
    return str(alias) if alias.exists() else shutil.which("winget")


def available() -> bool:
    return exe() is not None


def valid_id(pkg_id: str) -> bool:
    return bool(ID_RE.match(pkg_id or "")) and "…" not in pkg_id


def parse_upgrades(text: str) -> list[Upgrade]:
    """winget's table -> rows. Column starts come from the header line; a row that doesn't fit them is split on
    runs of 2+ spaces from the right. Rows whose id is cut short (an ellipsis) are dropped, never guessed."""
    lines = [ln.rstrip() for ln in re.split(r"\r\n|\r|\n", text)]    # the progress spinner ends lines with a bare \r
    head = next((i for i, ln in enumerate(lines) if re.search(r"\bId\b", ln) and re.search(r"\bVersion\b", ln)
                 and re.search(r"\bSource\b", ln)), None)
    if head is None:
        return []
    h = re.sub(r"^[\s\-\\|/]*", lambda m: " " * len(m.group(0)), lines[head])   # spinner residue before "Name"
    cols = [h.find(c) for c in ("Id", "Version", "Available", "Source")]
    if min(cols) < 0:
        return []
    out = []
    for ln in lines[head + 1:]:
        if not ln.strip() or set(ln.strip()) <= {"-"} or re.match(r"^\d+ (upgrades?|package)", ln.strip()):
            continue
        row = None
        if len(ln) >= cols[3] and ln[cols[0] - 1:cols[0]] in (" ", "") and ln[cols[3] - 1] == " ":
            parts = [ln[:cols[0]], ln[cols[0]:cols[1]], ln[cols[1]:cols[2]], ln[cols[2]:cols[3]], ln[cols[3]:]]
            row = [p.strip() for p in parts]
        if not row or not valid_id(row[1]) or not row[4]:
            bits = re.split(r"\s{2,}", ln.strip())
            row = bits if len(bits) == 5 else None
        if row and valid_id(row[1]) and row[2] and row[3]:
            out.append(Upgrade(*row))
    return out


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    w = exe()
    if not w:
        raise RuntimeError("winget isn't installed (it comes with 'App Installer' from the Store)")
    return subprocess.run([w, *args], capture_output=True, timeout=timeout, creationflags=NO_WINDOW)


def list_upgrades(include_unknown: bool = False, timeout: float = 180) -> list[Upgrade]:
    """Programs winget can update. Store ('msstore') rows are left to Unjammed's own Store engine."""
    try:
        r = _run(["upgrade", *COMMON, *(["--include-unknown"] if include_unknown else [])], timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"winget didn't answer within {int(timeout)} s") from None
    return [u for u in parse_upgrades(r.stdout.decode("utf-8", "replace")) if u.source.lower() == "winget"]


def explain(code: int, output: str = "") -> str:
    code &= 0xFFFFFFFF
    if code in ERRORS:
        return ERRORS[code]
    last = next((ln.strip() for ln in reversed(output.splitlines()) if ln.strip() and not set(ln.strip()) <= set("-\\|/ ")), "")
    return f"winget failed (0x{code:08X})" + (f": {last[:200]}" if last else "")


_NOISE = re.compile(r"^[\s\-\\|/█▒░]*$|^\s*[\d.]+ (KB|MB|GB) / [\d.]+ (KB|MB|GB)\s*$")


def upgrade(pkg_id: str, report=lambda stage, done, total, msg: None, cancel: threading.Event | None = None,
            timeout: float = 3600) -> str:
    """Update one program; returns "" (winget doesn't say the new version). Raises RuntimeError in plain words."""
    if not valid_id(pkg_id):
        raise RuntimeError(f"not a winget package id: {pkg_id!r}")
    w = exe()
    if not w:
        raise RuntimeError("winget isn't installed (it comes with 'App Installer' from the Store)")
    cancel = cancel or threading.Event()
    p = subprocess.Popen([w, "upgrade", "--id", pkg_id, "--exact", "--silent", "--accept-package-agreements", *COMMON],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    seen: list[str] = []

    def read():
        buf = b""
        while chunk := p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(4096):
            buf += chunk
            *done, buf = re.split(rb"[\r\n]", buf)
            for raw in done:
                line = raw.decode("utf-8", "replace").strip()
                if line and not _NOISE.match(line):
                    seen.append(line)
                    report("install", 0, 0, line[:120])
    t = threading.Thread(target=read, daemon=True)
    t.start()
    end = time.monotonic() + timeout
    while p.poll() is None:
        if cancel.is_set() or time.monotonic() > end:
            p.kill()
            t.join(2)
            if cancel.is_set():
                from .download import Cancelled
                raise Cancelled()
            raise RuntimeError(f"winget took longer than {int(timeout / 60)} minutes - stopped")
        time.sleep(0.25)
    t.join(5)
    if p.returncode != 0:
        raise RuntimeError(explain(p.returncode, "\n".join(seen)))
    return ""
