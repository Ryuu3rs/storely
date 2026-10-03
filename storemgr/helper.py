"""The admin / SYSTEM half of Unjammed.

  Unjammed.exe --elevated <action> --job <id> ...      started through one UAC prompt by storemgr.admin
  Unjammed.exe --system-task <action> --job <id> ...   one-off SYSTEM task started by the elevated half

No scripts are written anywhere: SYSTEM runs this same installed program, which only admins can modify. Every
input is validated, and all work files/results live in a folder only SYSTEM + Administrators can write to."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import winreg
from pathlib import Path

import psutil

from . import MACHINE_DIR, RESULTS_DIR, launcher, secure
from .winapps import FAMILY_RE, NO_WINDOW, SYSTEM32, ps, q, verify_signature

JOB_RE = re.compile(r"\A[0-9a-f]{32}\Z")
PKG_EXT = {".appx", ".msix", ".appxbundle", ".msixbundle", ".eappx", ".emsix", ".eappxbundle", ".emsixbundle"}
STAGING = MACHINE_DIR / "staging"
BACKUP = MACHINE_DIR / "rslc-backup"
SERVICES = ("InstallService", "ClipSVC", "AppXSvc")
SC = str(SYSTEM32 / "sc.exe")


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _parser(prog: str, actions: list[str]) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, add_help=False, exit_on_error=False)
    p.add_argument("action", choices=actions)
    p.add_argument("--job", required=True)
    p.add_argument("--family", default="")
    return p


def _parse(p: argparse.ArgumentParser, argv: list[str]):
    try:
        a = p.parse_args(argv)
    except (argparse.ArgumentError, SystemExit):
        return None
    if not JOB_RE.match(a.job) or (a.family and not FAMILY_RE.match(a.family)):
        return None
    return a


# ----------------------------------------------------------------------------- elevated (admin) side

def elevated_main(argv: list[str]) -> int:
    p = _parser("--elevated", ["unjam", "install", "cleanup", "store-auto-update"])
    p.add_argument("--path", default="")
    p.add_argument("--dep", action="append", default=[])
    p.add_argument("--close", action="store_true")
    p.add_argument("--publisher", default="")
    p.add_argument("--value", choices=["on", "off"], default="off")
    a = _parse(p, argv)
    if a is None:
        return 2
    res = {"ok": True, "steps": [], "errors": []}
    try:
        res["steps"] += secure.ensure_protected_dir(MACHINE_DIR)
        RESULTS_DIR.mkdir(exist_ok=True)
        {"unjam": _unjam, "install": _install, "cleanup": _cleanup, "store-auto-update": _store_auto}[a.action](a, res)
    except Exception as e:
        res["errors"].append(f"{type(e).__name__}: {e}")
    res["ok"] = not res["errors"]
    if RESULTS_DIR.is_dir() and secure.protected(MACHINE_DIR):
        _write(RESULTS_DIR / f"{a.job}.json", res)
    return 0 if res["ok"] else 1


def _status(name: str) -> dict:
    try:
        return psutil.win_service_get(name).as_dict()
    except Exception:
        return {}


def _wait(name: str, state: str, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if _status(name).get("status") == state:
            return True
        time.sleep(0.5)
    return _status(name).get("status") == state


def _stop_service(name: str, res: dict) -> None:
    s = _status(name)
    if not s or s.get("status") == "stopped":
        return
    subprocess.run([SC, "stop", name], capture_output=True, timeout=30, creationflags=NO_WINDOW)
    if _wait(name, "stopped", 10):
        res["steps"].append(f"stopped {name}")
        return
    pid = _status(name).get("pid")
    shared = [x.name() for x in psutil.win_service_iter() if x.name() != name and _pid(x) == pid] if pid else []
    if pid and not shared:     # hung: end its process, but only when it hosts nothing else
        try:
            psutil.Process(pid).kill()
        except psutil.Error as e:
            res["errors"].append(f"could not end {name}: {e}")
            return
        _wait(name, "stopped", 10)
        res["steps"].append(f"ended hung {name} (process {pid})")
    else:
        res["errors"].append(f"could not stop {name}")


def _pid(svc) -> int | None:
    try:
        return svc.pid()
    except Exception:
        return None


def _system_task(action: str, job: str, extra: list[str], timeout: float) -> dict:
    from .admin import untrusted_code
    bad = untrusted_code()
    if bad:
        raise PermissionError(f"won't run a SYSTEM task from a copy others can modify: {bad[0]}")
    cmd = launcher("--system-task", action, "--job", job, *extra)
    name = f"Unjammed-{action}-{job[:8]}"
    out = RESULTS_DIR / f"{job}.system.json"
    r = ps(f"$a = New-ScheduledTaskAction -Execute {q(cmd[0])} -Argument {q(subprocess.list2cmdline(cmd[1:]))};"
           f" $p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest;"
           f" Register-ScheduledTask -TaskName {q(name)} -Action $a -Principal $p -Force | Out-Null;"
           f" Start-ScheduledTask -TaskName {q(name)}; 'OK'", timeout=60)
    try:
        if not r.stdout.strip().endswith("OK"):
            raise RuntimeError(f"couldn't start the SYSTEM task: {(r.stderr or r.stdout).strip()[:300]}")
        end = time.time() + timeout
        while time.time() < end and not out.exists():
            time.sleep(0.5)
    finally:
        ps(f"Unregister-ScheduledTask -TaskName {q(name)} -Confirm:$false -ErrorAction SilentlyContinue", timeout=60)
    if not out.exists():
        raise RuntimeError("the SYSTEM task did not finish")
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    finally:
        out.unlink(missing_ok=True)


def _unjam(a, res: dict) -> None:
    for s in SERVICES:
        _stop_service(s, res)
    # saved queue jobs (*.rslc) are restored at every boot - that's why restarts never clear a jam. Their folder
    # belongs to SYSTEM (admins get 'access denied'), so a one-off SYSTEM task moves them to a backup folder.
    try:
        r = _system_task("move-rslc", a.job, ["--family", a.family] if a.family else [], timeout=60)
        res["steps"].append(f"queue files moved {r.get('moved', 0)} (backup: {r.get('backup')})")
        res["errors"] += [f"queue file {f}" for f in r.get("fails", [])]
    except Exception as e:
        res["errors"].append(str(e))
    if a.family:     # half-installed leftovers of this app: staged for the system but installed for nobody
        pkg = a.family.rsplit("_", 1)[0]
        r = ps(f"Get-AppxPackage -AllUsers -Name {q(pkg)} -ErrorAction SilentlyContinue | Where-Object {{"
               " -not ($_.PackageUserInformation | Where-Object { \"$($_.InstallState)\" -eq 'Installed' }) } |"
               " ForEach-Object { try { Remove-AppxPackage -Package $_.PackageFullName -AllUsers -ErrorAction Stop;"
               " \"removed half-installed $($_.PackageFullName)\" } catch { \"FAIL could not remove $($_.PackageFullName):"
               " $($_.Exception.Message)\" } }", timeout=600)
        for line in filter(None, (ln.strip() for ln in r.stdout.splitlines())):
            (res["errors"] if line.startswith("FAIL ") else res["steps"]).append(line.removeprefix("FAIL "))
    for s in reversed(SERVICES):
        r = subprocess.run([SC, "start", s], capture_output=True, timeout=30, creationflags=NO_WINDOW)
        if r.returncode not in (0, 1056):      # 1056 = already running
            res["errors"].append(f"could not start {s} (error {r.returncode})")
        else:
            _wait(s, "running", 15)
    res["steps"].append("services: " + ", ".join(f"{s}={_status(s).get('status', '?')}" for s in reversed(SERVICES)))


def _stage(src: Path, dest_dir: Path, publisher: str | None) -> Path:
    """Copy a package where standard users can't swap it, then check its signature there."""
    if src.suffix.lower() not in PKG_EXT or not src.is_file() or secure.is_reparse(src):
        raise ValueError(f"not a Windows app package: {src}")
    dest = dest_dir / src.name
    shutil.copyfile(src, dest)
    ok, why = verify_signature(dest, publisher)
    if not ok:
        raise RuntimeError(f"signature check failed for {src.name} ({why})")
    return dest


def _install(a, res: dict) -> None:
    stage = STAGING / a.job
    stage.mkdir(parents=True)
    try:
        main = _stage(Path(a.path), stage, a.publisher or None)
        deps = [_stage(Path(d), stage, None) for d in a.dep]
        dep = f" -DependencyPath {','.join(q(d) for d in deps)}" if deps else ""
        force = " -ForceApplicationShutdown" if a.close else ""
        r = ps(f"$ErrorActionPreference='Stop'; Add-AppxPackage -Path {q(main)}{dep} -ForceUpdateFromAnyVersion{force}; 'OK'",
               timeout=1800)
        if r.returncode == 0 and r.stdout.strip().endswith("OK"):
            res["steps"].append(f"installed {main.name}")
        else:
            res["errors"].append((r.stderr or r.stdout).strip()[:1500] or "Add-AppxPackage failed")
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _cleanup(a, res: dict) -> None:
    r = _system_task("cleanup-deleted", a.job, [], timeout=300)
    res["freed"], res["left"] = r.get("freed", 0), r.get("left", 0)
    res["steps"].append(f"freed {res['freed']} bytes")


def _store_auto(a, res: dict) -> None:
    key = r"SOFTWARE\Policies\Microsoft\WindowsStore"
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        if a.value == "off":
            winreg.SetValueEx(k, "AutoDownload", 0, winreg.REG_DWORD, 2)
            res["steps"].append("Store automatic updates: off")
        else:
            try:
                winreg.DeleteValue(k, "AutoDownload")
            except FileNotFoundError:
                pass
            res["steps"].append("Store automatic updates: Windows default")


# ----------------------------------------------------------------------------- SYSTEM side

def system_main(argv: list[str]) -> int:
    a = _parse(_parser("--system-task", ["move-rslc", "cleanup-deleted"]), argv)
    if a is None or not secure.protected(MACHINE_DIR) or not RESULTS_DIR.is_dir():
        return 2
    try:
        out = _move_rslc(a.family) if a.action == "move-rslc" else _cleanup_deleted()
    except Exception as e:
        out = {"fails": [f"{type(e).__name__}: {e}"]}
    _write(RESULTS_DIR / f"{a.job}.system.json", out)
    return 0


def _move_rslc(family: str) -> dict:
    repo = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows" / "AppRepository"
    pkg = family.rsplit("_", 1)[0].lower() if family else ""
    backup = BACKUP / time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, exist_ok=True)
    moved, fails = 0, []
    for f in repo.glob("*.rslc"):
        try:
            if pkg:
                b = f.read_bytes()
                if pkg not in (b.decode("utf-16-le", "ignore") + b.decode("latin-1")).lower():
                    continue
            shutil.move(str(f), str(backup / f.name))
            moved += 1
        except OSError as e:
            fails.append(f"{f.name}: {e}")
    return {"moved": moved, "fails": fails, "backup": str(backup)}


def _cleanup_deleted() -> dict:
    from .cleanup import folder_size
    d = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WindowsApps" / "Deleted"
    if not d.is_dir():
        return {"freed": 0, "left": 0}
    before = folder_size(d)
    for c in d.iterdir():
        try:
            if secure.is_reparse(c):
                os.rmdir(c) if c.is_dir() else c.unlink()      # remove the link itself, never what it points at
            elif c.is_dir():
                shutil.rmtree(c, ignore_errors=True)
            else:
                c.unlink()
        except OSError:
            pass
    after = folder_size(d)
    return {"freed": before - after, "left": after}
