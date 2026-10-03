"""Microsoft Store catalog: product details, lookup by package family, search."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field

import requests

from . import CACHE_DIR, __version__

DISPLAYCATALOG = "https://displaycatalog.mp.microsoft.com/v7.0"
STOREEDGE = "https://storeedgefd.dsx.mp.microsoft.com/v9.0"
CACHE_FILE = CACHE_DIR / "catalog.json"
CACHE_TTL = 6 * 3600

_session = requests.Session()
_session.headers["User-Agent"] = f"Unjammed/{__version__}"


@dataclass
class Product:
    product_id: str
    title: str
    publisher: str
    wu_category: str | None
    pfn: str | None
    icon_url: str | None
    tile_color: str | None
    description: str = ""
    short_description: str = ""
    rating: float | None = None
    rating_count: int = 0
    price: float = 0.0
    currency: str = ""
    category: str = ""
    size: int = 0
    screenshots: list[str] = field(default_factory=list)
    hero_url: str | None = None
    is_framework: bool = False
    platforms: dict = field(default_factory=dict)   # package identity -> [(platform, min_version_ulong)]

    @property
    def is_free(self) -> bool:
        return not self.price


def _img(url: str | None) -> str | None:
    if not url:
        return None
    return "https:" + url if url.startswith("//") else url


def _parse(p: dict) -> Product:
    lp = (p.get("LocalizedProperties") or [{}])[0]
    images = lp.get("Images") or []

    def pick(purpose, prefer=150):
        cands = [i for i in images if i.get("ImagePurpose") == purpose]
        if not cands:
            return None
        cands.sort(key=lambda i: abs((i.get("Width") or 0) - prefer))
        return cands[0]

    icon = pick("Tile", 150) or pick("Logo", 100) or pick("BoxArt", 300)
    hero = pick("SuperHeroArt", 1920) or pick("Hero", 1920) or pick("TitledHeroArt", 1920)
    shots = [_img(i.get("Uri")) for i in images if i.get("ImagePurpose") == "Screenshot"][:8]
    sku = (p.get("DisplaySkuAvailabilities") or [{}])[0]
    props = (sku.get("Sku") or {}).get("Properties") or {}
    fd = props.get("FulfillmentData") or {}
    if isinstance(fd, str):
        try:
            fd = json.loads(fd)
        except ValueError:
            fd = {}
    price = {}
    for av in sku.get("Availabilities") or []:
        price = (av.get("OrderManagementData") or {}).get("Price") or price
        if price:
            break
    usage = ((p.get("MarketProperties") or [{}])[0].get("UsageData") or [])
    usage = next((u for u in usage if u.get("AggregateTimeSpan") == "AllTime"), usage[0] if usage else {})
    pkgs = props.get("Packages") or []
    size = max((x.get("MaxDownloadSizeInBytes") or 0 for x in pkgs), default=0)
    pfn = fd.get("PackageFamilyName") or next(
        (a.get("Value") for a in p.get("AlternateIds") or [] if a.get("IdType") == "PackageFamilyName"), None)
    cats = (p.get("Properties") or {}).get("Categories") or []
    return Product(
        product_id=p.get("ProductId", ""),
        title=lp.get("ProductTitle") or p.get("ProductId", ""),
        publisher=lp.get("PublisherName") or "",
        wu_category=fd.get("WuCategoryId"),
        pfn=pfn,
        icon_url=_img(icon.get("Uri")) if icon else None,
        tile_color=(icon or {}).get("BackgroundColor") or None,
        description=lp.get("ProductDescription") or "",
        short_description=lp.get("ShortDescription") or "",
        rating=usage.get("AverageRating"),
        rating_count=int(usage.get("RatingCount") or 0),
        price=float(price.get("ListPrice") or 0),
        currency=price.get("CurrencyCode") or "",
        category=cats[0] if cats else ((p.get("Properties") or {}).get("Category") or ""),
        size=size,
        screenshots=[s for s in shots if s],
        hero_url=_img(hero.get("Uri")) if hero else None,
        is_framework=(p.get("ProductKind") or "").lower() == "framework",
        platforms={x.get("PackageFullName", ""): [(d.get("PlatformName", ""), int(d.get("MinVersion") or 0))
                                                   for d in x.get("PlatformDependencies") or []] for x in pkgs},
    )


class Catalog:
    def __init__(self, market: str = "GB", language: str = "en-GB"):
        self.market = market
        self.language = language
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}
        try:
            self._cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    def _q(self) -> str:
        return f"market={self.market}&languages={self.language},en,neutral"

    def _cached(self, key: str):
        e = self._cache.get(key)
        if e and time.time() - e["t"] < CACHE_TTL:
            return e["v"]
        return None

    def _store(self, key: str, value) -> None:
        with self._lock:
            self._cache[key] = {"t": time.time(), "v": value}

    def save(self) -> None:
        with self._lock:
            tmp = CACHE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache), encoding="utf-8")
            tmp.replace(CACHE_FILE)

    def product(self, product_id: str, fresh: bool = False) -> Product:
        key = f"p:{product_id}"
        raw = None if fresh else self._cached(key)
        if raw is None:
            r = _session.get(f"{DISPLAYCATALOG}/products/{product_id}?{self._q()}&fieldsTemplate=details", timeout=30)
            r.raise_for_status()
            raw = r.json()["Product"]
            self._store(key, raw)
        return _parse(raw)

    def by_family(self, pfn: str) -> Product | None:
        """Product for an installed package family; None if it is not a Store product."""
        key = f"f:{pfn}"
        raw = self._cached(key)
        if raw is None:
            r = _session.get(f"{DISPLAYCATALOG}/products/lookup?alternateId=PackageFamilyName&value={pfn}"
                             f"&{self._q()}&fieldsTemplate=details", timeout=30)
            if r.status_code == 404:
                self._store(key, {})
                return None
            r.raise_for_status()
            d = r.json()
            prods = d.get("Products") or ([d["Product"]] if d.get("Product") else [])
            raw = prods[0] if prods else {}
            self._store(key, raw)
            if raw:
                self._store(f"p:{raw['ProductId']}", raw)
        return _parse(raw) if raw else None

    def search(self, query: str) -> list[dict]:
        """Quick search -> [{product_id, title, icon_url, tile_color, kind}]."""
        r = _session.get(f"{DISPLAYCATALOG}/productFamilies/autosuggest?market={self.market}&languages={self.language}"
                         f"&query={requests.utils.quote(query)}&productFamilyNames=apps,games", timeout=30)
        r.raise_for_status()
        out = []
        for fam in r.json().get("Results") or []:
            for p in fam.get("Products") or []:
                out.append({"product_id": p.get("ProductId"), "title": p.get("Title"),
                            "icon_url": _img(p.get("Icon")), "tile_color": p.get("BackgroundColor"),
                            "kind": fam.get("ProductFamilyName")})
        return out
