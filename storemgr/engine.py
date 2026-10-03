"""Update engine: what is installed, what is newer, and getting it installed - without the Store app or its queue."""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import DATA_DIR, DOWNLOAD_DIR, LOG_FILE, ROLLBACK_DIR, admin, fe3, storequeue, winapps
from .catalog import Catalog, Product
from .download import Cancelled, fetch
from .fe3 import PackageFile
from .winsys import InstallLock

log = logging.getLogger("unjammed")
if not log.handlers:
    h = logging.FileHandler(LOG_FILE, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)

SKIP_FAMILIES = {"Microsoft.WindowsStore_8wekyb3d8bbwe"}


class NotYetOut(RuntimeError):
    """Nothing newer is actually downloadable yet - not a failure, just wait."""


@dataclass
class Prepared:
    pkg: PackageFile
    main: Path
    deps: list


CHANGELOG_FILE = DATA_DIR / "changelog.json"


def _changelog(app, old: str, new: str, pkg) -> None:
    """Per-app record of what Unjammed installed and when - the 'What's new' history."""
    try:
        data = json.loads(CHANGELOG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault(app.family, []).append({"t": time.time(), "from": old, "to": new, "size": pkg.size,
                                            "file": pkg.filename})
    data[app.family] = data[app.family][-50:]
    CHANGELOG_FILE.write_text(json.dumps(data), encoding="utf-8")


def changelog(family: str) -> list[dict]:
    try:
        return json.loads(CHANGELOG_FILE.read_text(encoding="utf-8")).get(family, [])
    except (OSError, ValueError):
        return []


@dataclass
class App:
    family: str
    installed: winapps.Installed | None
    product: Product | None
    entries: list = field(default_factory=list)
    latest: PackageFile | None = None
    check_error: str = ""
    files: list = field(default_factory=list)
    bundle: winapps.Installed | None = None
    pool: list = field(default_factory=list)
    held: str = ""          # "all" = never update, or a version string to skip

    @property
    def current(self) -> tuple:
        """Installed version on the same footing as `latest` (bundles are versioned separately from the app inside)."""
        if self.latest and self.latest.ext.endswith("bundle") and self.bundle:
            return self.bundle.vt
        return self.installed.vt if self.installed else (0,)

    @property
    def current_str(self) -> str:
        return ".".join(map(str, self.current))

    @property
    def title(self) -> str:
        if self.product:
            return self.product.title
        if self.entries and self.entries[0].display_name and not self.entries[0].display_name.startswith("ms-resource"):
            return self.entries[0].display_name
        return (self.installed.name if self.installed else self.family).split(".")[-1]

    @property
    def update_available(self) -> bool:
        return bool(self.latest and self.installed and self.latest.version > self.current and not self.is_held)

    @property
    def is_held(self) -> bool:
        return bool(self.held) and (self.held == "all" or (self.latest is not None and self.held == self.latest.version_str))

    @property
    def package_name(self) -> str:
        return self.installed.name if self.installed else self.family.rsplit("_", 1)[0]


class Engine:
    def __init__(self, market: str = "GB", keep_rollback: bool = False, holds: dict | None = None):
        self.catalog = Catalog(market)
        self.keep_rollback = keep_rollback
        self.holds = holds if holds is not None else {}    # family -> "all" | version to skip
        self.apps: dict[str, App] = {}
        self.all_installed: list[winapps.Installed] = []
        self.allow_admin = True     # False in the background updater: no surprise admin prompts
        self._install_lock = InstallLock()   # Windows' installer jams when jobs overlap: one at a time, PC-wide

    # ------------------------------------------------------------------ inventory

    def scan(self, progress=None) -> dict[str, App]:
        self.all_installed = winapps.installed()
        fams: dict[str, winapps.Installed] = {}
        bundles = {p.family: p for p in self.all_installed if p.is_bundle}
        for p in self.all_installed:
            if p.is_bundle or p.is_framework or p.is_resource or not p.is_store or p.family in SKIP_FAMILIES:
                continue
            cur = fams.get(p.family)
            if cur is None or (p.arch in (winapps.ARCH, "neutral") and p.vt >= cur.vt):
                fams[p.family] = p
        apps: dict[str, App] = {}

        def one(fam):
            pkg = fams[fam]
            try:
                prod = self.catalog.by_family(fam)
            except Exception as e:
                log.warning("catalog lookup %s: %s", fam, e)
                prod = None
            return App(fam, pkg, prod, winapps.manifest_apps(pkg.location), bundle=bundles.get(fam))

        with ThreadPoolExecutor(8) as ex:
            for i, app in enumerate(ex.map(one, list(fams))):
                apps[app.family] = app
                if progress:
                    progress(i + 1, len(fams))
        self.catalog.save()
        self.apps = apps
        return apps

    def check(self, app: App) -> App:
        app.check_error = ""
        app.held = self.holds.get(app.family, "")
        if not app.product or not app.product.wu_category:
            app.check_error = "not updatable from the Store catalogue"
            return app
        try:
            app.files = fe3.for_this_pc(fe3.packages(app.product.wu_category), app.product.platforms, winapps.ARCH)
            mine = [f for f in app.files if f.name.lower() == app.package_name.lower()]
            if app.bundle and any(f.ext.endswith("bundle") for f in mine):
                pool, line = [f for f in mine if f.ext.endswith("bundle")], app.bundle.vt
            else:
                pool, line = [f for f in mine if not f.ext.endswith("bundle")] or mine, app.installed.vt if app.installed else None
            mine_here = [f for f in pool if f.arch in (winapps.ARCH, "neutral", "")]
            offered = fe3.majors(mine_here)
            app.pool = [f for f in mine_here if not line or fe3.same_line(f.version, line, offered)]
            app.latest = fe3.best(pool, app.package_name, winapps.ARCH, line)
            if not app.latest and not pool:
                app.check_error = "no build for this edition of Windows in Microsoft's delivery service"
            # pool but nothing on this version line: Microsoft only has other-edition builds - nothing to update
        except Exception as e:
            app.check_error = f"check failed: {e}"
        return app

    def check_all(self, progress=None) -> None:
        apps = [a for a in self.apps.values() if a.product and a.product.wu_category]
        with ThreadPoolExecutor(6) as ex:
            for i, _ in enumerate(ex.map(self.check, apps)):
                if progress:
                    progress(i + 1, len(apps))

    # ------------------------------------------------------------------ install

    def _get(self, pkg: PackageFile, publisher: str | None, report, cancel, url: str | None = None) -> Path:
        dest = DOWNLOAD_DIR / pkg.filename
        report("download", 0, pkg.size, f"Downloading {pkg.name} {pkg.version_str}")
        fetch(url or fe3.download_url(pkg), dest, pkg.size, pkg.digest,
              progress=lambda d, t, s: report("download", d, t, f"{d / 1048576:.0f} / {t / 1048576:.0f} MB  ({s / 1048576:.1f} MB/s)"),
              cancel=cancel)
        report("verify", 0, 0, "Checking Microsoft signature")
        ok, why = winapps.verify_signature(dest, publisher)
        if not ok:
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"signature check failed - deleted ({why})")
        log.info("verified %s: %s", pkg.filename, why)
        return dest

    def _dependencies(self, main: Path, files: list[PackageFile], report, cancel) -> list[Path]:
        paths = []
        for dep in winapps.package_dependencies(main):
            have = winapps.newest(self.all_installed, dep.name)
            if have and have.vt >= dep.min_version:
                continue
            report("deps", 0, 0, f"Needs {dep.name} {'.'.join(map(str, dep.min_version))}")
            cand = fe3.best(files, dep.name, winapps.ARCH)
            if not cand or cand.version < dep.min_version:
                prod = self.catalog.by_family(dep.family)
                if not prod or not prod.wu_category:
                    raise RuntimeError(f"needs {dep.name} {dep.min_version}, which is not in the Store catalogue")
                cand = fe3.best(fe3.packages(prod.wu_category), dep.name, winapps.ARCH)
            if not cand or cand.version < dep.min_version:
                raise RuntimeError(f"needs {dep.name} >= {dep.min_version}; Microsoft offers {cand.version_str if cand else 'nothing'}")
            paths.append(self._get(cand, dep.publisher, report, cancel))
        return paths

    def prepare(self, app: App, report=lambda *a: None, cancel: threading.Event | None = None) -> "Prepared":
        """Download + verify the newest downloadable version and its frameworks. Safe to run several at once."""
        cancel = cancel or threading.Event()
        if not app.latest:
            self.check(app)
        if not app.latest:
            raise RuntimeError(app.check_error or "nothing to install")
        publisher = app.installed.publisher if app.installed else None
        # newest first; a version can be announced before its download is live - fall back to the next one
        current = app.current if app.installed else (0,)
        cands = sorted({f.identity: f for f in (app.pool or [app.latest]) if f.version > current}.values(),
                       key=lambda f: (f.version, f.arch == winapps.ARCH), reverse=True) or [app.latest]
        pkg = url = None
        for cand in cands:
            try:
                url = fe3.download_url(cand)
                pkg = cand
                break
            except fe3.NotPublished as e:
                log.info("%s", e)
        if not pkg:
            app.latest = None
            app.check_error = f"newest version announced but not downloadable yet ({cands[0].version_str})"
            raise NotYetOut(app.check_error)
        log.info("update %s -> %s", app.family, pkg.identity)
        stale = storequeue.cancel(app.family)   # the Store's own copy of this job would fight ours
        if stale:
            log.info("cancelled Store queue items: %s", stale)
        main = self._get(pkg, publisher, report, cancel, url)
        deps = self._dependencies(main, app.files, report, cancel)
        return Prepared(pkg, main, deps)

    def install(self, app: App, prep: "Prepared", report=lambda *a: None, cancel: threading.Event | None = None,
                close_app: bool = False, install_timeout: float = 900) -> str:
        """Install a prepared download. Windows' installer jams when jobs overlap, so this is one at a time."""
        cancel = cancel or threading.Event()
        pkg, main, deps = prep.pkg, prep.main, prep.deps
        if app.installed and winapps.running(app.installed.location) and not close_app:
            raise RuntimeError(f"{app.title} is open - close it, or choose 'close and update'")
        report("install", 0, 0, "Waiting for Windows' installer" if self._install_lock.locked() else "Installing")
        with self._install_lock:
            if cancel.is_set():
                raise Cancelled()
            report("install", 0, 0, "Installing")
            for d in deps:
                ok, err = winapps.install(d, timeout=install_timeout)
                if not ok and "higher version" not in err.lower():
                    raise RuntimeError(f"dependency {d.name}: {err}")
            ok, err = winapps.install(main, close_app=close_app, timeout=install_timeout)
            if not ok and "0x80073D28" in err and self.allow_admin:
                # the package installs a Windows service (Codex does) - Windows insists on admin rights for that
                report("install", 0, 0, "This app installs a Windows service - approve the admin prompt")
                log.info("%s needs admin (packaged service) - elevating", pkg.identity)
                r = admin.install(main, close_app=close_app, publisher=app.installed.publisher if app.installed else None)
                ok, err = r.get("ok", False), "; ".join(r.get("errors", [])) or "admin install failed"
            if not ok:
                raise RuntimeError(err)
        self.all_installed = winapps.installed()
        now = winapps.newest(self.all_installed, app.package_name)
        bundle = next((p for p in self.all_installed if p.is_bundle and p.family == app.family), None)
        got = bundle.vt if pkg.ext.endswith("bundle") and bundle else (now.vt if now else (0,))
        if not now or got < pkg.version:
            raise RuntimeError(f"Windows reported success but {app.package_name} is still {'.'.join(map(str, got))}")
        old = app.current_str if app.installed else ""
        app.installed, app.bundle = now, bundle
        app.entries = winapps.manifest_apps(now.location)
        if app.family not in self.apps:
            self.apps[app.family] = app
        if self.keep_rollback:
            keep = ROLLBACK_DIR / app.package_name
            shutil.rmtree(keep, ignore_errors=True)
            keep.mkdir(parents=True, exist_ok=True)
            shutil.move(str(main), keep / main.name)
        else:
            main.unlink(missing_ok=True)
        for d in deps:
            d.unlink(missing_ok=True)
        log.info("installed %s %s", app.package_name, now.version)
        _changelog(app, old, now.version, pkg)
        report("done", 1, 1, f"Installed {now.version}")
        return now.version

    def update(self, app: App, report=lambda *a: None, cancel: threading.Event | None = None,
               close_app: bool = False, install_timeout: float = 900) -> str:
        """Download, verify and install the newest version (or a fresh install). Returns the installed version."""
        prep = self.prepare(app, report, cancel)
        return self.install(app, prep, report, cancel, close_app, install_timeout)
    def app_for_product(self, product: Product) -> App:
        """An App for a catalogue product - the installed one if present, else a fresh-install candidate."""
        if product.pfn and product.pfn in self.apps:
            return self.apps[product.pfn]
        if product.pfn:
            for a in self.apps.values():
                if a.family.lower() == product.pfn.lower():
                    return a
        return App(product.pfn or product.product_id, None, product)

    def rollback(self, app: App, close_app: bool = True) -> str:
        f = self.rollback_file(app)
        if not f:
            raise RuntimeError("no saved previous version")
        ok, why = winapps.verify_signature(f, app.installed.publisher if app.installed else None)
        if not ok:
            raise RuntimeError(f"the saved previous version failed the signature check ({why})")
        with self._install_lock:
            ok, err = winapps.install(f, close_app=close_app)
        if not ok:
            raise RuntimeError(err)
        self.all_installed = winapps.installed()
        app.installed = winapps.newest(self.all_installed, app.package_name)
        log.info("rolled back %s to %s", app.package_name, app.installed.version if app.installed else "?")
        return app.installed.version if app.installed else "?"

    def rollback_file(self, app: App) -> Path | None:
        d = ROLLBACK_DIR / app.package_name
        files = sorted(d.glob("*.*")) if d.exists() else []
        return files[-1] if files else None
