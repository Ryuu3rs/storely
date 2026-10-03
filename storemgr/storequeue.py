"""The Microsoft Store's own install queue (the one that gets stuck on "Preparing"): read it and cancel items."""

from __future__ import annotations

from dataclasses import dataclass

STATES = {0: "Pending", 1: "Starting", 2: "Acquiring licence", 3: "Downloading", 4: "Restoring data", 5: "Installing",
          6: "Completed", 7: "Cancelled", 8: "Paused", 9: "Error", 10: "Paused (low battery)",
          11: "Paused (Wi-Fi recommended)", 12: "Paused (Wi-Fi required)", 13: "Ready to download"}


@dataclass
class QueueItem:
    product_id: str
    family: str
    state: str
    percent: float
    error: str


def _manager():
    from winrt.windows.applicationmodel.store.preview.installcontrol import AppInstallManager
    return AppInstallManager()


def items() -> list[QueueItem]:
    try:
        m = _manager()
        out = []
        for it in m.app_install_items:
            st = it.get_current_status()
            err = st.error_code.value if getattr(st, "error_code", None) else 0
            out.append(QueueItem(it.product_id, it.package_family_name, STATES.get(int(st.install_state), str(st.install_state)),
                                 float(st.percent_complete or 0), f"0x{err & 0xffffffff:08X}" if err else ""))
        return out
    except Exception:
        return []


def cancel(family_or_product: str) -> list[str]:
    """Cancel every Store queue item for a package family (or product id). Returns what was cancelled."""
    key = family_or_product.lower()
    done = []
    try:
        for it in _manager().app_install_items:
            if key in (it.product_id.lower(), it.package_family_name.lower()) or \
                    it.package_family_name.lower().startswith(key.split("_")[0] + "_") and "_" not in key:
                it.cancel()
                done.append(f"{it.product_id} ({it.package_family_name})")
    except Exception as e:
        done.append(f"error: {e}")
    return done
