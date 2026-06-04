"""Aqar.fm scraper — Playwright + API interception."""

import re
import json
import logging
import time
from bs4 import BeautifulSoup
from .base import BaseScraper
from .pw_browser import fetch

logger = logging.getLogger(__name__)


class AqarScraper(BaseScraper):
    SOURCE_NAME = "Aqar.fm"
    BASE_URL    = "https://sa.aqar.fm"

    AREA_URLS = {
        "malaz":        f"{BASE_URL}/استوديو-للإيجار/الرياض/الملز",
        "rabwah":       f"{BASE_URL}/استوديو-للإيجار/الرياض/الربوة",
        "sulaimaniyah": f"{BASE_URL}/استوديو-للإيجار/الرياض/السليمانية",
    }

    API_PATTERNS = ["aqar.fm/api", "aqar.fm/graphql", "/api/properties", "/api/listings"]

    def scrape(self):
        logger.info("[Aqar] Starting scrape with Playwright…")
        for area_key, url in self.AREA_URLS.items():
            for page_num in range(1, 4):
                page_url = f"{url}?page={page_num}" if page_num > 1 else url
                html, intercepted = fetch(
                    page_url,
                    api_patterns=self.API_PATTERNS,
                    wait_selector="[class*='property'], [class*='listing'], article",
                )
                found = self._process(html, intercepted, area_key)
                if not found:
                    break
                time.sleep(2)
        logger.info(f"[Aqar] Done — {len(self.listings)} listings.")
        return self.listings

    def _process(self, html, intercepted, area_key):
        found = False

        # Try intercepted API data
        for resp in intercepted:
            data  = resp["data"]
            items = (
                data.get("data") or data.get("listings") or
                data.get("properties") or data.get("items") or
                (data if isinstance(data, list) else [])
            )
            for item in (items or []):
                listing = self._parse_api_item(item, area_key)
                if listing:
                    self.listings.append(listing)
                    found = True

        # Try __NEXT_DATA__ embedded JSON
        if not found and html:
            soup = BeautifulSoup(html, "lxml")
            for script in soup.find_all("script", id="__NEXT_DATA__"):
                try:
                    data  = json.loads(script.string or "")
                    items = (
                        data.get("props", {}).get("pageProps", {}).get("listings", [])
                        or data.get("props", {}).get("pageProps", {}).get("properties", [])
                    )
                    for item in items:
                        listing = self._parse_api_item(item, area_key)
                        if listing:
                            self.listings.append(listing)
                            found = True
                except Exception:
                    pass

        # HTML card fallback
        if not found and html:
            soup  = BeautifulSoup(html, "lxml")
            cards = (
                soup.find_all("div", class_=re.compile(r"property|listing|card|item", re.I))
                or soup.find_all("article")
            )
            for card in cards:
                text_blob = card.get_text(" ", strip=True)
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
                found = True

        return found

    def _parse_api_item(self, item, area_key):
        try:
            price = self.extract_price(
                item.get("price") or item.get("annual_price") or item.get("rent") or 0
            )
            if not self.in_price_range(price):
                return None

            prop_id  = item.get("id") or ""
            slug     = item.get("slug") or item.get("url_slug") or ""
            link     = (
                item.get("url") or item.get("link")
                or (f"{self.BASE_URL}/property/{slug}" if slug
                    else f"{self.BASE_URL}/property/{prop_id}")
            )
            is_furn  = item.get("furnished") or item.get("is_furnished")
            furnished = (
                "Furnished"   if is_furn is True
                else ("Unfurnished" if is_furn is False else "Not specified")
            )
            title     = item.get("title") or item.get("name") or "N/A"
            text_blob = f"{title} {item.get('description', '')}"
            phone     = str(item.get("phone") or item.get("mobile") or "N/A")

            return self.make_listing(
                source=self.SOURCE_NAME, area=area_key, title=title, price=price,
                link=link, phone=phone, furnished=furnished,
                property_type=self.detect_property_type(text_blob),
                bedrooms=item.get("bedrooms") or item.get("beds") or "Studio",
                bathrooms=item.get("bathrooms") or item.get("baths") or "N/A",
                size_sqm=item.get("area") or item.get("size") or "N/A",
                description=str(item.get("description", ""))[:200],
            )
        except Exception as exc:
            logger.debug(f"[Aqar] API item error: {exc}")
            return None
