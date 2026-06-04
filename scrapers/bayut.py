"""
Bayut.sa scraper — extracts Algolia credentials from their JS bundle
then queries Algolia directly (CDN-based, no IP blocking).
"""

import re
import json
import logging
import requests
from .base import BaseScraper

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

# Known Bayut SA Algolia app ID (embedded publicly in their JS)
ALGOLIA_APP_ID = "ll8iz00g37"

# Candidate index names for Bayut SA rentals (en + ar)
CANDIDATE_INDICES = [
    "bayut-sa-for-rent-en",
    "bayut-sa-properties-for-rent-en",
    "production_bayut_sa_for-rent_en",
    "bayut-sa-for-rent-ar",
    "bayut-sa-properties-for-rent-ar",
]

AREA_FILTERS = {
    "malaz":        ["al-malaz", "malaz", "الملز"],
    "rabwah":       ["ar-rabwah", "rabwah", "الربوة"],
    "sulaimaniyah": ["as-sulaimaniyah", "sulaimaniyah", "السليمانية"],
}


class BayutScraper(BaseScraper):
    SOURCE_NAME = "Bayut.sa"
    BASE_URL = "https://www.bayut.sa"

    def __init__(self):
        super().__init__()
        self._algolia_key = None
        self._algolia_index = None

    def scrape(self):
        logger.info("[Bayut] Starting scrape via Algolia API…")

        # Step 1: get Algolia credentials
        self._algolia_key = self._find_algolia_key()
        if not self._algolia_key:
            logger.warning("[Bayut] Could not find Algolia key — skipping.")
            return self.listings

        # Step 2: discover working index name
        self._algolia_index = self._discover_index()
        if not self._algolia_index:
            logger.warning("[Bayut] Could not discover Algolia index — skipping.")
            return self.listings

        logger.info(f"[Bayut] Using index: {self._algolia_index}")

        # Step 3: query per area
        for area_key, slugs in AREA_FILTERS.items():
            for slug in slugs[:1]:   # try first slug
                self._query_algolia(area_key, slug)

        logger.info(f"[Bayut] Done — {len(self.listings)} listings.")
        return self.listings

    # ------------------------------------------------------------------ #
    # Algolia credential extraction
    # ------------------------------------------------------------------ #

    def _find_algolia_key(self):
        """Try to extract the Algolia search-only API key from Bayut's pages."""
        urls_to_try = [
            f"{self.BASE_URL}/en/saudi-arabia/",
            f"{self.BASE_URL}/",
            f"{self.BASE_URL}/to-rent/studio/riyadh/",
        ]
        for url in urls_to_try:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15)
                if resp.status_code != 200:
                    continue
                key = self._extract_key_from_html(resp.text)
                if key:
                    logger.info(f"[Bayut] Algolia key found from {url}")
                    return key
            except Exception as exc:
                logger.debug(f"[Bayut] Key extraction error: {exc}")

        # Try fetching the _next/static JS chunk that contains the Algolia config
        try:
            resp = requests.get(f"{self.BASE_URL}/", headers=HEADERS, timeout=15)
            if resp.ok:
                # Find JS bundle URLs
                chunk_urls = re.findall(
                    r'"(/(_next|static)/[^"]+\.js)"', resp.text
                )
                for (path, _) in chunk_urls[:10]:
                    try:
                        js_resp = requests.get(
                            f"{self.BASE_URL}{path}", headers=HEADERS, timeout=10
                        )
                        if js_resp.ok:
                            key = self._extract_key_from_html(js_resp.text)
                            if key:
                                return key
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug(f"[Bayut] JS bundle extraction error: {exc}")

        return None

    def _extract_key_from_html(self, text):
        """Search HTML/JS text for an Algolia search-only API key."""
        patterns = [
            # JSON config: "apiKey":"<key>"
            r'"apiKey"\s*:\s*"([a-f0-9]{32})"',
            # Next.js env: ALGOLIA_API_KEY or similar
            r'ALGOLIA[_A-Z]*KEY["\s:]+([a-f0-9]{32})',
            # Generic: algolia.*key
            r'algolia[^}]{0,200}key["\s:]+([a-f0-9]{32})',
            # Direct Algolia header value
            r'X-Algolia-API-Key["\s:]+([a-f0-9]{32})',
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    # ------------------------------------------------------------------ #
    # Index discovery
    # ------------------------------------------------------------------ #

    def _discover_index(self):
        """Try each candidate index name until one works."""
        for index_name in CANDIDATE_INDICES:
            try:
                result = self._algolia_search(
                    index_name,
                    filters="",
                    query="studio riyadh",
                    hits_per_page=1,
                )
                if result and result.get("nbHits", 0) > 0:
                    return index_name
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------ #
    # Algolia search
    # ------------------------------------------------------------------ #

    def _query_algolia(self, area_key, area_slug):
        """Query Algolia for listings in one area."""
        for page in range(0, self.scraper_config["max_pages_per_site"]):
            try:
                filters = (
                    f"purpose:for-rent AND "
                    f"(location3.slug:{area_slug} OR location4.slug:{area_slug}) AND "
                    f"rooms:0 AND "
                    f"price >= {self.config['min_price']} AND "
                    f"price <= {self.config['max_price']}"
                )
                result = self._algolia_search(
                    self._algolia_index,
                    filters=filters,
                    query="studio",
                    hits_per_page=50,
                    page=page,
                )
                if not result:
                    break

                hits = result.get("hits", [])
                if not hits:
                    break

                for hit in hits:
                    listing = self._parse_hit(hit, area_key)
                    if listing:
                        self.listings.append(listing)

                # Stop if we've seen all pages
                total_pages = result.get("nbPages", 1)
                if page >= total_pages - 1:
                    break

                self._delay()
            except Exception as exc:
                logger.debug(f"[Bayut] Algolia query error: {exc}")
                break

    def _algolia_search(self, index_name, filters, query="", hits_per_page=50, page=0):
        """Make a direct Algolia search API call."""
        url = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{index_name}/query"
        headers = {
            "X-Algolia-Application-Id": ALGOLIA_APP_ID,
            "X-Algolia-API-Key": self._algolia_key,
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "filters": filters,
            "hitsPerPage": hits_per_page,
            "page": page,
            "attributesToRetrieve": [
                "title", "price", "rooms", "bathrooms", "area",
                "furnishingStatus", "furnished", "location3", "location4",
                "phoneNumber", "externalID", "slug", "pageURL", "description",
                "rentFrequency", "yearlyRent", "monthlyRent",
            ],
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        logger.debug(f"[Bayut] Algolia returned {resp.status_code}: {resp.text[:200]}")
        return None

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #

    def _parse_hit(self, hit, area_key):
        try:
            # Price handling — Bayut can store monthly or yearly
            price = int(hit.get("price") or 0)
            rent_freq = str(hit.get("rentFrequency", "yearly")).lower()
            if rent_freq == "monthly" and price:
                price = price * 12
            elif rent_freq == "weekly" and price:
                price = price * 52

            if not self.in_price_range(price):
                return None

            prop_id = hit.get("externalID") or hit.get("objectID") or ""
            slug    = hit.get("slug") or ""
            link    = (
                hit.get("pageURL")
                or (f"{self.BASE_URL}/property/{slug}" if slug
                    else f"{self.BASE_URL}/property/{prop_id}")
            )
            if link and not link.startswith("http"):
                link = f"{self.BASE_URL}{link}"

            furn = str(hit.get("furnishingStatus", hit.get("furnished", ""))).lower()
            furnished = (
                "Furnished"   if furn in ("furnished", "f", "yes", "true")
                else ("Unfurnished" if furn in ("unfurnished", "u", "no", "false")
                      else "Not specified")
            )

            rooms = hit.get("rooms", 0)
            beds  = "Studio" if str(rooms) in ("0", "ST", "STUDIO", "") else str(rooms)
            title = hit.get("title") or f"Studio – {area_key.title()}"

            return self.make_listing(
                source=self.SOURCE_NAME,
                area=area_key,
                title=title,
                price=price,
                link=link,
                phone=str(hit.get("phoneNumber") or "N/A"),
                furnished=furnished,
                property_type="Studio",
                bedrooms=beds,
                bathrooms=hit.get("bathrooms") or "N/A",
                size_sqm=hit.get("area") or "N/A",
                description=str(hit.get("description", ""))[:200],
            )
        except Exception as exc:
            logger.debug(f"[Bayut] Hit parse error: {exc}")
            return None
