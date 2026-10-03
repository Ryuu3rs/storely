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
    if flag == "--enable-background":      # the installer's "background updates" option (runs as you, not admin)
        from storemgr import background
        return 0 if background.register()[0] else 1
    from app import main as window
    return window(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
