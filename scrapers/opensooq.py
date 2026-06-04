"""
OpenSooq scraper — direct requests + JSON extraction.
"""

import re
import json
import logging
import requests
from urllib.parse import quote
from .base import BaseScraper

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8",
}

BASE = "https://sa.opensooq.com"

AREA_SLUGS = {
    "malaz":        "al-malaz",
    "rabwah":       "al-rabwah",
    "sulaimaniyah": "al-sulaimaniyah",
}


class OpenSooqScraper(BaseScraper):
    SOURCE_NAME = "OpenSooq"
    BASE_URL = BASE

    def scrape(self):
        logger.info("[OpenSooq] Starting scrape…")
        for area_key, slug in AREA_SLUGS.items():
            urls = [
                f"{BASE}/ar/riyadh/{slug}/real-estate-for-rent/rooms-for-rent",
                f"{BASE}/ar/riyadh/{slug}/real-estate-for-rent/apartments-for-rent",
                f"{BASE}/en/riyadh/{slug}/real-estate-for-rent/studio",
            ]
            for url in urls:
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=20)
                    if resp.status_code == 200:
                        self._parse_page(resp.text, area_key)
                except Exception as exc:
                    logger.debug(f"[OpenSooq] Error: {exc}")
                self._delay()
        logger.info(f"[OpenSooq] Done — {len(self.listings)} listings.")
        return self.listings

    def _parse_page(self, html, area_key):
        # Try __NEXT_DATA__
        m = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
            html, re.S
        )
        if m:
            try:
                data  = json.loads(m.group(1))
                items = (
                    data.get("props", {}).get("pageProps", {}).get("listings", [])
                    or data.get("props", {}).get("pageProps", {}).get("posts", [])
                    or data.get("props", {}).get("pageProps", {}).get("items", [])
                )
                for item in items:
                    self._parse_item(item, area_key)
                return
            except Exception:
                pass

        # Try embedded JSON arrays
        for m in re.finditer(r'"(?:listings|posts|items)"\s*:\s*(\[.+?\])', html, re.S):
            try:
                items = json.loads(m.group(1))
                for item in items:
                    self._parse_item(item, area_key)
                return
            except Exception:
                pass

    def _parse_item(self, item, area_key):
        try:
            title     = item.get("title") or item.get("name") or "N/A"
            text_blob = f"{title} {item.get('description', '')}"
            if not any(k in text_blob for k in ["studio", "Studio", "استوديو", "ستوديو"]):
                return
            price = self.extract_price(item.get("price") or text_blob)
            if not self.in_price_range(price):
                return
            post_id = item.get("id") or ""
            link    = item.get("url") or item.get("link") or f"{BASE}/post/{post_id}"
            if not link.startswith("http"):
                link = f"{BASE}{link}"
            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME, area=area_key, title=title, price=price,
                link=link, phone=self.extract_phone(text_blob),
                furnished=self.detect_furnished(text_blob),
                property_type=self.detect_property_type(text_blob),
                description=text_blob[:200],
            ))
        except Exception as exc:
            logger.debug(f"[OpenSooq] item error: {exc}")
