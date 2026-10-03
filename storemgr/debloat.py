"""Remove preinstalled clutter: a curated list of Windows 11 extras that are safe to remove for this user and can be
put back from the Store. Removal is per-user (Remove-AppxPackage, no admin); Windows keeps its provisioned copy, so
new user accounts still get them and a big Windows update can bring some back."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from . import DATA_DIR, winapps

REMOVED_FILE = DATA_DIR / "removed.json"

MS_EXTRAS = "Microsoft extras"
GAMES = "Games"
PROMOTED = "Promoted third-party"
GROUPS = (MS_EXTRAS, GAMES, PROMOTED)


@dataclass(frozen=True)
class Entry:
    family: str
    title: str
    description: str
    product_id: str
    group: str

    @property
    def name(self) -> str:
        return self.family.rsplit("_", 1)[0]


# every family + product id checked against Microsoft's catalogue (displaycatalog lookup both ways) on 2026-10-03
PRESETS: tuple[Entry, ...] = (
    Entry("Clipchamp.Clipchamp_yxz26nhyzhsrt", "Microsoft Clipchamp", "Video editor", "9P1J8S7CCWWT", MS_EXTRAS),
    Entry("Microsoft.BingNews_8wekyb3d8bbwe", "Microsoft News", "News headlines from MSN", "9WZDNCRFHVFW", MS_EXTRAS),
    Entry("Microsoft.BingWeather_8wekyb3d8bbwe", "MSN Weather", "Weather forecasts from MSN", "9WZDNCRFJ3Q2", MS_EXTRAS),
    Entry("Microsoft.BingSearch_8wekyb3d8bbwe", "Microsoft Bing", "Bing search app", "9NZBF4GT040C", MS_EXTRAS),
    Entry("Microsoft.GetHelp_8wekyb3d8bbwe", "Get Help", "Microsoft support chat; some Settings troubleshooters open it",
          "9PKDZBMV1H3T", MS_EXTRAS),
    Entry("Microsoft.Getstarted_8wekyb3d8bbwe", "Microsoft Tips", "Tips and tours for new Windows users", "9WZDNCRDTBJJ",
          MS_EXTRAS),
    Entry("Microsoft.WindowsFeedbackHub_8wekyb3d8bbwe", "Feedback Hub", "Send feedback and bug reports to Microsoft",
          "9NBLGGH4R32N", MS_EXTRAS),
    Entry("Microsoft.WindowsMaps_8wekyb3d8bbwe", "Windows Maps", "Maps and directions", "9WZDNCRDTBVB", MS_EXTRAS),
    Entry("Microsoft.People_8wekyb3d8bbwe", "Microsoft People", "Old contacts app", "9NBLGGH10PG8", MS_EXTRAS),
    Entry("Microsoft.PowerAutomateDesktop_8wekyb3d8bbwe", "Power Automate", "Desktop automation flows", "9NFTCH6J7FHV",
          MS_EXTRAS),
    Entry("Microsoft.Todos_8wekyb3d8bbwe", "Microsoft To Do", "Task lists synced to a Microsoft account", "9NBLGGH5R558",
          MS_EXTRAS),
    Entry("Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe", "Microsoft Sticky Notes", "Desktop sticky notes",
          "9NBLGGH4QGHW", MS_EXTRAS),
    Entry("MicrosoftCorporationII.MicrosoftFamily_8wekyb3d8bbwe", "Microsoft Family Safety",
          "Parental controls dashboard (family settings still work online)", "9PDJDJS743XF", MS_EXTRAS),
    Entry("Microsoft.OutlookForWindows_8wekyb3d8bbwe", "Outlook (new)", "The new Outlook mail and calendar app",
          "9NRX63209R7B", MS_EXTRAS),
    Entry("microsoft.windowscommunicationsapps_8wekyb3d8bbwe", "Mail and Calendar", "Retired mail app replaced by Outlook",
          "9WZDNCRFHVQM", MS_EXTRAS),
    Entry("Microsoft.Windows.DevHome_8wekyb3d8bbwe", "Dev Home", "Developer dashboard (now Windows Advanced Settings)",
          "9N8MHTPHNGVV", MS_EXTRAS),
    Entry("Microsoft.Copilot_8wekyb3d8bbwe", "Copilot", "Microsoft's AI chat app", "9NHT9RB2F4HD", MS_EXTRAS),
    Entry("Microsoft.MicrosoftOfficeHub_8wekyb3d8bbwe", "Microsoft 365 Copilot", "Office launcher and sign-up app",
          "9WZDNCRD29V9", MS_EXTRAS),
    Entry("Microsoft.YourPhone_8wekyb3d8bbwe", "Phone Link", "Texts, calls and photos from your phone", "9NMPJ99VJBWV",
          MS_EXTRAS),
    Entry("Microsoft.ZuneVideo_8wekyb3d8bbwe", "Films & TV", "Old video player and film store", "9WZDNCRFJ3P2", MS_EXTRAS),
    Entry("Microsoft.SkypeApp_kzf8qxf38zg5c", "Skype", "Retired calling app (Microsoft closed Skype)", "9WZDNCRFJ364",
          MS_EXTRAS),
    Entry("Microsoft.549981C3F5F10_8wekyb3d8bbwe", "Cortana", "Retired voice assistant", "9NFFX4SZZ23L", MS_EXTRAS),
    Entry("Microsoft.Office.OneNote_8wekyb3d8bbwe", "OneNote for Windows 10", "Retired OneNote app (not the Office one)",
          "9WZDNCRFHVJL", MS_EXTRAS),
    Entry("Microsoft.MixedReality.Portal_8wekyb3d8bbwe", "Mixed Reality Portal", "Windows Mixed Reality headset setup",
          "9NG1H8B3ZC7M", MS_EXTRAS),
    Entry("Microsoft.Microsoft3DViewer_8wekyb3d8bbwe", "3D Viewer", "Viewer for 3D model files", "9NBLGGH42THS", MS_EXTRAS),
    Entry("Microsoft.MicrosoftSolitaireCollection_8wekyb3d8bbwe", "Microsoft Solitaire Collection",
          "Card games with ads", "9WZDNCRFHWD2", GAMES),
    Entry("Microsoft.MicrosoftJigsaw_8wekyb3d8bbwe", "Microsoft Jigsaw", "Jigsaw puzzles", "9WZDNCRFJ9X2", GAMES),
    Entry("king.com.CandyCrushSaga_kgqvnymyfvs32", "Candy Crush Saga", "Promoted match-three game", "9NBLGGH18846", GAMES),
    Entry("king.com.CandyCrushSodaSaga_kgqvnymyfvs32", "Candy Crush Soda Saga", "Promoted match-three game",
          "9NBLGGH1ZRPV", GAMES),
    Entry("7EE7776C.LinkedInforWindows_w1wdnht996qgy", "LinkedIn", "LinkedIn app", "9WZDNCRFJ4Q7", PROMOTED),
    Entry("SpotifyAB.SpotifyMusic_zpdnekdrzrea0", "Spotify", "Music streaming", "9NCBCSZSJRSB", PROMOTED),
    Entry("Disney.37853FC22B2CE_6rarf9sa4v8jt", "Disney+", "Video streaming", "9NXQXXLFST89", PROMOTED),
    Entry("BytedancePte.Ltd.TikTok_6yccndn6064se", "TikTok", "Short video app", "9NH2GPH4JZS4", PROMOTED),
    Entry("Facebook.InstagramBeta_8xx8rvfyw5nnt", "Instagram", "Instagram app", "9NBLGGH5L9XT", PROMOTED),
    Entry("Facebook.Facebook_8xx8rvfyw5nnt", "Facebook", "Facebook app", "9WZDNCRFJ2WL", PROMOTED),
    Entry("FACEBOOK.317180B0BB486_8xx8rvfyw5nnt", "Messenger", "Facebook Messenger", "9WZDNCRF0083", PROMOTED),
    Entry("4DF9E0F8.Netflix_mcm4njqhnhss8", "Netflix", "Video streaming", "9WZDNCRFJ3TJ", PROMOTED),
    Entry("AmazonVideo.PrimeVideo_pwbj9vvecjh7j", "Prime Video", "Video streaming", "9P6RC76MSMMJ", PROMOTED),
)

# never offered, whatever the table says: Windows itself, the Store and its plumbing, frameworks, codecs, Xbox sign-in
PROTECTED_PREFIXES = (
    "Microsoft.WindowsStore", "Microsoft.StorePurchaseApp", "Microsoft.DesktopAppInstaller", "Microsoft.Winget.",
    "Microsoft.SecHealthUI", "Microsoft.WindowsTerminal", "Microsoft.WindowsNotepad", "Microsoft.WindowsCalculator",
    "Microsoft.Windows.Photos", "Microsoft.Paint", "Microsoft.ScreenSketch", "Microsoft.XboxIdentityProvider",
    "Microsoft.GamingServices", "Microsoft.Xbox.TCUI", "Microsoft.MicrosoftEdge", "Microsoft.Edge",
    "MicrosoftWindows.Client.", "Microsoft.Windows.", "Microsoft.VCLibs", "Microsoft.UI.Xaml", "Microsoft.NET.",
    "Microsoft.WindowsAppRuntime", "MicrosoftCorporationII.WinAppRuntime", "Microsoft.Services.Store",
    "Microsoft.AAD.", "Microsoft.AccountsControl", "Microsoft.LockApp", "Microsoft.ECApp", "Microsoft.WebExperience",
    "Microsoft.HEIFImageExtension", "Microsoft.HEVCVideoExtension", "Microsoft.VP9VideoExtensions",
    "Microsoft.WebMediaExtensions", "Microsoft.WebpImageExtension", "Microsoft.RawImageExtension",
    "Microsoft.AV1VideoExtension", "Microsoft.MPEG2VideoExtension", "Microsoft.LanguageExperiencePack",
    "windows.immersivecontrolpanel", "Windows.",
)
SYSTEM_PUBLISHER = "cw5n1h2txyewy"     # Windows' own inbox components
_ALLOWED_WINDOWS_PREFIX = {"microsoft.windows.devhome_8wekyb3d8bbwe"}   # an optional Store app under Microsoft.Windows.*

_LOCAL_ERRORS = {
    "0x80073CFA": "Windows won't let this app be removed",
    "0x80070032": "Windows marks this app as part of the system",
}


def protected(family: str) -> bool:
    f = family.lower()
    if f in _ALLOWED_WINDOWS_PREFIX:
        return False
    return f.endswith("_" + SYSTEM_PUBLISHER) or any(f.startswith(p.lower()) for p in PROTECTED_PREFIXES)


def preset(family: str) -> Entry | None:
    f = family.lower()
    return next((e for e in PRESETS if e.family.lower() == f), None)


def _installed_main(installed: list[winapps.Installed], family: str) -> list[winapps.Installed]:
    f = family.lower()
    return [p for p in installed if p.family.lower() == f and not p.is_bundle and not p.is_framework and not p.is_resource]


def installed_clutter(installed: list[winapps.Installed]) -> list[Entry]:
    """Presets present for this user, in table order."""
    fams = {p.family.lower() for p in installed if not p.is_framework and not p.is_resource}
    return [e for e in PRESETS if e.family.lower() in fams and not protected(e.family)]


def _explain(err: str) -> str:
    for code, text in _LOCAL_ERRORS.items():
        if code.lower() in err.lower():
            return f"{text} ({code})"
    return winapps.explain(err)


def remove(entry: Entry, installed: list[winapps.Installed] | None = None) -> tuple[bool, str]:
    """Remove a preset app for this user (no admin) and remember it for 'Put back'."""
    known = preset(entry.family)
    if known is None or known != entry:
        return False, "not one of Storely's removable presets"
    if not winapps.FAMILY_RE.match(entry.family) or protected(entry.family):
        return False, f"{entry.title} is part of Windows and is not removed"
    pkgs = _installed_main(installed if installed is not None else winapps.installed(), entry.family)
    if not pkgs:
        return True, f"{entry.title} is not installed"
    if any(not p.removable for p in pkgs):
        return False, f"Windows marks {entry.title} as not removable"
    newest = max(pkgs, key=lambda p: p.vt)
    errors = []
    for p in pkgs:
        ok, err = winapps.uninstall(p)
        if not ok:
            errors.append(_explain(err))
    if errors:
        return False, errors[0]
    _record(entry, newest.version)
    return True, f"Removed {entry.title}"


# ----------------------------------------------------------------------------- 'Put back' record

def _load() -> dict:
    try:
        data = json.loads(REMOVED_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    tmp = REMOVED_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, REMOVED_FILE)


def _record(entry: Entry, version: str) -> None:
    data = _load()
    data[entry.family] = {"family": entry.family, "title": entry.title, "product_id": entry.product_id,
                          "group": entry.group, "version": version, "t": time.time()}
    _save(data)


def removed() -> list[dict]:
    """What Storely removed, newest first: [{family, title, product_id, group, version, t}]."""
    return sorted((v for v in _load().values() if isinstance(v, dict) and v.get("product_id")),
                  key=lambda d: d.get("t", 0), reverse=True)


def forget(family: str) -> None:
    """Drop a family from the 'Put back' list (after it was reinstalled, or the user dismissed it)."""
    data = _load()
    key = next((k for k in data if k.lower() == family.lower()), None)
    if key is not None:
        del data[key]
        _save(data)
