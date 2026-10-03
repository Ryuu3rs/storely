"""Settings shared by the app, the background updater and the CLI."""

from __future__ import annotations

import json

from . import DATA_DIR

FILE = DATA_DIR / "settings.json"
DEFAULTS = {
    "close_apps": False, "keep_rollback": False, "check_on_start": True, "watchdog": True, "market": "GB",
    "auto_update": [],              # families updated in the background ("ticked")
    "background_mode": "ticked",    # "ticked" | "all"
    "background_desktop": True,     # also update desktop-installer apps installed via Storely
    "auto_unjam": True,             # cancel the Store's stuck items automatically when a jam is seen
    "notify": True,
    "pause_on_metered": True,
    "parallel_downloads": 2,
    "speed_limit_mbps": 0,
    "holds": {},                    # family -> "all" | version to skip
    "wishlist": [],                 # [{product_id, title, icon_url, tile_color}]
    "theme": "system",              # "system" | "dark" | "light"
    "pause_on_battery": False,
    "quiet_hours": [],              # [start_hour, end_hour]: no background installs or notifications
    "winget": True,                 # also show/update other apps through winget
    "ask_new_permissions": True,    # hold updates that add risky permissions until you approve
    "self_update": "notify",        # "notify" | "off"
    "skipped_update": "",
}


def load() -> dict:
    s = json.loads(json.dumps(DEFAULTS))
    try:
        s.update(json.loads(FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return s


def save(s: dict) -> None:
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2), encoding="utf-8")
    tmp.replace(FILE)
