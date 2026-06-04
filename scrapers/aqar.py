"""
Aqar.fm scraper — tries multiple REST API endpoints directly,
then falls back to fetching the page and extracting __NEXT_DATA__.
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
    "Accept": "application/json, text/html, */*;q=0.8",
    "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8",
    "Referer": "https://sa.aqar.fm/",
}

BASE = "https://sa.aqar.fm"

# Candidate REST API endpoints
API_ENDPOINTS = [
    f"{BASE}/api/v1/properties",
    f"{BASE}/api/v1/listings",
    f"{BASE}/api/v2/properties",
    f"{BASE}/api/properties",
    f"{BASE}/properties",
]

AREA_MAP = {
    "malaz":        {"ar": "الملز",      "slug": "al-malaz",        "id": None},
    "rabwah":       {"ar": "الربوة",     "slug": "ar-rabwah",       "id": None},
    "sulaimaniyah": {"ar": "السليمانية", "slug": "as-sulaimaniyah", "id": None},
}


class AqarScraper(BaseScraper):
    SOURCE_NAME = "Aqar.fm"
    BASE_URL = BASE

    def scrape(self):
        logger.info("[Aqar] Starting scrape via direct API…")
        for area_key, area_info in AREA_MAP.items():
            fetched = self._try_api(area_key, area_info)
            if not fetched:
                self._try_page(area_key, area_info)
            self._delay()
        logger.info(f"[Aqar] Done — {len(self.listings)} listings.")
        return self.listings

    # ------------------------------------------------------------------ #
    # API approach
    # ------------------------------------------------------------------ #

    def _try_api(self, area_key, area_info):
        param_variants = [
            {
                "city": "الرياض", "district": area_info["ar"],
                "category": "studio", "purpose": "rent",
                "price_min": self.config["min_price"],
                "price_max": self.config["max_price"],
            },
            {
                "city": "riyadh", "district": area_info["slug"],
                "type": "studio", "purpose": "rent",
                "min_price": self.config["min_price"],
                "max_price": self.config["max_price"],
            },
            {
                "city_id": 1, "purpose": "rent", "category": 7,  # 7 = studio
                "price_from": self.config["min_price"],
                "price_to": self.config["max_price"],
                "neighborhood": area_info["ar"],
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
                            data.get("data") or data.get("listings")
                            or data.get("properties") or data.get("items")
                            or (data if isinstance(data, list) else None)
                        )
                        if items:
                            for item in items:
                                self._parse_item(item, area_key)
                            return True
                except Exception as exc:
                    logger.debug(f"[Aqar] API error {endpoint}: {exc}")
        return False

    # ------------------------------------------------------------------ #
    # Page / __NEXT_DATA__ fallback
    # ------------------------------------------------------------------ #

    def _try_page(self, area_key, area_info):
        urls = [
            f"{BASE}/استوديو-للإيجار/الرياض/{area_info['ar']}",
            f"{BASE}/studio-for-rent/riyadh/{area_info['slug']}",
        ]
        for url in urls:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=20)
                if resp.status_code != 200:
                    continue

                # Try __NEXT_DATA__
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
                            or data.get("props", {}).get("pageProps", {}).get("data", [])
                        )
                        if items:
                            for item in items:
                                self._parse_item(item, area_key)
                            return
                    except Exception:
                        pass

                # Try window.__INITIAL_STATE__
                m2 = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.+?});\s*</script>', resp.text, re.S)
                if m2:
                    try:
                        data  = json.loads(m2.group(1))
                        items = data.get("listings", data.get("properties", []))
                        for item in items:
                            self._parse_item(item, area_key)
                        return
                    except Exception:
                        pass

            except Exception as exc:
                logger.debug(f"[Aqar] Page error {url}: {exc}")

    def _parse_item(self, item, area_key):
        try:
            price = self.extract_price(
                item.get("price") or item.get("annual_price") or item.get("rent") or 0
            )
            if not self.in_price_range(price):
                return

            prop_id  = item.get("id") or ""
            slug     = item.get("slug") or item.get("url_slug") or ""
            link     = (
                item.get("url") or item.get("link")
                or (f"{BASE}/property/{slug}" if slug else f"{BASE}/property/{prop_id}")
            )
            is_furn  = item.get("furnished") or item.get("is_furnished")
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
                bathrooms=item.get("bathrooms") or item.get("baths") or "N/A",
                size_sqm=item.get("area") or item.get("size") or "N/A",
                description=str(item.get("description", ""))[:200],
            ))
        except Exception as exc:
            logger.debug(f"[Aqar] Parse error: {exc}")
