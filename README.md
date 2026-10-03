# My Store

A Microsoft Store replacement that doesn't jam.

It uses Microsoft's own services - the Store catalogue, the Store's browse/search/review service and the Windows
Update delivery servers the Store downloads from - but replaces the Store app and its install queue.

Unofficial: not made, endorsed or supported by Microsoft. Free apps only; it doesn't get around app licensing.

## Install

Run `MyStore-Setup-<version>.exe` and click through: it installs to Program Files, adds a Start menu entry (and a
desktop shortcut if you want one) and an uninstaller. Optional during setup:

- **Background updates** - a scheduled task that runs as you (no admin) at sign-in and every 6 hours.
- **Open Microsoft Store links in My Store** - registers My Store for `ms-windows-store://` links; Windows then asks
  you to confirm it in Settings > Default apps.

Installing a newer setup over the top upgrades in place and keeps your settings. To pin it, right-click My Store in
the Start menu > Pin to Start / Pin to taskbar (Windows doesn't let installers pin for you).

## What it does

| Page                |                                                                                                                                                                |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Home                | Your status, category chips, shelves: updates for your apps, wishlist, Top free apps/games, Trending, Best-selling games, Top paid                             |
| Search              | Full Store search with Apps/Games, price and sort filters, "Load more"                                                                                         |
| Categories / charts | Top free / paid / trending per category, "See all" grids                                                                                                       |
| App page            | Get / Update / Open, Unjam, Wishlist, What's new (publisher update date + what My Store installed when), requirements, age rating, links, screenshots, reviews |
| Updates             | Available, in progress, needs attention (Retry all / Unjam & retry all), held back, desktop apps, the Store's own stuck queue                                  |
| Library             | All Store apps + desktop apps installed from the Store, sizes, export / import app list                                                                        |
| Downloads           | The queue: pause / resume (keeps partial downloads), cancel, reorder, pause all, parallel downloads, speed limit                                               |
| Wishlist            | Apps starred for later                                                                                                                                         |
| Health              | Installer jam detector, Unjam everything, auto-unjam, Store auto-update switch, clean-up (caches, WindowsApps\Deleted)                                         |
| Settings            | Background updates, notifications, metered-connection pause, holds, region, Store links                                                                        |

Per-app menu: Update, Unjam, Unjam (deep clean), Hold (never update / skip a version), Repair, Reset, Roll back,
Uninstall, Update automatically (background).

Command line: `mystore-cli.exe list | updates | update <app> [--close] | queue | health | export <f> | import <f>`.

## Safety

- Store packages: must be served from a Microsoft address, match Microsoft's SHA-1 digest, and carry a valid
  signature from the Microsoft Marketplace CA or Microsoft's own code-signing CAs (exact names, not "mentions
  Microsoft"), from the same publisher as the copy already installed.
- Desktop-installer apps (Discord, Teams...): the installer must match the SHA-256 in the Store's own install
  recipe and be validly Authenticode-signed.
- Admin actions (Unjam deep clean, WindowsApps clean-up, apps with a Windows service, the Store auto-update
  switch) take one UAC prompt. The elevated part is My Store itself - no scripts are written or run from disk - and
  it only runs from a copy only admins can modify (Program Files). A copy that others can change refuses.
- Work that needs SYSTEM (moving the Store's stuck queue files) runs the same installed program as a one-off task,
  with its files in a `C:\ProgramData\MyStore` folder only SYSTEM and Administrators can write to. Every input is
  validated before it gets anywhere near admin code.
- The background task runs as you, never as admin. Updates that need admin wait until you open My Store.
- One install at a time across the whole PC - overlapping installs are what jam Windows' installer.

## Privacy

No accounts, telemetry or analytics. Everything stays on your PC in `%LOCALAPPDATA%\MyStore\`. My Store talks to
Microsoft's Store and delivery services (sending your region, language, Windows build and the apps it looks up, as
the Store does) and, for desktop-installer apps, to that publisher's download server.

Reporting a problem? Attach `%LOCALAPPDATA%\MyStore\mystore.log` - but look through it first: it contains file
paths that include your Windows user name.

## Building

Needs Python 3.12+ and Inno Setup 6. `pwsh -File build.ps1` makes a clean venv from the hash-pinned
`requirements.lock`, runs the tests, builds `dist\MyStore\` with PyInstaller and the installer
`dist\MyStore-Setup-<version>.exe`. From source: `python main.py` (admin actions are off when the source folder can
be changed without admin rights - use the installed build for those).

## Files

- `main.py` - entry point (window, `--auto`, admin/SYSTEM roles); `app.py` - the window; `cli.py` - command line
- `storemgr/` - engine (`engine.py`, `fe3.py`, `catalog.py`, `download.py`, `winapps.py`), browsing (`browse.py`),
  desktop installers (`wpm.py`), queue (`dlqueue.py`), background (`background.py`), health/unjam (`health.py`,
  `storequeue.py`), admin (`admin.py` caller side, `helper.py` elevated/SYSTEM side, `secure.py` permission checks),
  `cleanup.py`, `settings.py`, `winsys.py`, `ui/`
- `installer/MyStore.iss`, `MyStore.spec`, `build.ps1` - packaging; `tests/` - pytest
