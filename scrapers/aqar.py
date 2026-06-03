"""Scraper for sa.aqar.fm — popular Saudi real-estate classifieds."""

import re
import json
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper

logger = logging.getLogger(__name__)


class AqarScraper(BaseScraper):
    SOURCE_NAME = "Aqar.fm"
    BASE_URL = "https://sa.aqar.fm"
    API_URL  = "https://sa.aqar.fm/api/v1"

    AREA_SLUGS = {
        "malaz":        ("الملز",        "al-malaz"),
        "rabwah":       ("الربوة",       "ar-rabwah"),
        "sulaimaniyah": ("السليمانية",   "as-sulaimaniyah"),
    }

    def scrape(self):
        logger.info("[Aqar] Starting scrape…")
        for area_key, (area_ar, area_en) in self.AREA_SLUGS.items():
            # Try API first, fall back to HTML
            fetched = self._api_search(area_key, area_ar)
            if not fetched:
                self._html_search(area_key, area_ar, area_en)
            self._delay()
        logger.info(f"[Aqar] Done — {len(self.listings)} listings collected.")
        return self.listings

    # ------------------------------------------------------------------ #
    # API approach
    # ------------------------------------------------------------------ #

    def _api_search(self, area_key, area_ar):
        """Try Aqar's internal search API (may require auth)."""
        endpoints = [
            f"{self.API_URL}/listings/search",
            f"{self.API_URL}/properties/search",
            f"{self.BASE_URL}/api/search",
        ]
        params = {
            "city":      "الرياض",
            "district":  area_ar,
            "purpose":   "rent",
            "category":  "studio",
            "price_min": self.config["min_price"],
            "price_max": self.config["max_price"],
            "per_page":  50,
        }
        for endpoint in endpoints:
            resp = self.get(endpoint, params=params, is_json=True)
            if resp and resp.status_code == 200:
                try:
                    data = resp.json()
                    items = (
                        data.get("data")
                        or data.get("listings")
                        or data.get("properties")
                        or data.get("items")
                        or (data if isinstance(data, list) else [])
                    )
                    if items:
                        for item in items:
                            self._parse_api_item(item, area_key)
                        return True
                except Exception as exc:
                    logger.debug(f"[Aqar] API parse error: {exc}")
        return False

    def _parse_api_item(self, item, area_key):
        try:
            price = self.extract_price(
                item.get("price") or item.get("annual_price") or item.get("rent") or 0
            )
            if not self.in_price_range(price):
                return

            prop_id  = item.get("id") or item.get("property_id") or ""
            slug     = item.get("slug") or item.get("url_slug") or ""
            link     = (
                item.get("url") or item.get("link")
                or (f"{self.BASE_URL}/property/{slug}" if slug else f"{self.BASE_URL}/property/{prop_id}")
            )
            phone = (
                item.get("phone") or item.get("mobile")
                or item.get("contact_phone") or "N/A"
            )
            is_furnished = item.get("furnished") or item.get("is_furnished")
            furnished = (
                "Furnished" if is_furnished is True
                else ("Unfurnished" if is_furnished is False else "Not specified")
            )

            title = item.get("title") or item.get("name") or item.get("description") or "N/A"
            text_blob = f"{title} {item.get('description', '')}"

            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME,
                area=area_key,
                title=title,
                price=price,
                link=link,
                phone=str(phone) if phone != "N/A" else "N/A",
                furnished=furnished,
                property_type=self.detect_property_type(text_blob),
                bedrooms=item.get("bedrooms") or item.get("beds") or "Studio",
                bathrooms=item.get("bathrooms") or item.get("baths") or "N/A",
                size_sqm=item.get("area") or item.get("size") or "N/A",
                description=str(item.get("description", ""))[:200],
            ))
        except Exception as exc:
            logger.debug(f"[Aqar] API item parse error: {exc}")

    # ------------------------------------------------------------------ #
    # HTML fallback
    # ------------------------------------------------------------------ #

    def _html_search(self, area_key, area_ar, area_en):
        url_variants = [
            f"{self.BASE_URL}/استوديو-للإيجار/الرياض/{area_ar}",
            f"{self.BASE_URL}/studio-for-rent/riyadh/{area_en}",
            f"{self.BASE_URL}/شقق-للإيجار/الرياض/{area_ar}",
        ]
        for url in url_variants:
            resp = self.get(url)
            if resp and resp.status_code == 200:
                self._parse_html_page(resp.text, area_key)
                self._delay()
                return

    def _parse_html_page(self, html, area_key):
        soup = BeautifulSoup(html, "lxml")

        # Try embedded JSON (Next.js __NEXT_DATA__ or similar)
        for script in soup.find_all("script", id="__NEXT_DATA__"):
            try:
                data = json.loads(script.string or "")
                props = (
                    data.get("props", {})
                       .get("pageProps", {})
                       .get("listings", [])
                )
                for item in props:
                    self._parse_api_item(item, area_key)
                return
            except Exception:
                pass

        # Raw card parsing
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

            size_m  = re.search(r"(\d+)\s*(?:sqm|m²|متر)", text_blob, re.I)
            size_sqm = size_m.group(1) if size_m else "N/A"

            self.listings.append(self.make_listing(
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
            ))
