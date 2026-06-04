"""Haraj.com.sa scraper — Playwright for JS rendering."""

import re
import json
import logging
import time
from urllib.parse import quote
from bs4 import BeautifulSoup
from .base import BaseScraper
from .pw_browser import fetch

logger = logging.getLogger(__name__)


class HarajScraper(BaseScraper):
    SOURCE_NAME = "Haraj.com.sa"
    BASE_URL    = "https://haraj.com.sa"

    SEARCHES = [
        "استوديو للإيجار الملز الرياض",
        "استوديو للإيجار الربوة الرياض",
        "استوديو للإيجار السليمانية الرياض",
        "studio rent malaz riyadh",
        "studio rent sulaimaniyah riyadh",
        "studio rent rabwah riyadh",
    ]

    API_PATTERNS = ["haraj.com.sa/api", "/api/posts", "/api/search", "/graphql"]

    def scrape(self):
        logger.info("[Haraj] Starting scrape with Playwright…")
        for query in self.SEARCHES:
            url = f"{self.BASE_URL}/search/{quote(query)}"
            html, intercepted = fetch(
                url,
                api_patterns=self.API_PATTERNS,
                wait_selector="[class*='post'], [class*='card'], article",
                wait_ms=3000,
            )
            self._process(html, intercepted)
            time.sleep(2)
        logger.info(f"[Haraj] Done — {len(self.listings)} listings.")
        return self.listings

    def _process(self, html, intercepted):
        # Try intercepted API data
        for resp in intercepted:
            data  = resp["data"]
            items = (
                data.get("posts") or data.get("listings") or
                data.get("data", {}).get("posts", []) or
                (data if isinstance(data, list) else [])
            )
            for item in (items or []):
                self._parse_api_item(item)

        # HTML parsing
        if not html:
            return
        soup = BeautifulSoup(html, "lxml")

        # Try __NEXT_DATA__
        for script in soup.find_all("script", id="__NEXT_DATA__"):
            try:
                data  = json.loads(script.string or "")
                posts = (
                    data.get("props", {}).get("pageProps", {}).get("posts", [])
                    or data.get("props", {}).get("pageProps", {}).get("listings", [])
                )
                for p in posts:
                    self._parse_api_item(p)
                return
            except Exception:
                pass

        # Direct card scraping — only pick actual listing cards
        cards = (
            soup.find_all("div", class_=re.compile(r"post-item|card|listing", re.I))
            or soup.find_all("article")
            or soup.find_all("li", class_=re.compile(r"post|item", re.I))
        )

        for card in cards:
            # Skip navigation / search form elements
            if card.find(["form", "input", "select"]):
                continue

            text_blob = card.get_text(" ", strip=True)

            # Must contain studio keyword
            if not any(k in text_blob for k in ["studio", "Studio", "استوديو", "ستوديو"]):
                continue

            # Must be in a target area
            area = self.detect_area(text_blob)
            if area == "Unknown":
                continue

            price = self.extract_price(text_blob)
            if not self.in_price_range(price):
                continue

            title_tag = card.find(["h2", "h3", "h4", "strong"])
            a_tag     = card.find("a", href=True)

            # Skip if the "title" is just a navigation element
            title = title_tag.get_text(strip=True) if title_tag else ""
            if not title or len(title) < 10:
                continue

            href = a_tag["href"] if a_tag else "N/A"
            link = href if href.startswith("http") else f"{self.BASE_URL}{href}"

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

    def _parse_api_item(self, item):
        try:
            title     = item.get("title") or item.get("subject") or ""
            body      = item.get("body") or item.get("description") or ""
            text_blob = f"{title} {body}"

            if not any(k in text_blob for k in ["studio", "استوديو", "ستوديو"]):
                return

            area = self.detect_area(text_blob)
            if area == "Unknown":
                return

            price = self.extract_price(item.get("price") or text_blob)
            if not self.in_price_range(price):
                return

            post_id = item.get("id") or item.get("post_id") or ""
            link    = item.get("url") or item.get("link") or f"{self.BASE_URL}/post/{post_id}"

            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME,
                area=area,
                title=title or "N/A",
                price=price,
                link=link,
                phone=self.extract_phone(text_blob),
                furnished=self.detect_furnished(text_blob),
                property_type=self.detect_property_type(text_blob),
                description=text_blob[:200],
            ))
        except Exception as exc:
            logger.debug(f"[Haraj] API item error: {exc}")
