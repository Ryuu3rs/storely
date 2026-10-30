"""Storely entry point: the window, or with a flag one of its background roles.

  Storely.exe [ms-windows-store://... link]    the window (or hand the link to the one already open)
  Storely.exe --auto                           one background update pass (the scheduled task runs this)
  Storely.exe --enable-background              register that scheduled task for the current user
  Storely.exe --elevated ... / --system-task   admin / SYSTEM helper (started by Storely itself)"""

import sys


def main(argv: list[str]) -> int:
    flag = argv[1] if len(argv) > 1 else ""
    if flag == "--elevated":
        from storemgr.helper import elevated_main
        return elevated_main(argv[2:])
    if flag == "--system-task":
        from storemgr.helper import system_main
        return system_main(argv[2:])
    if flag == "--auto":
        from storemgr import background, settings
        background.run(settings.load())
        return 0
    if flag == "--import-check":           # build smoke test: every module loads in the frozen app (no window)
        return import_check(argv[2] if len(argv) > 2 else "")
    if flag == "--enable-background":      # the installer's "background updates" option (runs as you, not admin)
        from storemgr import background
        return 0 if background.register()[0] else 1
    from app import main as window
    return window(argv[1:])


def import_check(report: str) -> int:
    """Import the window and every storemgr module. A windowed exe can't print, so failures go to `report`."""
    import importlib
    import pkgutil
    import traceback
    try:
        import app  # noqa: F401
        import storemgr
        names = [m.name for m in pkgutil.walk_packages(storemgr.__path__, "storemgr.")]
        for name in names:
            importlib.import_module(name)
        from nacl.signing import VerifyKey  # noqa: F401 - compiled parts load only on first use
        VerifyKey(bytes(32))
        if len(names) < 20:
            raise RuntimeError(f"only {len(names)} storemgr modules found in the build")
        return 0
    except BaseException:
        if report:
            with open(report, "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
