"""Headless Unjammed.
  python cli.py list | updates | update <name-or-family> [--close] | queue | health
  python cli.py auto                  one background pass (same as Unjammed.exe --auto)
  python cli.py export <file.json>    save the list of Store apps on this PC
  python cli.py import <file.json>    install everything in that list that is missing (store apps)"""

import json
import sys
import time

from storemgr import __version__, background, health, settings, storequeue
from storemgr.engine import Engine


def find(e, key):
    key = key.lower()
    apps = list(e.apps.values())
    return (next((a for a in apps if key in (a.title.lower(), a.family.lower())), None) or
            next((a for a in apps if a.family.lower().startswith(key)), None) or
            min((a for a in apps if key in a.title.lower() or key in a.family.lower()), key=lambda a: len(a.title), default=None))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "updates"
    if cmd in ("--version", "version"):
        print(f"Unjammed {__version__}")
        return 0
    s = settings.load()
    if cmd == "auto":
        out = background.run(s)
        print(json.dumps(out, indent=1))
        return 0
    if cmd == "queue":
        for i in storequeue.items():
            print(f"{i.product_id}  {i.family:55} {i.state:20} {i.percent:5.1f}%  {i.error}")
        return 0
    if cmd == "health":
        h = health.status()
        print("services:", h["services"])
        print("stuck installer jobs:", *[f"\n  {j.package}  {j.operation}  {j.minutes:.0f} min" for j in h["stuck"]] or [" none"])
        print("store queue:", *[f"\n  {i.family}  {i.state}" for i in h["store_queue"]] or [" empty"])
        return 0
    e = Engine(s["market"], s["keep_rollback"], s["holds"])
    t0 = time.time()
    e.scan()
    print(f"{len(e.apps)} Store apps ({time.time() - t0:.1f}s)")
    if cmd == "list":
        for a in sorted(e.apps.values(), key=lambda a: a.title.lower()):
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
    print(f"checked ({time.time() - t0:.1f}s)")
    if cmd == "updates":
        for a in sorted(e.apps.values(), key=lambda a: a.title.lower()):
            if a.update_available:
                print(f"  UPDATE  {a.title[:36]:36} {a.current_str} -> {a.latest.version_str}  ({a.latest.size / 1048576:.0f} MB)")
            elif a.is_held:
                print(f"  HELD    {a.title[:36]:36} {a.held}")
            elif a.check_error and a.product:
                print(f"  ?       {a.title[:36]:36} {a.check_error[:80]}")
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
