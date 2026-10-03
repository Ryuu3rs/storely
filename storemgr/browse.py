"""Browsing the Microsoft Store: charts, categories, full search, app pages, reviews, desktop-installer manifests."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

import requests

from . import __version__

EDGE = "https://storeedgefd.dsx.mp.microsoft.com/v9.0"
_s = requests.Session()
_s.headers["User-Agent"] = f"Unjammed/{__version__}"
_cache: dict[str, tuple[float, object]] = {}
TTL = 30 * 60

CHARTS = {  # key -> (collection, media type, title)
    "top_free_apps": ("TopFree", "apps", "Top free apps"),
    "top_free_games": ("TopFree", "games", "Top free games"),
    "trending_apps": ("TopGrossing", "apps", "Trending apps"),
    "best_games": ("Bestselling", "games", "Best-selling games"),
    "top_paid_apps": ("TopPaid", "apps", "Top paid apps"),
}
CATEGORIES = ["Productivity", "Social", "Photo & video", "Music", "Entertainment", "Utilities & tools", "Business",
              "Education", "Developer tools", "Health & fitness", "Lifestyle", "News & weather", "Personal finance",
              "Security", "Books & reference", "Navigation & maps", "Multimedia design", "Personalization",
              "Food & dining", "Kids & family", "Shopping", "Sports", "Travel"]


@dataclass
class Card:
    product_id: str
    title: str
    publisher: str = ""
    icon_url: str | None = None
    tile_color: str | None = None
    price_text: str = ""
    price: float = 0.0
    rating: float | None = None
    rating_count: str = ""          # already formatted by the Store, e.g. "56K"
    categories: list = field(default_factory=list)
    installer: str = ""             # "WindowsUpdate" (MSIX via Microsoft's delivery service) or "WPM" (desktop installer)
    families: list = field(default_factory=list)
    media: str = ""

    @property
    def free(self) -> bool:
        return not self.price


def _url(u):
    if not u:
        return None
    return "https:" + u if u.startswith("//") else u


def _icon(images):
    best = None
    for im in images or []:
        if (im.get("ImageType") or "").lower() in ("logo", "tile", "boxart", "poster"):
            w = im.get("Width") or 0
            if best is None or abs(w - 150) < abs((best.get("Width") or 0) - 150):
                best = im
    return best


def _card(c: dict) -> Card:
    im = _icon(c.get("Images"))
    return Card(product_id=c.get("ProductId", ""), title=c.get("Title", ""), publisher=c.get("PublisherName") or "",
                icon_url=_url((im or {}).get("Url")), tile_color=(im or {}).get("BackgroundColor"),
                price_text=c.get("DisplayPrice") or "", price=float(c.get("Price") or 0),
                rating=c.get("AverageRating"), rating_count=str(c.get("RatingsCount") or c.get("RatingCount") or ""),
                categories=c.get("Categories") or [], installer=(c.get("Installer") or {}).get("Type") or "",
                families=c.get("PackageFamilyNames") or [], media=c.get("TypeTag") or c.get("MediaType") or "")


class Browse:
    def __init__(self, market: str = "GB", locale: str = "en-GB"):
        self.market, self.locale = market, locale

    def _get(self, path: str, ttl: float = TTL):
        sep = "&" if "?" in path else "?"
        url = f"{EDGE}/{path}{sep}market={self.market}&locale={self.locale}&deviceFamily=Windows.Desktop"
        hit = _cache.get(url)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        r = _s.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        _cache[url] = (time.time(), data)
        return data

    # ------------------------------------------------------------------ charts / categories
    def chart(self, key: str, category: str | None = None, size: int = 24) -> tuple[str, list[Card]]:
        coll, media, title = CHARTS[key]
        q = f"recommendations/collections/{coll}?mediaType={media}&pageSize={size}"
        if category:
            q += f"&category={requests.utils.quote(category)}"
            title = f"{title.replace(' apps', '').replace(' games', '')} in {category}"
        p = self._get(q)["Payload"]
        return title, [_card(c) for c in p.get("Cards") or []]

    # ------------------------------------------------------------------ search
    def search(self, query: str, media: str = "all", price: str = "all", cursor: str | None = None
               ) -> tuple[list[Card], str | None]:
        """One page of results + the cursor for the next page (None when there are no more)."""
        if cursor:   # NextUri already carries market/locale/cursor - fetch it exactly as given
            url = EDGE + "/" + cursor.split("/v9.0/", 1)[-1]
            hit = _cache.get(url)
            if hit and time.time() - hit[0] < TTL:
                data = hit[1]
            else:
                r = _s.get(url, timeout=30)
                r.raise_for_status()
                data = r.json()
                _cache[url] = (time.time(), data)
        else:
            q = f"search?query={requests.utils.quote(query)}&mediaType={media}"
            if price != "all":
                q += f"&priceType={price}"
            data = self._get(q)
        p = data["Payload"]
        cards = [_card(c) for c in (p.get("HighlightedResults") or []) + (p.get("SearchResults") or [])]
        seen, out = set(), []
        for c in cards:
            if c.product_id not in seen:
                seen.add(c.product_id)
                out.append(c)
        if price == "Free":
            out = [c for c in out if c.free]
        elif price == "Paid":
            out = [c for c in out if not c.free]
        return out, p.get("NextUri")

    # ------------------------------------------------------------------ app page
    def _payload(self, product_id: str) -> dict:
        """The Store's product record. pages/pdp covers Store packages; desktop-installer apps ("XP..." ids) are
        only served by products/{id}, which has the same fields."""
        try:
            pages = self._get(f"pages/pdp?productId={product_id}")
            p = next((it.get("Payload") for it in pages if (it.get("Payload") or {}).get("ProductId")), None)
            if p:
                return p
        except requests.HTTPError:
            pass
        return self._get(f"products/{product_id}").get("Payload") or {}

    def as_product(self, product_id: str):
        """A catalogue-style Product for apps Microsoft's catalogue doesn't list (desktop installers)."""
        from .catalog import Product
        p = self._payload(product_id)
        imgs = p.get("Images") or []
        icon = _icon(imgs)
        shots = [_url(i.get("Url")) for i in imgs if (i.get("ImageType") or "").lower() == "screenshot"][:8]
        try:
            rating = float(p.get("AverageRating")) if p.get("AverageRating") else None
        except (TypeError, ValueError):
            rating = None
        return Product(product_id=product_id, title=p.get("Title") or product_id, publisher=p.get("PublisherName") or "",
                       wu_category=None, pfn=None, icon_url=_url((icon or {}).get("Url")),
                       tile_color=(icon or {}).get("BackgroundColor"), description=p.get("Description") or "",
                       short_description=p.get("ShortDescription") or "", rating=rating,
                       rating_count=int(float(p.get("RatingCount") or 0)), price=float(p.get("Price") or 0),
                       currency="", category=(p.get("Categories") or [""])[0], screenshots=[s for s in shots if s])

    def details(self, product_id: str) -> dict:
        """Extra app-page info: requirements, size, updated date, age rating, links, install type."""
        p = self._payload(product_id)
        reqs = []
        for level in ("Minimum", "Recommended"):
            for item in ((p.get("SystemRequirements") or {}).get(level) or {}).get("Items") or []:
                v = item.get("Description") or item.get("Value") or ""
                n = item.get("Name") or item.get("Title") or ""
                if n and v:
                    reqs.append((level, n, v))
        rating_text = ""
        pr = p.get("ProductRatings") or []
        if pr:
            rating_text = pr[0].get("LongName") or pr[0].get("RatingValue") or ""

        def dt(s):
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone() if s else None
            except ValueError:
                return None
        return {
            "updated": dt(p.get("LastUpdateDateUtc")), "released": dt(p.get("ReleaseDateUtc")),
            "size": p.get("ApproximateSizeInBytes") or p.get("MaxInstallSizeInBytes") or 0,
            "requirements": reqs, "age": rating_text,
            "website": p.get("AppWebsiteUrl") or "", "privacy": p.get("PrivacyUrl") or "",
            "support": next((u.get("Url") for u in p.get("SupportUris") or [] if u.get("Url")), ""),
            "installer": (p.get("Installer") or {}).get("Type") or "",
            "compatible": p.get("IsCompatible", True), "category": p.get("CategoryId") or "",
            "description": p.get("Description") or "", "title": p.get("Title") or "",
            "publisher": p.get("PublisherName") or "", "price_text": p.get("DisplayPrice") or "",
            "rating": p.get("AverageRating"), "rating_count": p.get("RatingCount") or 0,
            "permissions": [c.get("Title") or c.get("Name") for c in (p.get("PermissionsRequired") or []) if isinstance(c, dict)],
            "languages": p.get("SupportedLanguages") or [],
        }

    def reviews(self, product_id: str, token: str | None = None) -> tuple[list[dict], str | None]:
        q = f"ratings/product/{product_id}?pageSize=25"
        if token:
            q += f"&continuationToken={requests.utils.quote(token)}"
        p = self._get(q)["Payload"]
        out = []
        for r in p.get("Reviews") or []:
            when = r.get("SubmittedDateTimeUtc") or ""
            out.append({"rating": r.get("Rating") or 0, "title": r.get("Title") or "",
                        "text": r.get("ReviewText") or r.get("Text") or "", "date": when[:10],
                        "helpful": r.get("HelpfulPositive") or 0, "device": r.get("DeviceFamily") or ""})
        return out, p.get("ContinuationToken")

    def manifest(self, product_id: str) -> dict:
        """The Store's install recipe for desktop-installer apps (Discord, Teams...)."""
        return self._get(f"packageManifests/{product_id}", ttl=10 * 60).get("Data") or {}
