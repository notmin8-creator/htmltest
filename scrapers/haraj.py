"""Scraper for haraj.com.sa — Saudi classifieds with many rental listings."""

import re
import json
import logging
from urllib.parse import quote
from bs4 import BeautifulSoup
from .base import BaseScraper

logger = logging.getLogger(__name__)


class HarajScraper(BaseScraper):
    SOURCE_NAME = "Haraj.com.sa"
    BASE_URL = "https://haraj.com.sa"

    SEARCH_QUERIES = [
        "استوديو للإيجار الملز الرياض",
        "استوديو للإيجار الربوة الرياض",
        "استوديو للإيجار السليمانية الرياض",
        "studio for rent malaz riyadh",
        "studio for rent rabwah riyadh",
        "studio for rent sulaimaniyah riyadh",
        "غرفة للإيجار السليمانية الرياض",
        "شقة استوديو الرياض للإيجار",
    ]

    CATEGORY_URLS = [
        f"{BASE_URL}/riyadh/rent",
        f"{BASE_URL}/riyadh/apartments-for-rent",
    ]

    def scrape(self):
        logger.info("[Haraj] Starting scrape…")

        for query in self.SEARCH_QUERIES:
            encoded = quote(query)
            url = f"{self.BASE_URL}/search/{encoded}"
            resp = self.get(url)
            if resp and resp.status_code == 200:
                self._parse_search_page(resp.text)
            self._delay()

        # Also scrape category pages
        for cat_url in self.CATEGORY_URLS:
            for page in range(1, 4):
                url = f"{cat_url}?page={page}"
                resp = self.get(url)
                if resp and resp.status_code == 200:
                    self._parse_search_page(resp.text)
                self._delay()

        logger.info(f"[Haraj] Done — {len(self.listings)} listings collected.")
        return self.listings

    def _parse_search_page(self, html):
        soup = BeautifulSoup(html, "lxml")

        # Try embedded JSON
        for script in soup.find_all("script"):
            src = script.string or ""
            if "listings" in src or "posts" in src:
                try:
                    data = json.loads(src)
                    items = (
                        data.get("listings") or data.get("posts")
                        or data.get("data", {}).get("listings", [])
                    )
                    for item in (items or []):
                        self._parse_json_item(item)
                    return
                except Exception:
                    pass

        # HTML card parsing
        selectors = [
            ("div", re.compile(r"post|card|item|listing", re.I)),
            ("article", None),
            ("li", re.compile(r"post|item", re.I)),
        ]
        cards = []
        for tag, cls in selectors:
            found = soup.find_all(tag, class_=cls) if cls else soup.find_all(tag)
            if found:
                cards = found
                break

        for card in cards:
            self._parse_card(card)

    def _parse_json_item(self, item):
        try:
            title     = item.get("title") or item.get("subject") or "N/A"
            text_blob = f"{title} {item.get('body', '')} {item.get('description', '')}"

            # Filter by studio keyword
            if not any(k in text_blob.lower() for k in ["studio", "استوديو", "ستوديو", "غرفة وصالة"]):
                if not any(k in text_blob.lower() for k in ["rent", "للإيجار", "إيجار"]):
                    return

            price = self.extract_price(item.get("price") or text_blob)
            if not self.in_price_range(price):
                return

            area  = self.detect_area(text_blob)
            if area == "Unknown":
                return  # skip listings not in target areas

            post_id = item.get("id") or item.get("post_id") or ""
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
            logger.debug(f"[Haraj] JSON item error: {exc}")

    def _parse_card(self, card):
        try:
            text_blob = card.get_text(" ", strip=True)

            # Must mention studio and be in a target area
            if not any(k in text_blob.lower() for k in ["studio", "استوديو", "ستوديو"]):
                return
            area = self.detect_area(text_blob)
            if area == "Unknown":
                return

            price = self.extract_price(text_blob)
            if not self.in_price_range(price):
                return

            title_tag = card.find(["h2", "h3", "h4", "strong", "a"])
            a_tag     = card.find("a", href=True)
            title = title_tag.get_text(strip=True) if title_tag else text_blob[:80]
            href  = a_tag["href"] if a_tag else "N/A"
            link  = href if href.startswith("http") else f"{self.BASE_URL}{href}"

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
            logger.debug(f"[Haraj] Card parse error: {exc}")
