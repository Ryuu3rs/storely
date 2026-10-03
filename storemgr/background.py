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

from . import DATA_DIR, FROZEN, ROOT, health, launcher, perms, storequeue, winapps, winsys, wpm
from .winapps import ps, q

TASK = "Unjammed background updates"
OLD_TASK = "My Store background updates"     # this app's name before 1.2
STATUS_FILE = DATA_DIR / "background_status.json"


def _command() -> list[str]:
    cmd = launcher("--auto")
    if not FROZEN:      # from source: the windowless Python, so no console flashes up
        cmd[0] = str(Path(sys.executable).with_name("pythonw.exe"))
    return cmd


def refresh() -> str:
    """Keep the task pointing at this installed copy (after a move or the rename) and carry the pre-1.2 task over.
    Only the installed app does this - a copy run from source must not take over the real one's task."""
    if not FROZEN:
        return ""
    r = ps(f"foreach ($n in {q(TASK)}, {q(OLD_TASK)}) {{ $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue;"
           " if ($t) { \"$n|$($t.Actions[0].Execute)\" } }", timeout=30)
    found = dict(line.split("|", 1) for line in r.stdout.splitlines() if "|" in line)
    if not found or found.get(TASK, "").lower() == _command()[0].lower() and OLD_TASK not in found:
        return ""
    ok, err = register()
    if ok and OLD_TASK in found:
        ps(f"Unregister-ScheduledTask -TaskName {q(OLD_TASK)} -Confirm:$false -ErrorAction SilentlyContinue", timeout=30)
    return "background updates moved to this copy" if ok else f"couldn't update the background task: {err}"


def register(hours: int = 6) -> tuple[bool, str]:
    cmd = _command()
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
    """One background pass (`Unjammed.exe --auto`, or `cli.py auto`)."""
    from .engine import Engine, NotYetOut
    from .browse import Browse
    t0 = time.time()
    out = {"started": t0, "updated": [], "failed": [], "skipped_open": [], "needs_admin": [], "needs_ok": [],
           "waiting": [], "jam": "", "desktop": [], "others": 0}
    for skip, why in ((settings.get("pause_on_metered", True) and winsys.metered(), "metered connection"),
                      (settings.get("pause_on_battery") and winsys.on_battery(), "on battery"),
                      (winsys.in_quiet_hours(settings), "quiet hours")):
        if skip:
            out["note"] = f"{why} - skipped"
            _save(out)
            return out
    e = Engine(settings.get("market", "GB"), settings.get("keep_rollback", False), settings.get("holds", {}))
    e.allow_admin = False
    e.scan()
    e.check_all()
    mode = settings.get("background_mode", "ticked")
    ticked = set(settings.get("auto_update", []))
    for a in e.apps.values():
        if not a.update_available:
            continue
        if mode == "ticked" and a.family not in ticked:
            out["waiting"].append(a.title)
            continue
        if a.installed and winapps.running(a.installed.location):
            out["skipped_open"].append(a.title)
            continue
        try:
            prep = e.prepare(a)
            if settings.get("ask_new_permissions", True) and prep.perms and perms.has_risky(prep.perms):
                out["needs_ok"].append(f"{a.title}: {perms.summary(prep.perms)}")    # the user decides, in the app
                continue
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
                if not d.update_available:
                    continue
                if d.installer and (d.installer.scope or "").lower() != "user":
                    out["needs_admin"].append(f"{d.title}: installs for every user, which needs admin")   # no surprise UAC
                    continue
                wpm.install(d)
                out["desktop"].append(f"{d.title} {d.version}")
            except Exception as ex:
                out["failed"].append(f"{pid}: {ex}")
    if settings.get("winget", True):
        try:
            from . import winget
            if winget.available():
                out["others"] = len(winget.list_upgrades())
        except Exception as ex:
            out["failed"].append(f"winget: {ex}")
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
    waiting = len(out["waiting"]) + len(out["needs_ok"]) + out["others"]
    if waiting:
        lines.append(f"{waiting} update(s) waiting" + (f", {len(out['needs_ok'])} want new permissions" if out["needs_ok"] else ""))
    if out["needs_admin"]:
        lines.append(f"{len(out['needs_admin'])} need admin - open Unjammed")
    if out["failed"]:
        lines.append(f"{len(out['failed'])} failed - see Unjammed")
    if out["jam"] and "stuck" in out["jam"]:
        lines.append(f"Windows' installer jammed ({out['jam']}) - open Unjammed > Health")
    if lines and settings.get("notify", True):
        actions = [("Update all", winsys.action_link("update-all"))] if out["waiting"] or out["others"] else []
        winsys.toast("Unjammed", "\n".join(lines), actions + [("Open", "unjammed://updates")], launch="unjammed://updates")
    return out


def _save(out: dict) -> None:
    STATUS_FILE.write_text(json.dumps(out, indent=1), encoding="utf-8")
