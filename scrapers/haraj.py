"""
Haraj.com.sa scraper — direct requests + __NEXT_DATA__ extraction.
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

BASE = "https://haraj.com.sa"

SEARCHES = [
    "استوديو للإيجار الملز الرياض",
    "استوديو للإيجار الربوة الرياض",
    "استوديو للإيجار السليمانية الرياض",
    "studio for rent malaz riyadh",
    "studio for rent sulaimaniyah riyadh",
    "studio for rent rabwah riyadh",
]


class HarajScraper(BaseScraper):
    SOURCE_NAME = "Haraj.com.sa"
    BASE_URL = BASE

    def scrape(self):
        logger.info("[Haraj] Starting scrape…")
        for query in SEARCHES:
            url = f"{BASE}/search/{quote(query)}"
            try:
                resp = requests.get(url, headers=HEADERS, timeout=20)
                if resp.status_code == 200:
                    self._parse_page(resp.text)
            except Exception as exc:
                logger.debug(f"[Haraj] Error: {exc}")
            self._delay()
        logger.info(f"[Haraj] Done — {len(self.listings)} listings.")
        return self.listings

    def _parse_page(self, html):
        # Try __NEXT_DATA__
        m = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
            html, re.S
        )
        if m:
            try:
                data  = json.loads(m.group(1))
                posts = (
                    data.get("props", {}).get("pageProps", {}).get("posts", [])
                    or data.get("props", {}).get("pageProps", {}).get("listings", [])
                    or data.get("props", {}).get("pageProps", {}).get("items", [])
                )
                for p in posts:
                    self._parse_post(p)
                if posts:
                    return
            except Exception:
                pass

        # JSON arrays embedded in script tags
        for m in re.finditer(r'"posts"\s*:\s*(\[.+?\])', html, re.S):
            try:
                posts = json.loads(m.group(1))
                for p in posts:
                    self._parse_post(p)
                return
            except Exception:
                pass

    def _parse_post(self, item):
        try:
            title     = item.get("title") or item.get("subject") or ""
            body      = item.get("body") or item.get("description") or ""
            text_blob = f"{title} {body}"

            if not any(k in text_blob for k in ["studio", "Studio", "استوديو", "ستوديو"]):
                return

            area = self.detect_area(text_blob)
            if area == "Unknown":
                return

            price = self.extract_price(item.get("price") or text_blob)
            if not self.in_price_range(price):
                return

            post_id = item.get("id") or item.get("post_id") or ""
            link    = item.get("url") or item.get("link") or f"{BASE}/post/{post_id}"

            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME, area=area,
                title=title or "N/A", price=price, link=link,
                phone=self.extract_phone(text_blob),
                furnished=self.detect_furnished(text_blob),
                property_type=self.detect_property_type(text_blob),
                description=text_blob[:200],
            ))
        except Exception as exc:
            logger.debug(f"[Haraj] Post error: {exc}")
