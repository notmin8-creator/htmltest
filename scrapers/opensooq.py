"""OpenSooq scraper — Playwright + API interception."""

import re
import json
import logging
import time
from urllib.parse import quote
from bs4 import BeautifulSoup
from .base import BaseScraper
from .pw_browser import fetch

logger = logging.getLogger(__name__)


class OpenSooqScraper(BaseScraper):
    SOURCE_NAME = "OpenSooq"
    BASE_URL    = "https://sa.opensooq.com"

    AREA_URLS = {
        "malaz":        f"{BASE_URL}/ar/riyadh/al-malaz/real-estate-for-rent/rooms-for-rent",
        "rabwah":       f"{BASE_URL}/ar/riyadh/al-rabwah/real-estate-for-rent/rooms-for-rent",
        "sulaimaniyah": f"{BASE_URL}/ar/riyadh/al-sulaimaniyah/real-estate-for-rent/rooms-for-rent",
    }

    API_PATTERNS = ["opensooq.com/api", "/api/posts", "/api/listings", "graphql"]

    def scrape(self):
        logger.info("[OpenSooq] Starting scrape with Playwright…")
        for area_key, url in self.AREA_URLS.items():
            html, intercepted = fetch(
                url,
                api_patterns=self.API_PATTERNS,
                wait_selector="[class*='item'], [class*='card'], [class*='listing']",
            )
            self._process(html, intercepted, area_key)
            time.sleep(2)
        logger.info(f"[OpenSooq] Done — {len(self.listings)} listings.")
        return self.listings

    def _process(self, html, intercepted, area_key):
        for resp in intercepted:
            data  = resp["data"]
            items = (
                data.get("listings") or data.get("posts") or
                data.get("data", {}).get("listings", []) or
                (data if isinstance(data, list) else [])
            )
            for item in (items or []):
                self._parse_api_item(item, area_key)

        if not html:
            return
        soup = BeautifulSoup(html, "lxml")

        for script in soup.find_all("script", id="__NEXT_DATA__"):
            try:
                data  = json.loads(script.string or "")
                items = (
                    data.get("props", {}).get("pageProps", {}).get("listings", [])
                    or data.get("props", {}).get("pageProps", {}).get("posts", [])
                )
                for item in items:
                    self._parse_api_item(item, area_key)
                return
            except Exception:
                pass

        cards = (
            soup.find_all("li",  class_=re.compile(r"item|post|listing|card", re.I))
            or soup.find_all("div", class_=re.compile(r"item|post|listing|card", re.I))
            or soup.find_all("article")
        )
        for card in cards:
            text_blob = card.get_text(" ", strip=True)
            if not any(k in text_blob for k in ["studio", "استوديو", "ستوديو", "غرفة وصالة"]):
                continue
            price = self.extract_price(text_blob)
            if not self.in_price_range(price):
                continue
            title_tag = card.find(["h2", "h3", "h4", "strong"])
            a_tag     = card.find("a", href=True)
            title = title_tag.get_text(strip=True) if title_tag else text_blob[:80]
            href  = a_tag["href"] if a_tag else "N/A"
            link  = href if href.startswith("http") else f"{self.BASE_URL}{href}"
            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME, area=area_key, title=title, price=price,
                link=link, phone=self.extract_phone(text_blob),
                furnished=self.detect_furnished(text_blob),
                property_type=self.detect_property_type(text_blob),
                description=text_blob[:200],
            ))

    def _parse_api_item(self, item, area_key):
        try:
            title     = item.get("title") or item.get("name") or "N/A"
            text_blob = f"{title} {item.get('description', '')}"
            if not any(k in text_blob for k in ["studio", "استوديو", "ستوديو"]):
                return
            price = self.extract_price(item.get("price") or text_blob)
            if not self.in_price_range(price):
                return
            post_id = item.get("id") or ""
            link    = item.get("url") or item.get("link") or f"{self.BASE_URL}/post/{post_id}"
            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME, area=area_key, title=title, price=price,
                link=link, phone=self.extract_phone(text_blob),
                furnished=self.detect_furnished(text_blob),
                property_type=self.detect_property_type(text_blob),
                description=text_blob[:200],
            ))
        except Exception as exc:
            logger.debug(f"[OpenSooq] item error: {exc}")
