"""Base scraper class with shared utilities."""

import re
import time
import random
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup

from config import SEARCH_CONFIG, SCRAPER_CONFIG, DEFAULT_HEADERS, JSON_HEADERS

logger = logging.getLogger(__name__)


class BaseScraper:
    SOURCE_NAME = "Unknown"

    def __init__(self):
        self.listings = []
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.config = SEARCH_CONFIG
        self.scraper_config = SCRAPER_CONFIG

    # ------------------------------------------------------------------ #
    # HTTP helpers
    # ------------------------------------------------------------------ #

    def get(self, url, params=None, headers=None, is_json=False, retries=None):
        """GET with retry logic and rate limiting."""
        if retries is None:
            retries = self.scraper_config["max_retries"]

        req_headers = JSON_HEADERS if is_json else DEFAULT_HEADERS
        if headers:
            req_headers = {**req_headers, **headers}

        for attempt in range(retries):
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    headers=req_headers,
                    timeout=self.scraper_config["timeout"],
                )
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (429, 503):
                    wait = 2 ** attempt * 5
                    logger.warning(f"Rate limited ({resp.status_code}). Waiting {wait}s…")
                    time.sleep(wait)
                else:
                    logger.debug(f"HTTP {resp.status_code} for {url}")
                    return resp
            except requests.RequestException as exc:
                logger.warning(f"Request error ({attempt+1}/{retries}): {exc}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        return None

    def _delay(self):
        time.sleep(random.uniform(
            self.scraper_config["delay_min"],
            self.scraper_config["delay_max"],
        ))

    # ------------------------------------------------------------------ #
    # Parsing utilities
    # ------------------------------------------------------------------ #

    def extract_price(self, text):
        """Return the annual SAR price as int, or 0 if not found."""
        if isinstance(text, (int, float)):
            return int(text)

        text = str(text).replace(",", "").replace("٬", "").replace("\xa0", "")

        # Monthly price → annual
        monthly_patterns = [
            r"(\d{3,6})\s*(?:sar|sr|ريال|riyals?)?\s*/?\s*(?:month|mo|شهر|شهري)",
            r"(?:monthly|شهري)\s*:?\s*(\d{3,6})",
        ]
        for p in monthly_patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                monthly = int(m.group(1))
                if 500 <= monthly <= 15000:
                    return monthly * 12

        # Annual price patterns
        annual_patterns = [
            r"(\d{4,6})\s*(?:sar|sr|ريال|riyals?)?\s*/?\s*(?:year|yr|annual|سنوي|سنة)",
            r"(?:annual|yearly|سنوي)\s*:?\s*(\d{4,6})",
            r"(\d{4,6})\s*(?:sar|sr|ريال|riyals?)",
            r"(?:sar|sr|ريال|riyals?)\s*(\d{4,6})",
            r"\b(\d{4,6})\b",
        ]
        for p in annual_patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                price = int(m.group(1))
                if 1000 <= price <= 500000:
                    return price
        return 0

    def extract_phone(self, text):
        """Extract a Saudi mobile/landline number from text."""
        text = str(text)
        patterns = [
            r"(\+966\s*5\d[\d\s\-]{7,9})",
            r"(00966\s*5\d[\d\s\-]{7,9})",
            r"(05\d[\d\s\-]{7,9})",
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                phone = re.sub(r"[\s\-]", "", m.group(1))
                return phone
        return "N/A"

    def detect_furnished(self, text):
        text_low = str(text).lower()
        unfurnished_kw = ["unfurnished", "غير مفروش", "غير مفروشة", "بدون أثاث", "without furniture"]
        furnished_kw   = ["fully furnished", "مفروش بالكامل", "furnished", "مفروش", "مفروشة", "أثاث كامل"]
        for kw in unfurnished_kw:
            if kw in text_low:
                return "Unfurnished"
        for kw in furnished_kw:
            if kw in text_low:
                return "Furnished"
        return "Not specified"

    def detect_property_type(self, text):
        text_low = str(text).lower()
        if any(k in text_low for k in ["studio", "استوديو", "ستوديو"]):
            return "Studio"
        if any(k in text_low for k in ["1 bed", "1bhk", "one bed", "غرفة واحدة", "غرفة وصالة"]):
            return "1 BHK"
        return "Studio"  # default since we're filtering for studios

    def detect_area(self, text):
        text_low = str(text).lower()
        area_keywords = {
            "malaz":        ["malaz", "الملز", "al malaz", "al-malaz"],
            "rabwah":       ["rabwah", "الربوة", "ar rabwah", "ar-rabwah"],
            "sulaimaniyah": ["sulaimaniyah", "sulemaniyah", "السليمانية", "as sulaimaniyah"],
            "near_metro":   ["metro", "مترو", "near metro"],
        }
        for area_key, keywords in area_keywords.items():
            if any(k in text_low for k in keywords):
                return area_key
        return "Unknown"

    def in_price_range(self, price):
        if not price:
            return True  # keep unknowns for manual review
        return self.config["min_price"] <= price <= self.config["max_price"]

    def make_listing(self, **kwargs):
        """Return a normalised listing dict."""
        price = kwargs.get("price", 0)
        preferred = (
            self.config["min_price"] <= price <= self.config["preferred_max_price"]
            if price else None
        )
        price_note = ""
        if price:
            if price <= self.config["preferred_max_price"]:
                price_note = "✓ In preferred range"
            elif price <= self.config["max_price"]:
                price_note = "⚠ Slightly above preferred"

        return {
            "source":        kwargs.get("source", self.SOURCE_NAME),
            "area":          kwargs.get("area", "Unknown"),
            "title":         kwargs.get("title", "N/A"),
            "property_type": kwargs.get("property_type", "Studio"),
            "price_sar":     price if price else "Unknown",
            "price_label":   f"{price:,} SAR/yr" if price else "N/A",
            "price_note":    price_note,
            "furnished":     kwargs.get("furnished", "Not specified"),
            "bedrooms":      kwargs.get("bedrooms", "Studio"),
            "bathrooms":     kwargs.get("bathrooms", "N/A"),
            "size_sqm":      kwargs.get("size_sqm", "N/A"),
            "phone":         kwargs.get("phone", "N/A"),
            "link":          kwargs.get("link", "N/A"),
            "description":   kwargs.get("description", ""),
            "scraped_at":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    # ------------------------------------------------------------------ #
    # Abstract interface
    # ------------------------------------------------------------------ #

    def scrape(self):
        raise NotImplementedError
