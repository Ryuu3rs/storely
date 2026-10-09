"""Is Windows' app installer healthy? Finds jobs that started and never finished (the jam), service state, Store queue."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime

import psutil

from . import storequeue
from .diag import log
from .winapps import ps

STUCK_MINUTES = 10
_RE_PKG = re.compile(r"(?:package|parameter)\s+([A-Za-z0-9.\-]+_[\d.]+_[^_\s]*_[^_\s]*_[a-z0-9]{13})", re.I)
_RE_OP = re.compile(r"Deployment (\w+) operation")


@dataclass
class StuckJob:
    package: str
    operation: str
    started: datetime
    minutes: float

    @property
    def family(self) -> str:
        parts = self.package.split("_")
        return f"{parts[0]}_{parts[-1]}" if len(parts) >= 2 else self.package


def installer_jobs(hours: float = 12) -> list[StuckJob]:
    """Jobs that were de-queued/started but never logged success or failure, oldest first."""
    try:
        r = ps("Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-AppXDeploymentServer/Operational';"
               f"StartTime=(Get-Date).AddHours(-{hours}); Id=607,400,401,404}} -MaxEvents 4000 -ErrorAction SilentlyContinue |"
               " ForEach-Object { $m = $_.Message -replace '\\s+',' '; [pscustomobject]@{ id=$_.Id; t=$_.TimeCreated.ToString('o');"
               " m=$m.Substring(0, [Math]::Min(400, $m.Length)) } } | ConvertTo-Json -Compress",
               timeout=120)
    except subprocess.TimeoutExpired:      # Windows is busy (e.g. just after an unjam restarted its services)
        log.warning("reading the installer's event log timed out - skipped this check")
        return []
    try:
        events = json.loads(r.stdout or "[]")
    except ValueError:
        return []
    if isinstance(events, dict):
        events = [events]
    # 607 = a job was taken off the queue and is running; 400/401/404 = finished / failed. Match by operation +
    # package (activity ids are not shared between the two), keeping only the latest start per package+operation.
    starts: dict[tuple, datetime] = {}
    ends: dict[tuple, datetime] = {}
    for e in events:
        m, o = _RE_PKG.search(e["m"]), _RE_OP.search(e["m"])
        if not m:
            continue
        key = (m.group(1).lower(), (o.group(1) if o else "").lower())
        t = datetime.fromisoformat(e["t"])
        if e["id"] == 607:
            starts[key] = max(starts.get(key, t), t)
        elif e["id"] in (400, 401, 404):
            ends[key] = max(ends.get(key, t), t)
            any_key = (key[0], "")
            ends[any_key] = max(ends.get(any_key, t), t)
    now = datetime.now().astimezone()
    out = []
    for (pkg, op), started in starts.items():
        finished = max(ends.get((pkg, op), datetime.min.replace(tzinfo=started.tzinfo)),
                       ends.get((pkg, ""), datetime.min.replace(tzinfo=started.tzinfo)))
        if finished >= started:
            continue
        mins = (now - started).total_seconds() / 60
        if mins >= STUCK_MINUTES:
            out.append(StuckJob(pkg, op or "install", started, mins))
    boot = _boot_time()
    return sorted([s for s in out if not boot or s.started >= boot], key=lambda s: s.started)


def _boot_time():
    """When Windows started - straight from the system, no PowerShell (which can stall while services restart)."""
    try:
        return datetime.fromtimestamp(psutil.boot_time()).astimezone()
    except (OSError, ValueError):
        return None


SERVICES = ("AppXSvc", "InstallService", "ClipSVC", "wuauserv", "DoSvc")
_STATE = {"running": "Running", "stopped": "Stopped", "start_pending": "Starting", "stop_pending": "Stopping",
          "paused": "Paused", "pause_pending": "Pausing", "continue_pending": "Resuming"}


def services() -> dict[str, str]:
    out = {}
    for name in SERVICES:
        try:
            st = psutil.win_service_get(name).status()
        except (psutil.Error, OSError):
            continue
        out[name] = _STATE.get(st, st.title())
    return out


def status() -> dict:
    stuck = installer_jobs()
    q = storequeue.items()
    return {"services": services(), "stuck": stuck, "store_queue": q,
            "healthy": not stuck and not [i for i in q if i.state not in ("Completed", "Cancelled")]}
