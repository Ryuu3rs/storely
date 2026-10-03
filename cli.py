"""Unjammed from a terminal.
  unjammed-cli list | updates | update <name-or-family> [--close] | queue | health | selftest
  unjammed-cli auto                  one background pass (same as Unjammed.exe --auto)
  unjammed-cli export <file.json>    save the list of Store apps on this PC
  unjammed-cli import <file.json>    install everything in that list that is missing (store apps)
Add --json to list, updates, queue, health or selftest for machine-readable output."""

import json
import sys
import time

from storemgr import __version__, background, diag, health, settings, storequeue
from storemgr.engine import Engine


def find(e, key):
    key = key.lower()
    apps = list(e.apps.values())
    return (next((a for a in apps if key in (a.title.lower(), a.family.lower())), None) or
            next((a for a in apps if a.family.lower().startswith(key)), None) or
            min((a for a in apps if key in a.title.lower() or key in a.family.lower()), key=lambda a: len(a.title), default=None))


def emit(data) -> int:
    print(json.dumps(data, indent=1, default=str))
    return 0


def main(argv):
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    cmd = argv[1] if len(argv) > 1 else "updates"
    if cmd in ("--version", "version"):
        print(f"Unjammed {__version__}")
        return 0
    s = settings.load()
    if cmd == "auto":
        return emit(background.run(s))
    if cmd == "selftest":
        res = diag.selftest(s["market"])
        if as_json:
            return emit(res)
        for r in res:
            print(f"  {'OK  ' if r['ok'] else 'FAIL'} {r['name']:48} {r['ms']:6} ms  {r['detail']}")
        return 0 if all(r["ok"] for r in res) else 1
    if cmd == "queue":
        items = storequeue.items()
        if as_json:
            return emit([i.__dict__ for i in items])
        for i in items:
            print(f"{i.product_id}  {i.family:55} {i.state:20} {i.percent:5.1f}%  {i.error}")
        return 0
    if cmd == "health":
        h = health.status()
        if as_json:
            return emit({"services": h["services"], "healthy": h["healthy"],
                         "stuck": [j.__dict__ for j in h["stuck"]], "store_queue": [i.__dict__ for i in h["store_queue"]]})
        print("services:", h["services"])
        print("stuck installer jobs:", *[f"\n  {j.package}  {j.operation}  {j.minutes:.0f} min" for j in h["stuck"]] or [" none"])
        print("store queue:", *[f"\n  {i.family}  {i.state}" for i in h["store_queue"]] or [" empty"])
        return 0
    e = Engine(s["market"], s["keep_rollback"], s["holds"])
    t0 = time.time()
    e.scan()
    if not as_json:
        print(f"{len(e.apps)} Store apps ({time.time() - t0:.1f}s)")
    if cmd == "list":
        apps = sorted(e.apps.values(), key=lambda a: a.title.lower())
        if as_json:
            return emit([{"title": a.title, "family": a.family, "version": a.installed.version,
                          "product_id": a.product.product_id if a.product else ""} for a in apps])
        for a in apps:
            print(f"  {a.title[:40]:40} {a.installed.version:18} {a.family}")
        return 0
    if cmd == "export":
        data = [{"family": a.family, "product_id": a.product.product_id if a.product else "", "title": a.title}
                for a in e.apps.values() if a.product]
        open(argv[2], "w", encoding="utf-8").write(json.dumps({"apps": data}, indent=1))
        print(f"saved {len(data)} apps to {argv[2]}")
        return 0
    if cmd == "import":
        want = json.load(open(argv[2], encoding="utf-8"))["apps"]
        missing = [w for w in want if w["family"] not in e.apps and w.get("product_id")]
        print(f"{len(missing)} of {len(want)} not installed here")
        for w in missing:
            app = e.app_for_product(e.catalog.product(w["product_id"]))
            try:
                print(f"  {w['title']}: {e.update(app)}")
            except Exception as ex:
                print(f"  {w['title']}: FAILED {ex}")
        return 0
    t0 = time.time()
    e.check_all()
    if not as_json:
        print(f"checked ({time.time() - t0:.1f}s)")
    if cmd == "updates":
        apps = sorted(e.apps.values(), key=lambda a: a.title.lower())
        frameworks = e.framework_updates()
        others = []
        if s.get("winget", True):
            from storemgr import winget
            if winget.available():
                others = winget.list_upgrades()
        if as_json:
            return emit({"store": [{"title": a.title, "family": a.family, "from": a.current_str, "to": a.latest.version_str,
                                    "size": a.latest.size} for a in apps if a.update_available],
                         "held": [{"title": a.title, "family": a.family, "hold": a.held} for a in apps if a.is_held],
                         "frameworks": [{"name": h.name, "arch": h.arch, "from": h.version, "to": p.version_str}
                                        for h, p in frameworks],
                         "winget": [o.__dict__ for o in others]})
        for a in apps:
            if a.update_available:
                print(f"  UPDATE  {a.title[:36]:36} {a.current_str} -> {a.latest.version_str}  ({a.latest.size / 1048576:.0f} MB)")
            elif a.is_held:
                print(f"  HELD    {a.title[:36]:36} {a.held}")
            elif a.check_error and a.product:
                print(f"  ?       {a.title[:36]:36} {a.check_error[:80]}")
        for h, p in frameworks:
            print(f"  RUNTIME {h.name[:36]:36} {h.version} -> {p.version_str}  ({h.arch})")
        for o in others:
            print(f"  WINGET  {o.name[:36]:36} {o.version} -> {o.available}")
        return 0
    if cmd == "update":
        app = find(e, argv[2])
        if not app:
            print("no such app")
            return 1
        last = [0.0]

        def report(stage, done, total, msg):
            if stage != "download" or time.time() - last[0] > 3 or done == total:
                print(f"  [{stage}] {msg}")
                last[0] = time.time()

        v = e.update(app, report, close_app="--close" in argv)
        print(f"OK {app.title} {v}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
