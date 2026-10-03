"""Background updates without the app open: a scheduled task (runs as you, no admin) at sign-in and every few
hours. It updates ticked apps (or all) while they're closed, watches for installer jams, and sends a notification.

Deliberately NOT elevated: an admin task that runs scripts from a user-writable folder would let any program
rewrite those scripts and get admin silently. Updates that need admin (e.g. Codex's service) wait for the app."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from . import DATA_DIR, FROZEN, ROOT, health, launcher, storequeue, winapps, winsys, wpm
from .winapps import ps, q

TASK = "My Store background updates"
STATUS_FILE = DATA_DIR / "background_status.json"


def register(hours: int = 6) -> tuple[bool, str]:
    cmd = launcher("--auto")
    if not FROZEN:      # from source: the windowless Python, so no console flashes up
        cmd[0] = str(Path(sys.executable).with_name("pythonw.exe"))
    script = (f"$a = New-ScheduledTaskAction -Execute {q(cmd[0])} -Argument {q(subprocess.list2cmdline(cmd[1:]))}"
              f" -WorkingDirectory {q(ROOT)};"
              f"$t1 = New-ScheduledTaskTrigger -AtLogOn -User \"$env:USERDOMAIN\\$env:USERNAME\"; $t1.Delay = 'PT5M';"
              f"$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(30) -RepetitionInterval (New-TimeSpan -Hours {hours});"
              "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3)"
              " -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;"
              "$p = New-ScheduledTaskPrincipal -UserId \"$env:USERDOMAIN\\$env:USERNAME\" -LogonType Interactive -RunLevel Limited;"
              f"Register-ScheduledTask -TaskName {q(TASK)} -Action $a -Trigger $t1,$t2 -Settings $s -Principal $p -Force | Out-Null; 'OK'")
    r = ps(script, timeout=60)
    ok = r.stdout.strip().endswith("OK")
    return ok, "" if ok else (r.stderr.strip() or r.stdout.strip())[:400]


def unregister() -> tuple[bool, str]:
    r = ps(f"Unregister-ScheduledTask -TaskName {q(TASK)} -Confirm:$false -ErrorAction Stop; 'OK'", timeout=60)
    ok = r.stdout.strip().endswith("OK")
    return ok, "" if ok else r.stderr.strip()[:300]


def status() -> dict:
    r = ps(f"$t = Get-ScheduledTask -TaskName {q(TASK)} -ErrorAction SilentlyContinue; if ($t) {{ $i = $t | Get-ScheduledTaskInfo;"
           " [pscustomobject]@{ state=\"$($t.State)\"; last=\"$($i.LastRunTime)\"; next=\"$($i.NextRunTime)\"; code=$i.LastTaskResult }"
           " | ConvertTo-Json -Compress }", timeout=30)
    try:
        d = json.loads(r.stdout) if r.stdout.strip() else {}
    except ValueError:
        d = {}
    try:
        d["run"] = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    d["registered"] = bool(d.get("state"))
    return d


def run(settings: dict) -> dict:
    """One background pass (`MyStore.exe --auto`, or `cli.py auto`)."""
    from .engine import Engine, NotYetOut
    from .browse import Browse
    t0 = time.time()
    out = {"started": t0, "updated": [], "failed": [], "skipped_open": [], "needs_admin": [], "jam": "", "desktop": []}
    if settings.get("pause_on_metered", True) and winsys.metered():
        out["note"] = "metered connection - skipped"
        _save(out)
        return out
    e = Engine(settings.get("market", "GB"), settings.get("keep_rollback", False), settings.get("holds", {}))
    e.allow_admin = False
    e.scan()
    e.check_all()
    mode = settings.get("background_mode", "ticked")
    ticked = set(settings.get("auto_update", []))
    for a in e.apps.values():
        if not a.update_available or (mode == "ticked" and a.family not in ticked):
            continue
        if a.installed and winapps.running(a.installed.location):
            out["skipped_open"].append(a.title)
            continue
        try:
            prep = e.prepare(a)
            v = e.install(a, prep, close_app=False)
            out["updated"].append(f"{a.title} {v}")
        except NotYetOut:
            pass
        except Exception as ex:
            msg = str(ex)
            (out["needs_admin"] if "0x80073D28" in msg or "admin" in msg.lower() else out["failed"]).append(
                f"{a.title}: {winapps.explain(msg)}")
    if mode == "all" or settings.get("background_desktop", True):
        b = Browse(settings.get("market", "GB"))
        for pid in wpm.tracked():
            try:
                d = wpm.resolve(b, pid, settings.get("market", "GB"))
                if d.update_available:
                    wpm.install(d)
                    out["desktop"].append(f"{d.title} {d.version}")
            except Exception as ex:
                out["failed"].append(f"{pid}: {ex}")
    if settings.get("watchdog", True):
        stuck = health.installer_jobs()
        if stuck:
            if settings.get("auto_unjam", True):
                for i in storequeue.items():
                    if i.state not in ("Completed", "Cancelled"):
                        storequeue.cancel(i.family)
                stuck = health.installer_jobs()
            out["jam"] = f"{len(stuck)} stuck job(s)" if stuck else "cleared the Store's stuck queue items"
    out["took"] = round(time.time() - t0)
    _save(out)
    lines = []
    if out["updated"] or out["desktop"]:
        lines.append(f"Updated {len(out['updated']) + len(out['desktop'])}: " + ", ".join((out["updated"] + out["desktop"])[:4]))
    if out["needs_admin"]:
        lines.append(f"{len(out['needs_admin'])} need admin - open My Store")
    if out["failed"]:
        lines.append(f"{len(out['failed'])} failed - see My Store")
    if out["jam"] and "stuck" in out["jam"]:
        lines.append(f"Windows' installer jammed ({out['jam']}) - open My Store > Health")
    if lines and settings.get("notify", True):
        winsys.toast("My Store", "\n".join(lines))
    return out


def _save(out: dict) -> None:
    STATUS_FILE.write_text(json.dumps(out, indent=1), encoding="utf-8")
