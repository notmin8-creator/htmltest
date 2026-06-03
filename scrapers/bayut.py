"""Scraper for bayut.sa — Saudi Arabia's leading property portal."""

import re
import json
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper

logger = logging.getLogger(__name__)


class BayutScraper(BaseScraper):
    SOURCE_NAME = "Bayut.sa"
    BASE_URL = "https://www.bayut.sa"

    # Area slugs as used in Bayut URLs
    AREA_SLUGS = {
        "malaz":        "al-malaz",
        "rabwah":       "ar-rabwah",
        "sulaimaniyah": "as-sulaimaniyah",
    }

    def scrape(self):
        logger.info("[Bayut] Starting scrape…")
        for area_key, area_slug in self.AREA_SLUGS.items():
            self._scrape_area(area_key, area_slug)
            self._delay()
        # Also try a broad Riyadh search without district filter
        self._scrape_broad()
        logger.info(f"[Bayut] Done — {len(self.listings)} listings collected.")
        return self.listings

    def _scrape_area(self, area_key, area_slug):
        page = 1
        max_pages = self.scraper_config["max_pages_per_site"]
        while page <= max_pages:
            url = (
                f"{self.BASE_URL}/to-rent/studio/riyadh/{area_slug}/"
                f"?page={page}"
            )
            resp = self.get(url)
            if not resp:
                break
            found = self._parse_page(resp.text, area_key)
            if not found:
                break
            page += 1
            self._delay()

    def _scrape_broad(self):
        """Broader search and filter by area keywords in description."""
        for page in range(1, 4):
            url = (
                f"{self.BASE_URL}/to-rent/studio/riyadh/"
                f"?min-price={self.config['min_price']}"
                f"&max-price={self.config['max_price']}"
                f"&page={page}"
            )
            resp = self.get(url)
            if not resp:
                break
            self._parse_page(resp.text, detect_area=True)
            self._delay()

    def _parse_page(self, html, area_key=None, detect_area=False):
        soup = BeautifulSoup(html, "lxml")
        found_any = False

        # Try JSON-LD structured data first (most reliable)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, list):
                    for item in data:
                        self._parse_jsonld(item, area_key, detect_area)
                        found_any = True
                elif isinstance(data, dict):
                    self._parse_jsonld(data, area_key, detect_area)
                    found_any = True
            except Exception:
                pass

        # Fall back to HTML card parsing
        cards = (
            soup.find_all("article")
            or soup.find_all("li", class_=re.compile(r"listing|property", re.I))
            or soup.find_all("div", class_=re.compile(r"PropertyCard|listing-card|property-item", re.I))
        )
        for card in cards:
            listing = self._parse_card(card, area_key, detect_area)
            if listing:
                self.listings.append(listing)
                found_any = True

        return found_any

    def _parse_jsonld(self, data, area_key, detect_area):
        try:
            dtype = data.get("@type", "")
            if dtype not in ("Apartment", "Residence", "RentAction", "Product"):
                return
            name  = data.get("name", data.get("description", "N/A"))
            url   = data.get("url", data.get("@id", "N/A"))
            price = 0
            offers = data.get("offers", {})
            if offers:
                price = self.extract_price(offers.get("price", 0))

            if not self.in_price_range(price):
                return

            text_blob = f"{name} {data.get('description', '')}"
            area = area_key or self.detect_area(text_blob)

            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME,
                area=area,
                title=name,
                price=price,
                link=url if url.startswith("http") else f"{self.BASE_URL}{url}",
                furnished=self.detect_furnished(text_blob),
                property_type=self.detect_property_type(text_blob),
            ))
        except Exception as exc:
            logger.debug(f"[Bayut] JSON-LD parse error: {exc}")

    def _parse_card(self, card, area_key, detect_area):
        try:
            text_blob = card.get_text(" ", strip=True)
            price = self.extract_price(text_blob)
            if not self.in_price_range(price):
                return None

            # Title
            title_tag = card.find(["h2", "h3", "h4"])
            title = title_tag.get_text(strip=True) if title_tag else text_blob[:80]

            # Link
            a_tag = card.find("a", href=True)
            link = "N/A"
            if a_tag:
                href = a_tag["href"]
                link = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            # Phone (rarely exposed on listing cards — noted as N/A)
            phone = self.extract_phone(text_blob)

            # Size
            size_m = re.search(r"(\d+)\s*(?:sqm|m²|متر)", text_blob, re.I)
            size_sqm = size_m.group(1) if size_m else "N/A"

            area = area_key if area_key else self.detect_area(text_blob)

            return self.make_listing(
                source=self.SOURCE_NAME,
                area=area,
                title=title,
                price=price,
                link=link,
                phone=phone,
                furnished=self.detect_furnished(text_blob),
                property_type=self.detect_property_type(text_blob),
                size_sqm=size_sqm,
                description=text_blob[:200],
            )
        except Exception as exc:
            logger.debug(f"[Bayut] Card parse error: {exc}")
            return None
