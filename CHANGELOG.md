# Changelog

## [1.2.1] - 2026-10-09

### Fixed

- Right after **Unjam**, Windows can take a while to answer while its install services restart. Storely asked it for
  the last boot time through PowerShell and showed a raw "timed out" command when that was slow. Boot time and service
  status now come straight from Windows (instant), the installer-log check is skipped for one round if Windows is busy,
  and any slow answer is reported in plain words.

## [1.2.0] - 2026-10-03

First public release, and a new name: My Store is now **Storely**. Installing it upgrades My Store in place and
keeps your settings, history, holds and wishlist.

### New

- **Your other programs too**: Chrome, 7-Zip, Steam, Zoom and the rest update from the same Updates page, through
  winget.
- **Permission warnings**: if an update wants more access than the version you have (camera, microphone, your files,
  full desktop access...), it waits in Downloads for your OK. Each app's page lists what it can access.
- **Windows runtimes**: shared parts Store apps run on (Visual C++ runtime, UI libraries, .NET Native, Windows App
  Runtime) update on their own.
- **Install an older version** of any Store app Microsoft still serves, and hold it there.
- **Offline copies**: save an app and everything it needs to a folder or USB stick; install it on another PC with no
  internet (Library > Install from folder).
- **Preinstalled extras**: remove Clipchamp, News, Candy Crush and other preinstalled apps for your account, and put
  them back any time (Health).
- **Choose the drive** new apps install to, and move installed apps to another drive.
- **Self-updating**: Storely tells you about new versions and installs them after checking its own signature.
- **Store links**: links to the Microsoft Store can open in Storely instead (optional, you choose it in Windows
  Settings). Paste a Store web link into search to open that app.
- **Light theme**, following Windows or your choice.
- **Notifications with buttons** ("Update all", "Open"), quiet hours, and a wait-for-the-charger option.
- **Service self-test** on the Health page; `storely-cli selftest`, and `--json` output for scripting.
- **Native ARM64 build** alongside x64.

### Fixed

- Updates for apps with date-style versions (XBOX 2608 -> 2609, Store Experience Host) were missed.
- Apps that ship two parallel lines (Realtek Audio Control 1.x and 2.x) are kept on the line you have.
- The background updater could show an admin prompt out of nowhere; updates that need admin now wait for you.
- Downloads and installs now check for free disk space first instead of failing halfway.

### Security

- The admin and SYSTEM helpers are part of the installed program: no scripts are written to disk or run from
  folders other accounts can change. Admin actions refuse to run from a copy standard users can modify.
- SYSTEM work files live in a folder only SYSTEM and Administrators can write to; every input to admin code is
  validated.
- Exact signer and issuer checks for Store packages; desktop installers must be validly signed as well as matching
  the Store's SHA-256.
- Dependencies are pinned by hash; links from Store listings open only if they are web links.

## [1.1.0] - 2026-10-02

My Store: installer build, Store link hand-over, security fixes.

## [1.0.0] - 2026-10-02

My Store: first version.
