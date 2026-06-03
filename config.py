"""
Rental Scraper Agent Configuration
Target: Studio apartments in Riyadh (Malaz, Rabwah, Sulaimaniyah, near metro)
Price range: 10,000 - 23,000 SAR/year
"""

SEARCH_CONFIG = {
    "city": "Riyadh",
    "city_arabic": "الرياض",

    # Target neighborhoods (English + Arabic)
    "areas": {
        "malaz": {
            "en": "Al Malaz",
            "ar": "الملز",
            "bayut_slug": "al-malaz",
            "aqar_slug": "الملز",
            "wasalt_slug": "malaz",
            "opensooq_slug": "al-malaz",
        },
        "rabwah": {
            "en": "Ar Rabwah",
            "ar": "الربوة",
            "bayut_slug": "ar-rabwah",
            "aqar_slug": "الربوة",
            "wasalt_slug": "rabwah",
            "opensooq_slug": "al-rabwah",
        },
        "sulaimaniyah": {
            "en": "As Sulaimaniyah",
            "ar": "السليمانية",
            "bayut_slug": "as-sulaimaniyah",
            "aqar_slug": "السليمانية",
            "wasalt_slug": "sulaimaniyah",
            "opensooq_slug": "al-sulaimaniyah",
        },
        "near_sulaimaniyah": {
            "en": "Near Sulaimaniyah",
            "ar": "قرب السليمانية",
            "bayut_slug": None,
            "aqar_slug": None,
            "wasalt_slug": None,
            "opensooq_slug": None,
        },
        "near_metro": {
            "en": "Near Metro",
            "ar": "قرب المترو",
            "bayut_slug": None,
            "aqar_slug": None,
            "wasalt_slug": None,
            "opensooq_slug": None,
        },
    },

    # Price range in SAR (annual)
    "min_price": 10000,
    "max_price": 23000,
    "preferred_max_price": 20000,  # 22-23k is acceptable but not preferred
    "currency": "SAR",

    # Property types to search
    "property_types": ["studio", "1bhk", "1 bedroom"],
    "property_types_arabic": ["استوديو", "غرفة وصالة", "شقة استوديو"],

    # Furnished filter: "both", "furnished", "unfurnished"
    "furnished_filter": "both",
}

# Website configurations
SCRAPER_CONFIG = {
    "delay_min": 1.5,  # seconds between requests
    "delay_max": 3.5,
    "timeout": 20,
    "max_retries": 3,
    "max_pages_per_site": 10,
}

# Output configuration
OUTPUT_CONFIG = {
    "excel_filename": "riyadh_studio_rentals.xlsx",
    "csv_filename": "riyadh_studio_rentals.csv",
    "sheet_names": {
        "all": "All Listings",
        "malaz": "Malaz",
        "rabwah": "Rabwah",
        "sulaimaniyah": "Sulaimaniyah",
        "near_metro": "Near Metro",
    },
}

# HTTP headers to mimic a real browser
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

JSON_HEADERS = {
    **DEFAULT_HEADERS,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}
