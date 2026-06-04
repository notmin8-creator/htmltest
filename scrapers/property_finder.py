"""PropertyFinder.sa scraper — Playwright + API interception."""

import re
import json
import logging
import time
from bs4 import BeautifulSoup
from .base import BaseScraper
from .pw_browser import fetch

logger = logging.getLogger(__name__)


class PropertyFinderScraper(BaseScraper):
    SOURCE_NAME = "PropertyFinder.sa"
    BASE_URL    = "https://www.propertyfinder.sa"

    AREA_SLUGS = {
        "malaz":        "al-malaz",
        "rabwah":       "ar-rabwah",
        "sulaimaniyah": "as-sulaimaniyah",
    }

    API_PATTERNS = ["propertyfinder", "/api/", "graphql"]

    def scrape(self):
        logger.info("[PropertyFinder] Starting scrape with Playwright…")
        for area_key, slug in self.AREA_SLUGS.items():
            for page_num in range(1, 4):
                url = (
                    f"{self.BASE_URL}/en/search?"
                    f"c=2&fu=0&ob=mr&page={page_num}"
                    f"&q[city_level_1][]={slug}"
                    f"&q[price][max]={self.config['max_price']}"
                    f"&q[price][min]={self.config['min_price']}"
                    f"&q[rooms][]=ST"
                )
                html, intercepted = fetch(
                    url,
                    api_patterns=self.API_PATTERNS,
                    wait_selector="[class*='card'], [class*='listing'], article",
                )
                found = self._process(html, intercepted, area_key)
                if not found:
                    break
                time.sleep(2)
        logger.info(f"[PropertyFinder] Done — {len(self.listings)} listings.")
        return self.listings

    def _process(self, html, intercepted, area_key):
        found = False

        for resp in intercepted:
            data  = resp["data"]
            items = (
                data.get("properties") or data.get("listings") or
                data.get("data", {}).get("properties", []) or
                (data if isinstance(data, list) else [])
            )
            for item in (items or []):
                listing = self._parse_api_item(item, area_key)
                if listing:
                    self.listings.append(listing)
                    found = True

        if not found and html:
            soup = BeautifulSoup(html, "lxml")
            for script in soup.find_all("script", id="__NEXT_DATA__"):
                try:
                    data  = json.loads(script.string or "")
                    items = (
                        data.get("props", {}).get("pageProps", {})
                           .get("searchResults", {}).get("properties", [])
                        or data.get("props", {}).get("pageProps", {}).get("listings", [])
                    )
                    for item in items:
                        listing = self._parse_api_item(item, area_key)
                        if listing:
                            self.listings.append(listing)
                            found = True
                except Exception:
                    pass

        if not found and html:
            soup  = BeautifulSoup(html, "lxml")
            cards = (
                soup.find_all("div", class_=re.compile(r"card-list|property-card|listing-item", re.I))
                or soup.find_all("article")
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
                size_m   = re.search(r"(\d+)\s*(?:sqm|m²|sq ft)", text_blob, re.I)
                self.listings.append(self.make_listing(
                    source=self.SOURCE_NAME, area=area_key, title=title, price=price,
                    link=link, phone=self.extract_phone(text_blob),
                    furnished=self.detect_furnished(text_blob),
                    property_type=self.detect_property_type(text_blob),
                    size_sqm=size_m.group(1) if size_m else "N/A",
                    description=text_blob[:200],
                ))
                found = True

        return found

    def _parse_api_item(self, item, area_key):
        try:
            price = self.extract_price(
                item.get("price") or item.get("yearly_price") or
                item.get("rent_price") or 0
            )
            if not self.in_price_range(price):
                return None

            prop_id = item.get("id") or item.get("externalID") or ""
            slug    = item.get("slug") or item.get("url_path") or ""
            link    = (
                item.get("url") or item.get("link")
                or (f"{self.BASE_URL}/en/property-for-rent/{slug}" if slug
                    else f"{self.BASE_URL}/en/property/{prop_id}")
            )
            if not link.startswith("http"):
                link = f"{self.BASE_URL}{link}"

            furn_val  = str(item.get("furnishing", "")).lower()
            furnished = (
                "Furnished"   if furn_val in ("furnished", "f")
                else ("Unfurnished" if furn_val in ("unfurnished", "u")
                      else "Not specified")
            )
            rooms = item.get("rooms") or item.get("bedrooms") or 0
            beds  = "Studio" if str(rooms).upper() in ("0", "ST", "STUDIO", "") else str(rooms)
            title = item.get("title") or item.get("name") or "N/A"
            text_blob = f"{title} {item.get('description', '')}"

            return self.make_listing(
                source=self.SOURCE_NAME, area=area_key, title=title, price=price,
                link=link,
                phone=self.extract_phone(str(item.get("phone", ""))),
                furnished=furnished,
                property_type=self.detect_property_type(text_blob),
                bedrooms=beds,
                bathrooms=item.get("bathrooms") or "N/A",
                size_sqm=item.get("area") or item.get("size") or "N/A",
                description=str(item.get("description", ""))[:200],
            )
        except Exception as exc:
            logger.debug(f"[PropertyFinder] API item error: {exc}")
            return None
