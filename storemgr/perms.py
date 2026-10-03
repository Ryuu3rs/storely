"""Permissions (capabilities) an app update adds - shown before it installs, which the Store never does."""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .winapps import ARCH

RISK_ORDER = {"high": 0, "medium": 1, "low": 2}

# lower-cased name -> (canonical name, short label, plain-English label, risk)
_TABLE: dict[str, tuple[str, str, str, str]] = {k.lower(): (k, s, l, r) for k, s, l, r in [
    ("runFullTrust", "full desktop access", "runs as a normal desktop program with full access as you", "high"),
    ("broadFileSystemAccess", "all your files", "full access to all your files", "high"),
    ("allowElevation", "admin rights", "can run as administrator", "high"),
    ("packagedServices", "Windows service", "installs a Windows service", "high"),
    ("localSystemServices", "Windows service", "installs a Windows service that runs as the system", "high"),
    ("customInstallActions", "setup program", "runs its own setup program during install", "high"),
    ("inputInjectionBrokered", "keyboard and mouse control", "can type and click for you", "high"),
    ("inputObservation", "keystroke watching", "can see everything you type", "high"),
    ("inputSuppression", "input blocking", "can block your keyboard and mouse input", "high"),
    ("uiAccess", "control of other windows", "can control other apps' windows", "high"),
    ("packageManagement", "app management", "can install and remove other apps", "high"),
    ("systemManagement", "system management", "can change system settings like the clock", "high"),
    ("emailSystem", "all your email", "full access to all your email accounts", "high"),
    ("unvirtualizedResources", "outside its sandbox", "writes to the registry and files outside its own sandbox", "medium"),
    ("webcam", "webcam", "your camera", "medium"),
    ("microphone", "microphone", "your microphone", "medium"),
    ("location", "location", "your location", "medium"),
    ("locationHistory", "location history", "your location history", "medium"),
    ("contacts", "contacts", "your contacts", "medium"),
    ("appointments", "calendar", "your calendar", "medium"),
    ("phoneCall", "phone calls", "can make phone calls", "medium"),
    ("phoneCallHistory", "call history", "your call history", "medium"),
    ("chat", "text messages", "your text messages", "medium"),
    ("smsSend", "send texts", "can send text messages", "medium"),
    ("email", "email", "your email", "medium"),
    ("userAccountInformation", "account info", "your name and account picture", "medium"),
    ("userDataTasks", "tasks", "your to-do tasks", "medium"),
    ("userNotificationListener", "notifications", "can read your notifications", "medium"),
    ("picturesLibrary", "pictures", "your Pictures folder", "medium"),
    ("videosLibrary", "videos", "your Videos folder", "medium"),
    ("musicLibrary", "music", "your Music folder", "medium"),
    ("documentsLibrary", "documents", "your Documents folder", "medium"),
    ("removableStorage", "USB drives", "USB drives and memory cards", "medium"),
    ("appDiagnostics", "other apps' activity", "can see what other apps are running", "medium"),
    ("packageQuery", "installed apps list", "can see which apps you have installed", "medium"),
    ("graphicsCapture", "screen capture", "can record your screen (you pick what)", "medium"),
    ("graphicsCaptureProgrammatic", "screen capture", "can record your screen without asking each time", "medium"),
    ("enterpriseAuthentication", "work sign-in", "signs in with your work account", "medium"),
    ("sharedUserCertificates", "certificates", "your certificates and smart cards", "medium"),
    ("modifiableApp", "modifiable files", "lets other programs change its files", "medium"),
    ("smbios", "hardware IDs", "reads your PC's hardware and serial number info", "medium"),
    ("appLicensing", "licence check", "checks its Store licence", "low"),
    ("storeLicenseManagement", "licence check", "manages its Store licences", "low"),
    ("systemAIModels", "Windows AI models", "uses the AI models built into Windows", "low"),
    ("bluetooth", "Bluetooth", "Bluetooth devices", "low"),
    ("internetClient", "internet", "the internet", "low"),
    ("internetClientServer", "incoming connections", "accepts connections from the internet", "low"),
    ("privateNetworkClientServer", "home network", "your home or work network", "low"),
    ("extendedExecutionUnconstrained", "runs in background", "keeps running in the background", "low"),
    ("extendedBackgroundTaskTime", "long background tasks", "runs long background tasks", "low"),
    ("backgroundMediaPlayback", "background audio", "plays media in the background", "low"),
    ("usb", "USB devices", "USB devices", "low"),
    ("humaninterfacedevice", "game controllers", "game controllers and similar devices", "low"),
    ("serialcommunication", "serial ports", "serial port devices", "low"),
    ("proximity", "NFC", "nearby devices (NFC)", "low"),
    ("radios", "radios", "can turn Wi-Fi and Bluetooth on or off", "low"),
    ("wiFiControl", "Wi-Fi", "can scan and connect to Wi-Fi", "low"),
    ("gazeInput", "eye tracking", "eye tracker input", "low"),
    ("remoteSystem", "your other devices", "talks to your other devices", "low"),
    ("spatialPerception", "surroundings", "maps your surroundings (mixed reality)", "low"),
    ("globalMediaControl", "media control", "can control media playing in other apps", "low"),
    ("confirmAppClose", "close prompt", "can ask before closing", "low"),
    ("objects3D", "3D objects", "your 3D Objects folder", "low"),
    ("voipCall", "calls", "can make internet calls", "low"),
    ("codeGeneration", "code generation", "generates code at runtime", "low"),
]}


@dataclass
class Perm:
    name: str
    label: str
    risk: str
    short: str = ""


@dataclass
class Change:
    added: list[Perm] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def _words(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|[._\-]+", " ", name)
    return re.sub(r"\s+", " ", s).strip().lower() or name


def describe(name: str) -> Perm:
    hit = _TABLE.get(name.lower())
    if hit:
        canon, short, label, risk = hit
        return Perm(canon, label, risk, short)
    if name.startswith("{"):
        return Perm(name, "a specific hardware device", "medium", "a hardware device")
    w = _words(name)
    return Perm(name, w, "medium", w)


def _canon(name: str) -> str:
    hit = _TABLE.get(name.lower())
    return hit[0] if hit else name


def capabilities(manifest: bytes | str) -> set[str]:
    """Capability names declared in an AppxManifest.xml (any namespace: uap*, rescap, DeviceCapability)."""
    root = ET.fromstring(manifest)
    out = set()
    for el in root.findall("{*}Capabilities/*"):
        if el.tag.rsplit("}", 1)[-1] in ("Capability", "DeviceCapability") and el.get("Name"):
            out.add(_canon(el.get("Name").strip()))
    return out


def capabilities_installed(location: str) -> set[str]:
    try:
        return capabilities((Path(location) / "AppxManifest.xml").read_bytes())
    except (OSError, ET.ParseError):
        return set()


def _package_manifest(path: Path, arch: str) -> bytes | None:
    """AppxManifest.xml of a .msix/.appx, or of the matching application package inside a bundle (stubs skipped)."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "AppxMetadata/AppxBundleManifest.xml" not in names:
            return z.read("AppxManifest.xml")
        bm = ET.fromstring(z.read("AppxMetadata/AppxBundleManifest.xml"))
        pkgs = [p for p in bm.iter() if p.tag.endswith("}Package") and p.get("Type", "application") == "application"
                and "stub" not in (p.get("FileName") or "").replace("\\", "/").lower().split("/")[:-1]]
        # explicit None checks: an Element with no children is falsy, so `a or b` would skip a valid match
        by_arch = {}
        for p in pkgs:
            by_arch.setdefault((p.get("Architecture") or "").lower(), p)
        pick = by_arch.get(arch)
        pick = pick if pick is not None else by_arch.get("neutral")
        pick = pick if pick is not None else (pkgs[0] if pkgs else None)
        inner_name = (pick.get("FileName") or "").replace("\\", "/") if pick is not None else ""
        if inner_name not in names:
            return None
        with zipfile.ZipFile(io.BytesIO(z.read(inner_name))) as inner:
            return inner.read("AppxManifest.xml")


def capabilities_package(path: Path, arch: str = ARCH) -> set[str]:
    try:
        manifest = _package_manifest(Path(path), arch.lower())
        return capabilities(manifest) if manifest else set()
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return set()


def diff(old: set[str], new: set[str]) -> Change:
    """What `new` asks for that `old` didn't (riskiest first), and what it dropped. Case-insensitive."""
    o, n = {x.lower(): x for x in old}, {x.lower(): x for x in new}
    added = sorted((describe(n[k]) for k in n.keys() - o.keys()), key=lambda p: (RISK_ORDER[p.risk], p.name.lower()))
    removed = sorted((o[k] for k in o.keys() - n.keys()), key=str.lower)
    return Change(added, removed)


def summary(change: Change, show: int = 2) -> str:
    """One short line, e.g. 'Adds: webcam, microphone, +2 more'. Empty when nothing is added."""
    if not change.added:
        return ""
    names = list(dict.fromkeys(p.short or p.label for p in change.added))
    more = len(names) - show
    return "Adds: " + ", ".join(names[:show]) + (f", +{more} more" if more > 0 else "")


def has_risky(change: Change) -> bool:
    return any(p.risk in ("high", "medium") for p in change.added)
