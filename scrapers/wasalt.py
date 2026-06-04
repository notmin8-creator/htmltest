"""Scraper for wasalt.com — modern Saudi real-estate platform."""

import re
import json
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper

logger = logging.getLogger(__name__)


class WasaltScraper(BaseScraper):
    SOURCE_NAME = "Wasalt.com"
    BASE_URL    = "https://wasalt.com"
    API_BASE    = "https://api.wasalt.com"

    AREA_SLUGS = {
        "malaz":        "malaz",
        "rabwah":       "rabwah",
        "sulaimaniyah": "sulaimaniyah",
    }

    def scrape(self):
        logger.info("[Wasalt] Starting scrape…")
        for area_key, slug in self.AREA_SLUGS.items():
            fetched = self._api_search(area_key, slug)
            if not fetched:
                self._html_search(area_key, slug)
            self._delay()
        logger.info(f"[Wasalt] Done — {len(self.listings)} listings collected.")
        return self.listings

    # ------------------------------------------------------------------ #
    # API approach
    # ------------------------------------------------------------------ #

    def _api_search(self, area_key, slug):
        endpoints = [
            f"{self.API_BASE}/v1/listings",
            f"{self.API_BASE}/v2/listings",
            f"{self.API_BASE}/v1/properties",
            f"{self.API_BASE}/api/v1/properties/search",
        ]
        params = {
            "city":       "riyadh",
            "district":   slug,
            "type":       "studio",
            "purpose":    "rent",
            "price_min":  self.config["min_price"],
            "price_max":  self.config["max_price"],
            "page":       1,
            "per_page":   50,
        }
        for endpoint in endpoints:
            resp = self.get(endpoint, params=params, is_json=True)
            if resp and resp.status_code == 200:
                try:
                    data = resp.json()
                    items = (
                        data.get("listings") or data.get("data")
                        or data.get("properties") or data.get("results")
                        or (data if isinstance(data, list) else [])
                    )
                    if items:
                        for item in items:
                            self._parse_api_item(item, area_key)
                        return True
                except Exception as exc:
                    logger.debug(f"[Wasalt] API error: {exc}")
        return False

    def _parse_api_item(self, item, area_key):
        try:
            price = self.extract_price(
                item.get("price") or item.get("annual_rent")
                or item.get("rent") or item.get("yearly_price") or 0
            )
            if not self.in_price_range(price):
                return

            prop_id = item.get("id") or item.get("property_id") or ""
            slug    = item.get("slug") or item.get("url") or ""
            link    = (
                item.get("url") or item.get("link")
                or f"{self.BASE_URL}/en/property/{slug or prop_id}"
            )
            if not link.startswith("http"):
                link = f"{self.BASE_URL}{link}"

            is_furnished = item.get("is_furnished") or item.get("furnished")
            furnished = (
                "Furnished"   if is_furnished is True
                else ("Unfurnished" if is_furnished is False else "Not specified")
            )

            title = (
                item.get("title") or item.get("name")
                or item.get("property_name") or "N/A"
            )
            text_blob = f"{title} {item.get('description', '')}"

            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME,
                area=area_key,
                title=title,
                price=price,
                link=link,
                phone=str(item.get("phone") or item.get("mobile") or "N/A"),
                furnished=furnished,
                property_type=self.detect_property_type(text_blob),
                bedrooms=item.get("bedrooms") or item.get("beds") or "Studio",
                bathrooms=item.get("bathrooms") or item.get("baths") or "N/A",
                size_sqm=item.get("area") or item.get("size_sqm") or "N/A",
                description=str(item.get("description", ""))[:200],
            ))
        except Exception as exc:
            logger.debug(f"[Wasalt] API item error: {exc}")

    # ------------------------------------------------------------------ #
    # HTML fallback
    # ------------------------------------------------------------------ #

    def _html_search(self, area_key, slug):
        url_variants = [
            f"{self.BASE_URL}/en/riyadh/{slug}/rent/studio",
            f"{self.BASE_URL}/en/riyadh/{slug}/for-rent/studio",
            f"{self.BASE_URL}/ar/الرياض/{slug}/للإيجار/استوديو",
        ]
        for url in url_variants:
            resp = self.get(url)
            if resp and resp.status_code == 200:
                self._parse_html(resp.text, area_key)
                return
            self._delay()

    def _parse_html(self, html, area_key):
        soup = BeautifulSoup(html, "lxml")

        # Try __NEXT_DATA__ or window.__INITIAL_STATE__
        for script in soup.find_all("script", id="__NEXT_DATA__"):
            try:
                data  = json.loads(script.string or "")
                items = (
                    data.get("props", {}).get("pageProps", {}).get("listings", [])
                    or data.get("props", {}).get("pageProps", {}).get("properties", [])
                )
                for item in items:
                    self._parse_api_item(item, area_key)
                return
            except Exception:
                pass

        # Generic card scraping
        cards = (
            soup.find_all("div", class_=re.compile(r"PropertyCard|property-card|listing-card", re.I))
            or soup.find_all("article")
            or soup.find_all("div", class_=re.compile(r"property|listing|card", re.I))
        )
        for card in cards:
            text_blob = card.get_text(" ", strip=True)
            price = self.extract_price(text_blob)
            if not self.in_price_range(price):
                continue

            title_tag = card.find(["h2", "h3", "h4"])
            a_tag     = card.find("a", href=True)
            title = title_tag.get_text(strip=True) if title_tag else text_blob[:80]
            href  = a_tag["href"] if a_tag else "N/A"
            link  = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME,
                area=area_key,
                title=title,
                price=price,
                link=link,
                phone=self.extract_phone(text_blob),
                furnished=self.detect_furnished(text_blob),
                property_type=self.detect_property_type(text_blob),
                description=text_blob[:200],
            ))
