"""
PropertyFinder.sa scraper — direct REST API + __NEXT_DATA__ fallback.
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
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.propertyfinder.sa/",
}

BASE = "https://www.propertyfinder.sa"

AREA_SLUGS = {
    "malaz":        "al-malaz",
    "rabwah":       "ar-rabwah",
    "sulaimaniyah": "as-sulaimaniyah",
}


class PropertyFinderScraper(BaseScraper):
    SOURCE_NAME = "PropertyFinder.sa"
    BASE_URL = BASE

    def scrape(self):
        logger.info("[PropertyFinder] Starting scrape via API…")
        for area_key, slug in AREA_SLUGS.items():
            self._try_api(area_key, slug)
            self._try_page(area_key, slug)
            self._delay()
        logger.info(f"[PropertyFinder] Done — {len(self.listings)} listings.")
        return self.listings

    def _try_api(self, area_key, slug):
        """Try PropertyFinder's internal search API."""
        endpoints = [
            f"{BASE}/en/search/api",
            f"{BASE}/api/search",
            f"{BASE}/en/api/properties",
        ]
        params = {
            "c": 2,  # for-rent
            "fu": 0,
            "ob": "mr",
            "q[city_level_1][]": slug,
            "q[price][max]": self.config["max_price"],
            "q[price][min]": self.config["min_price"],
            "q[rooms][]": "ST",  # Studio
            "page": 1,
        }
        for endpoint in endpoints:
            try:
                resp = requests.get(endpoint, params=params, headers=HEADERS, timeout=15)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        continue
                    items = (
                        data.get("properties") or data.get("listings")
                        or data.get("data", {}).get("properties", [])
                        or (data if isinstance(data, list) else None)
                    )
                    if items:
                        for item in items:
                            self._parse_item(item, area_key)
                        return True
            except Exception as exc:
                logger.debug(f"[PF] API error: {exc}")
        return False

    def _try_page(self, area_key, slug):
        """Fetch the listing page and extract __NEXT_DATA__ or JSON-LD."""
        url = (
            f"{BASE}/en/search?"
            f"c=2&fu=0&ob=mr"
            f"&q[city_level_1][]={slug}"
            f"&q[price][max]={self.config['max_price']}"
            f"&q[price][min]={self.config['min_price']}"
            f"&q[rooms][]=ST"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                return

            # __NEXT_DATA__
            m = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
                resp.text, re.S
            )
            if m:
                try:
                    data  = json.loads(m.group(1))
                    items = (
                        data.get("props", {}).get("pageProps", {})
                           .get("searchResults", {}).get("properties", [])
                        or data.get("props", {}).get("pageProps", {}).get("listings", [])
                    )
                    for item in items:
                        self._parse_item(item, area_key)
                    return
                except Exception:
                    pass

            # JSON-LD
            for script in re.finditer(
                r'<script type="application/ld\+json">(.+?)</script>', resp.text, re.S
            ):
                try:
                    data = json.loads(script.group(1))
                    if isinstance(data, list):
                        for d in data:
                            self._parse_jsonld(d, area_key)
                    else:
                        self._parse_jsonld(data, area_key)
                except Exception:
                    pass

        except Exception as exc:
            logger.debug(f"[PF] Page error: {exc}")

    def _parse_jsonld(self, data, area_key):
        try:
            dtype = data.get("@type", "")
            if dtype not in ("Apartment", "Residence", "Product"):
                return
            price = self.extract_price(
                data.get("offers", {}).get("price", 0)
            )
            if not self.in_price_range(price):
                return
            url  = data.get("url", data.get("@id", "N/A"))
            name = data.get("name", "N/A")
            text_blob = f"{name} {data.get('description', '')}"
            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME, area=area_key, title=name, price=price,
                link=url if url.startswith("http") else f"{BASE}{url}",
                furnished=self.detect_furnished(text_blob),
                property_type=self.detect_property_type(text_blob),
                description=text_blob[:200],
            ))
        except Exception:
            pass

    def _parse_item(self, item, area_key):
        try:
            price = self.extract_price(
                item.get("price") or item.get("yearly_price") or item.get("rent_price") or 0
            )
            if not self.in_price_range(price):
                return

            prop_id = item.get("id") or item.get("externalID") or ""
            slug    = item.get("slug") or item.get("url_path") or ""
            link    = (
                item.get("url") or item.get("link")
                or (f"{BASE}/en/property-for-rent/{slug}" if slug
                    else f"{BASE}/en/property/{prop_id}")
            )
            if not link.startswith("http"):
                link = f"{BASE}{link}"

            furn      = str(item.get("furnishing", "")).lower()
            furnished = (
                "Furnished"   if furn in ("furnished", "f")
                else ("Unfurnished" if furn in ("unfurnished", "u")
                      else "Not specified")
            )
            rooms = item.get("rooms") or item.get("bedrooms") or 0
            beds  = "Studio" if str(rooms).upper() in ("0", "ST", "STUDIO", "") else str(rooms)
            title = item.get("title") or item.get("name") or "N/A"
            text_blob = f"{title} {item.get('description', '')}"

            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME, area=area_key, title=title, price=price,
                link=link,
                phone=self.extract_phone(str(item.get("phone", ""))),
                furnished=furnished,
                property_type=self.detect_property_type(text_blob),
                bedrooms=beds,
                bathrooms=item.get("bathrooms") or "N/A",
                size_sqm=item.get("area") or item.get("size") or "N/A",
                description=str(item.get("description", ""))[:200],
            ))
        except Exception as exc:
            logger.debug(f"[PF] Parse error: {exc}")
