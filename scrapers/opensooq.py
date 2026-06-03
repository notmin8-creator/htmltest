"""Scraper for sa.opensooq.com — Arab-world classifieds."""

import re
import json
import logging
from urllib.parse import quote
from bs4 import BeautifulSoup
from .base import BaseScraper

logger = logging.getLogger(__name__)


class OpenSooqScraper(BaseScraper):
    SOURCE_NAME = "OpenSooq"
    BASE_URL = "https://sa.opensooq.com"

    AREA_SLUGS = {
        "malaz":        "al-malaz",
        "rabwah":       "al-rabwah",
        "sulaimaniyah": "al-sulaimaniyah",
    }

    SEARCH_URLS = [
        "/ar/riyadh/{area}/real-estate-for-rent/rooms-for-rent",
        "/ar/riyadh/{area}/real-estate-for-rent/apartments-for-rent",
        "/ar/riyadh/{area}/real-estate-for-rent/studio",
        "/en/riyadh/{area}/real-estate-for-rent/studio",
    ]

    def scrape(self):
        logger.info("[OpenSooq] Starting scrape…")
        for area_key, area_slug in self.AREA_SLUGS.items():
            self._scrape_area(area_key, area_slug)
            self._delay()

        # Also do keyword searches
        for query in ["استوديو إيجار الرياض", "studio rent riyadh"]:
            url = f"{self.BASE_URL}/ar/search?q={quote(query)}"
            resp = self.get(url)
            if resp and resp.status_code == 200:
                self._parse_page(resp.text, detect_area=True)
            self._delay()

        logger.info(f"[OpenSooq] Done — {len(self.listings)} listings collected.")
        return self.listings

    def _scrape_area(self, area_key, area_slug):
        for tmpl in self.SEARCH_URLS:
            url = self.BASE_URL + tmpl.format(area=area_slug)
            for page in range(1, 4):
                page_url = f"{url}?page={page}"
                resp = self.get(page_url)
                if resp and resp.status_code == 200:
                    found = self._parse_page(resp.text, area_key=area_key)
                    if not found:
                        break
                self._delay()

    def _parse_page(self, html, area_key=None, detect_area=False):
        soup = BeautifulSoup(html, "lxml")
        found_any = False

        # Try embedded JSON
        for script in soup.find_all("script"):
            src = script.string or ""
            if '"listings"' in src or '"posts"' in src:
                try:
                    m = re.search(r'(\{.*"listings".*\})', src, re.S)
                    if m:
                        data  = json.loads(m.group(1))
                        items = data.get("listings") or data.get("posts") or []
                        for item in items:
                            self._parse_json_item(item, area_key)
                            found_any = True
                        return found_any
                except Exception:
                    pass

        # HTML cards
        cards = (
            soup.find_all("li", class_=re.compile(r"item|post|listing|card", re.I))
            or soup.find_all("div", class_=re.compile(r"item|post|listing|card", re.I))
            or soup.find_all("article")
        )
        for card in cards:
            listing = self._parse_card(card, area_key, detect_area)
            if listing:
                self.listings.append(listing)
                found_any = True
        return found_any

    def _parse_json_item(self, item, area_key):
        try:
            title     = item.get("title") or item.get("name") or "N/A"
            text_blob = f"{title} {item.get('description', '')}"

            if not any(k in text_blob.lower() for k in ["studio", "استوديو", "ستوديو"]):
                return

            price = self.extract_price(item.get("price") or text_blob)
            if not self.in_price_range(price):
                return

            area = area_key or self.detect_area(text_blob)
            post_id = item.get("id") or ""
            link    = item.get("url") or item.get("link") or f"{self.BASE_URL}/post/{post_id}"

            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME,
                area=area,
                title=title,
                price=price,
                link=link,
                phone=self.extract_phone(text_blob),
                furnished=self.detect_furnished(text_blob),
                property_type=self.detect_property_type(text_blob),
                description=text_blob[:200],
            ))
        except Exception as exc:
            logger.debug(f"[OpenSooq] JSON item error: {exc}")

    def _parse_card(self, card, area_key, detect_area):
        try:
            text_blob = card.get_text(" ", strip=True)

            if not any(k in text_blob.lower() for k in ["studio", "استوديو", "ستوديو", "غرفة وصالة"]):
                return None

            price = self.extract_price(text_blob)
            if not self.in_price_range(price):
                return None

            area = area_key if area_key else (self.detect_area(text_blob) if detect_area else "Unknown")

            title_tag = card.find(["h2", "h3", "h4", "strong"])
            a_tag     = card.find("a", href=True)
            title = title_tag.get_text(strip=True) if title_tag else text_blob[:80]
            href  = a_tag["href"] if a_tag else "N/A"
            link  = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            return self.make_listing(
                source=self.SOURCE_NAME,
                area=area,
                title=title,
                price=price,
                link=link,
                phone=self.extract_phone(text_blob),
                furnished=self.detect_furnished(text_blob),
                property_type=self.detect_property_type(text_blob),
                description=text_blob[:200],
            )
        except Exception as exc:
            logger.debug(f"[OpenSooq] Card error: {exc}")
            return None
