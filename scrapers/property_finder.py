"""Scraper for propertyfinder.sa — Property Finder Saudi Arabia."""

import re
import json
import logging
from bs4 import BeautifulSoup
from .base import BaseScraper

logger = logging.getLogger(__name__)


class PropertyFinderScraper(BaseScraper):
    SOURCE_NAME = "PropertyFinder.sa"
    BASE_URL = "https://www.propertyfinder.sa"

    AREA_SLUGS = {
        "malaz":        "al-malaz",
        "rabwah":       "ar-rabwah",
        "sulaimaniyah": "as-sulaimaniyah",
    }

    def scrape(self):
        logger.info("[PropertyFinder] Starting scrape…")
        for area_key, slug in self.AREA_SLUGS.items():
            self._scrape_area(area_key, slug)
            self._delay()
        logger.info(f"[PropertyFinder] Done — {len(self.listings)} listings collected.")
        return self.listings

    def _scrape_area(self, area_key, slug):
        for page in range(1, self.scraper_config["max_pages_per_site"] + 1):
            url = (
                f"{self.BASE_URL}/en/search?"
                f"c=2&fu=0&ob=mr&page={page}"
                f"&q[city_level_1][]={slug}"
                f"&q[price][max]={self.config['max_price']}"
                f"&q[price][min]={self.config['min_price']}"
                f"&q[rooms][]=ST"  # Studio
            )
            resp = self.get(url)
            if not resp or resp.status_code != 200:
                break
            found = self._parse_page(resp.text, area_key)
            if not found:
                break
            self._delay()

    def _parse_page(self, html, area_key):
        soup = BeautifulSoup(html, "lxml")
        found_any = False

        # Try __NEXT_DATA__
        for script in soup.find_all("script", id="__NEXT_DATA__"):
            try:
                data  = json.loads(script.string or "")
                items = (
                    data.get("props", {}).get("pageProps", {}).get("searchResults", {}).get("properties", [])
                    or data.get("props", {}).get("pageProps", {}).get("listings", [])
                )
                for item in items:
                    self._parse_api_item(item, area_key)
                    found_any = True
                return found_any
            except Exception:
                pass

        # HTML cards
        cards = (
            soup.find_all("div", class_=re.compile(r"card-list__item|property-card|listing-item", re.I))
            or soup.find_all("article")
            or soup.find_all("div", {"data-testid": re.compile(r"property|listing", re.I)})
        )
        for card in cards:
            listing = self._parse_card(card, area_key)
            if listing:
                self.listings.append(listing)
                found_any = True
        return found_any

    def _parse_api_item(self, item, area_key):
        try:
            price = self.extract_price(
                item.get("price") or item.get("yearly_price") or item.get("rent_price") or 0
            )
            if not self.in_price_range(price):
                return

            prop_id = item.get("id") or item.get("externalID") or ""
            slug    = item.get("slug") or item.get("url_path") or ""
            link    = (
                item.get("url") or item.get("link")
                or (f"{self.BASE_URL}/en/property-for-rent/{slug}" if slug
                    else f"{self.BASE_URL}/en/property/{prop_id}")
            )
            if not link.startswith("http"):
                link = f"{self.BASE_URL}{link}"

            # Furnished
            furnishing = str(item.get("furnishing", "")).lower()
            if furnishing in ("furnished", "f"):
                furnished = "Furnished"
            elif furnishing in ("unfurnished", "u"):
                furnished = "Unfurnished"
            else:
                furnished = "Not specified"

            title = item.get("title") or item.get("name") or "N/A"
            text_blob = f"{title} {item.get('description', '')}"
            rooms = item.get("rooms") or item.get("bedrooms") or 0
            beds  = "Studio" if str(rooms).upper() in ("0", "ST", "STUDIO") else str(rooms)

            self.listings.append(self.make_listing(
                source=self.SOURCE_NAME,
                area=area_key,
                title=title,
                price=price,
                link=link,
                phone=self.extract_phone(str(item.get("phone", ""))),
                furnished=furnished,
                property_type=self.detect_property_type(text_blob),
                bedrooms=beds,
                bathrooms=item.get("bathrooms") or "N/A",
                size_sqm=item.get("area") or item.get("size") or "N/A",
                description=str(item.get("description", ""))[:200],
            ))
        except Exception as exc:
            logger.debug(f"[PropertyFinder] API item error: {exc}")

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

            size_m   = re.search(r"(\d+)\s*(?:sqm|m²|sq ft)", text_blob, re.I)
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
            logger.debug(f"[PropertyFinder] Card error: {exc}")
            return None
