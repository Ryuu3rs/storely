"""Is Windows' app installer healthy? Finds jobs that started and never finished (the jam), service state, Store queue."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from . import storequeue
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
    r = ps("Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-AppXDeploymentServer/Operational';"
           f"StartTime=(Get-Date).AddHours(-{hours}); Id=607,400,401,404}} -MaxEvents 4000 -ErrorAction SilentlyContinue |"
           " ForEach-Object { $m = $_.Message -replace '\\s+',' '; [pscustomobject]@{ id=$_.Id; t=$_.TimeCreated.ToString('o');"
           " m=$m.Substring(0, [Math]::Min(400, $m.Length)) } } | ConvertTo-Json -Compress",
           timeout=120)
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
    r = ps("(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')", timeout=30)
    try:
        return datetime.fromisoformat(r.stdout.strip())
    except ValueError:
        return None


def services() -> dict[str, str]:
    r = ps("Get-Service AppXSvc, InstallService, ClipSVC, wuauserv, DoSvc | ForEach-Object { [pscustomobject]@{ n=$_.Name; s=\"$($_.Status)\" } } |"
           " ConvertTo-Json -Compress", timeout=30)
    try:
        return {d["n"]: d["s"] for d in json.loads(r.stdout)}
    except (ValueError, TypeError):
        return {}


def status() -> dict:
    stuck = installer_jobs()
    q = storequeue.items()
    return {"services": services(), "stuck": stuck, "store_queue": q,
            "healthy": not stuck and not [i for i in q if i.state not in ("Completed", "Cancelled")]}
