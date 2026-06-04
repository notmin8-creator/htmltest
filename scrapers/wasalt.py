"""
Wasalt.com scraper — direct REST API calls + __NEXT_DATA__ fallback.
Wasalt has a public API used by their mobile app.
"""

import re
import json
import logging
import requests
from .base import BaseScraper

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*;q=0.8",
    "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8",
    "Origin": "https://wasalt.com",
    "Referer": "https://wasalt.com/",
}

BASE     = "https://wasalt.com"
API_BASE = "https://api.wasalt.com"

API_ENDPOINTS = [
    f"{API_BASE}/v1/listings",
    f"{API_BASE}/v2/listings",
    f"{API_BASE}/api/v1/properties/search",
    f"{API_BASE}/v1/properties",
    f"{BASE}/api/listings",
]

AREA_MAP = {
    "malaz":        {"en": "malaz",        "ar": "الملز"},
    "rabwah":       {"en": "rabwah",       "ar": "الربوة"},
    "sulaimaniyah": {"en": "sulaimaniyah", "ar": "السليمانية"},
}


class WasaltScraper(BaseScraper):
    SOURCE_NAME = "Wasalt.com"
    BASE_URL = BASE

    def scrape(self):
        logger.info("[Wasalt] Starting scrape via direct API…")
        for area_key, area_info in AREA_MAP.items():
            fetched = self._try_api(area_key, area_info)
            if not fetched:
                self._try_page(area_key, area_info)
            self._delay()
        logger.info(f"[Wasalt] Done — {len(self.listings)} listings.")
        return self.listings

    def _try_api(self, area_key, area_info):
        param_variants = [
            {
                "city": "riyadh", "district": area_info["en"],
                "type": "studio", "purpose": "rent",
                "price_min": self.config["min_price"],
                "price_max": self.config["max_price"],
                "per_page": 50,
            },
            {
                "city": "riyadh", "neighborhood": area_info["en"],
                "property_type": "studio", "listing_type": "rent",
                "min_price": self.config["min_price"],
                "max_price": self.config["max_price"],
            },
            {
                "location": area_info["en"], "city": "riyadh",
                "bedrooms": 0, "purpose": "rent",
                "price_from": self.config["min_price"],
                "price_to": self.config["max_price"],
            },
        ]
        for endpoint in API_ENDPOINTS:
            for params in param_variants:
                try:
                    resp = requests.get(
                        endpoint, params=params, headers=HEADERS, timeout=15
                    )
                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                        except Exception:
                            continue
                        items = (
                            data.get("listings") or data.get("data")
                            or data.get("properties") or data.get("results")
                            or (data if isinstance(data, list) else None)
                        )
                        if items:
                            for item in items:
                                self._parse_item(item, area_key)
                            return True
                except Exception as exc:
                    logger.debug(f"[Wasalt] API error: {exc}")
        return False

    def _try_page(self, area_key, area_info):
        urls = [
            f"{BASE}/en/riyadh/{area_info['en']}/rent/studio",
            f"{BASE}/en/riyadh/{area_info['en']}/for-rent/studio",
        ]
        for url in urls:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=20)
                if resp.status_code != 200:
                    continue
                m = re.search(
                    r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
                    resp.text, re.S
                )
                if m:
                    try:
                        data  = json.loads(m.group(1))
                        items = (
                            data.get("props", {}).get("pageProps", {}).get("listings", [])
                            or data.get("props", {}).get("pageProps", {}).get("properties", [])
                        )
                        for item in items:
                            self._parse_item(item, area_key)
                        if items:
                            return
                    except Exception:
                        pass
            except Exception as exc:
                logger.debug(f"[Wasalt] Page error: {exc}")

    def _parse_item(self, item, area_key):
        try:
            price = self.extract_price(
                item.get("price") or item.get("annual_rent")
                or item.get("rent") or item.get("yearly_price") or 0
            )
            if not self.in_price_range(price):
                return

            prop_id  = item.get("id") or item.get("property_id") or ""
            slug     = item.get("slug") or ""
            link     = (
                item.get("url") or item.get("link")
                or f"{BASE}/en/property/{slug or prop_id}"
            )
            if not link.startswith("http"):
                link = f"{BASE}{link}"

            is_furn   = item.get("is_furnished") or item.get("furnished")
            furnished = (
                "Furnished"   if is_furn is True
                else ("Unfurnished" if is_furn is False else "Not specified")
            )
            title     = item.get("title") or item.get("name") or "N/A"
            text_blob = f"{title} {item.get('description', '')}"

            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME, area=area_key, title=title, price=price,
                link=link,
                phone=str(item.get("phone") or item.get("mobile") or "N/A"),
                furnished=furnished,
                property_type=self.detect_property_type(text_blob),
                bedrooms=item.get("bedrooms") or item.get("beds") or "Studio",
                bathrooms=item.get("bathrooms") or "N/A",
                size_sqm=item.get("area") or item.get("size_sqm") or "N/A",
                description=str(item.get("description", ""))[:200],
            ))
        except Exception as exc:
            logger.debug(f"[Wasalt] Parse error: {exc}")
