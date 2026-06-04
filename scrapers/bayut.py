"""Bayut.sa scraper — uses Playwright + Algolia API interception."""

import re
import json
import logging
import time
from bs4 import BeautifulSoup
from .base import BaseScraper
from .pw_browser import fetch

logger = logging.getLogger(__name__)


class BayutScraper(BaseScraper):
    SOURCE_NAME = "Bayut.sa"
    BASE_URL    = "https://www.bayut.sa"

    AREA_PATHS = {
        "malaz":        "/to-rent/studio/riyadh/al-malaz/",
        "rabwah":       "/to-rent/studio/riyadh/ar-rabwah/",
        "sulaimaniyah": "/to-rent/studio/riyadh/as-sulaimaniyah/",
    }

    # Intercept Algolia + any internal property API calls
    API_PATTERNS = ["algolia.net", "algolia.io", "/api/properties", "/api/listings", "bayut"]

    def scrape(self):
        logger.info("[Bayut] Starting scrape with Playwright…")
        for area_key, path in self.AREA_PATHS.items():
            for page_num in range(1, 4):
                url = f"{self.BASE_URL}{path}?page={page_num}"
                html, intercepted = fetch(
                    url,
                    api_patterns=self.API_PATTERNS,
                    wait_selector="[class*='listing'], article, [data-testid*='property']",
                )
                found = self._process(html, intercepted, area_key)
                if not found:
                    break
                time.sleep(2)
        logger.info(f"[Bayut] Done — {len(self.listings)} listings.")
        return self.listings

    def _process(self, html, intercepted, area_key):
        found = False

        # 1. Try intercepted Algolia / API responses
        for resp in intercepted:
            data = resp["data"]
            hits = []
            # Algolia multi-index response
            if "results" in data:
                for r in data["results"]:
                    hits.extend(r.get("hits", []))
            elif "hits" in data:
                hits = data["hits"]
            # Generic listings array
            elif isinstance(data, list):
                hits = data
            elif "properties" in data or "listings" in data:
                hits = data.get("properties") or data.get("listings") or []

            for hit in hits:
                listing = self._parse_hit(hit, area_key)
                if listing:
                    self.listings.append(listing)
                    found = True

        # 2. Fall back to HTML parsing
        if not found and html:
            soup  = BeautifulSoup(html, "lxml")
            cards = (
                soup.find_all("article")
                or soup.find_all("div", class_=re.compile(r"PropertyCard|listing-card|property-item", re.I))
                or soup.find_all("li",  class_=re.compile(r"listing|property", re.I))
            )
            for card in cards:
                listing = self._parse_card(card, area_key)
                if listing:
                    self.listings.append(listing)
                    found = True

        return found

    def _parse_hit(self, hit, area_key):
        try:
            price = self.extract_price(
                hit.get("price") or hit.get("rentFrequency") or
                hit.get("yearlyRent") or hit.get("monthly_price", 0)
            )
            # Bayut prices are sometimes monthly — if suspiciously low, multiply
            if 0 < price < 3000:
                price = price * 12

            if not self.in_price_range(price):
                return None

            prop_id = hit.get("externalID") or hit.get("id") or ""
            slug    = hit.get("slug") or hit.get("url_path") or ""
            link    = (
                hit.get("pageURL") or hit.get("url")
                or (f"{self.BASE_URL}/property/{slug}" if slug
                    else f"{self.BASE_URL}/property/{prop_id}")
            )
            if link and not link.startswith("http"):
                link = f"{self.BASE_URL}{link}"

            furnishing = str(hit.get("furnishingStatus", hit.get("furnished", ""))).lower()
            furnished  = (
                "Furnished"   if furnishing in ("furnished", "f", "yes", "true", "1")
                else ("Unfurnished" if furnishing in ("unfurnished", "u", "no", "false", "0")
                      else "Not specified")
            )

            rooms = hit.get("rooms") or hit.get("bedrooms") or 0
            beds  = "Studio" if str(rooms).upper() in ("0", "ST", "STUDIO", "") else str(rooms)

            agency = hit.get("agency", {})
            phone  = (
                hit.get("phoneNumber") or hit.get("phone")
                or agency.get("phone") or "N/A"
            )

            title = (
                hit.get("title") or hit.get("name")
                or hit.get("description", "")[:80] or "N/A"
            )
            text_blob = f"{title} {hit.get('description', '')}"

            return self.make_listing(
                source=self.SOURCE_NAME,
                area=area_key,
                title=title,
                price=price,
                link=link,
                phone=str(phone),
                furnished=furnished,
                property_type=self.detect_property_type(text_blob),
                bedrooms=beds,
                bathrooms=hit.get("bathrooms") or "N/A",
                size_sqm=hit.get("area") or hit.get("size") or "N/A",
                description=str(hit.get("description", ""))[:200],
            )
        except Exception as exc:
            logger.debug(f"[Bayut] Hit parse error: {exc}")
            return None

    def _parse_card(self, card, area_key):
        try:
            text_blob = card.get_text(" ", strip=True)
            price = self.extract_price(text_blob)
            if not self.in_price_range(price):
                return None

            title_tag = card.find(["h2", "h3", "h4"])
            a_tag     = card.find("a", href=True)
            title = title_tag.get_text(strip=True) if title_tag else text_blob[:80]
            href  = a_tag["href"] if a_tag else "N/A"
            link  = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            size_m   = re.search(r"(\d+)\s*(?:sqm|m²|متر)", text_blob, re.I)
            size_sqm = size_m.group(1) if size_m else "N/A"

            return self.make_listing(
                source=self.SOURCE_NAME,
                area=area_key,
                title=title,
                price=price,
                link=link,
                phone=self.extract_phone(text_blob),
                furnished=self.detect_furnished(text_blob),
                property_type=self.detect_property_type(text_blob),
                size_sqm=size_sqm,
                description=text_blob[:200],
            )
        except Exception as exc:
            logger.debug(f"[Bayut] Card parse error: {exc}")
            return None
