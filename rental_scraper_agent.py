"""
Riyadh Rental Scraper Agent
============================
Scrapes multiple Saudi real-estate websites for studio apartments in:
  • Al Malaz (الملز)
  • Ar Rabwah (الربوة)
  • As Sulaimaniyah (السليمانية) + nearby / near metro

Price range: 10,000 – 23,000 SAR/year  (preferred ≤ 20,000)
Output:      Excel workbook  (+ optional CSV)

Usage:
    python rental_scraper_agent.py [--csv] [--output <filename>]
"""

import sys
import time
import logging
import argparse
from datetime import datetime

from scrapers import (
    BayutScraper,
    AqarScraper,
    HarajScraper,
    WasaltScraper,
    OpenSooqScraper,
    PropertyFinderScraper,
    close_browser,
)
from exporter import export_to_excel, export_to_csv, deduplicate

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scraper.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #
class RentalScraperAgent:
    """
    Orchestrates multiple site scrapers and aggregates results.
    """

    SCRAPERS = [
        ("Bayut.sa",        BayutScraper),
        ("Aqar.fm",         AqarScraper),
        ("Haraj.com.sa",    HarajScraper),
        ("Wasalt.com",      WasaltScraper),
        ("OpenSooq",        OpenSooqScraper),
        ("PropertyFinder",  PropertyFinderScraper),
    ]

    def __init__(self):
        self.all_listings = []
        self.stats = {}

    def run(self, output_filename=None, also_csv=False):
        logger.info("=" * 65)
        logger.info("  Riyadh Studio Rental Scraper Agent — starting")
        logger.info("  Target areas : Malaz · Rabwah · Sulaimaniyah · Near Metro")
        logger.info("  Price range  : 10,000 – 23,000 SAR/year")
        logger.info("=" * 65)

        start = time.time()

        for name, ScraperClass in self.SCRAPERS:
            logger.info(f"\n▶ Running {name} scraper…")
            t0 = time.time()
            try:
                scraper  = ScraperClass()
                listings = scraper.scrape()
                count    = len(listings)
                self.all_listings.extend(listings)
                self.stats[name] = count
                logger.info(f"  ✓ {name}: {count} listings  ({time.time()-t0:.1f}s)")
            except Exception as exc:
                logger.error(f"  ✗ {name} failed: {exc}", exc_info=True)
                self.stats[name] = 0

        elapsed = time.time() - start
        unique  = deduplicate(self.all_listings)

        logger.info("\n" + "=" * 65)
        logger.info(f"  Total raw listings  : {len(self.all_listings)}")
        logger.info(f"  After deduplication : {len(unique)}")
        logger.info(f"  Elapsed time        : {elapsed:.1f}s")
        logger.info("=" * 65)

        # Per-site breakdown
        logger.info("\n  Listings per site:")
        for site, cnt in self.stats.items():
            logger.info(f"    {site:<22} {cnt:>4}")

        close_browser()

        # Export
        excel_file = export_to_excel(unique, output_filename)
        logger.info(f"\n  Excel saved  → {excel_file}")

        if also_csv:
            csv_file = export_to_csv(unique)
            logger.info(f"  CSV saved    → {csv_file}")

        logger.info("\n  Done!  Open the Excel file to browse all listings.")
        return excel_file, unique


# --------------------------------------------------------------------------- #
# CLI entry-point
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description="Scrape Riyadh studio rental listings from multiple websites."
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILENAME",
        default=None,
        help="Output Excel filename (default: riyadh_studio_rentals_<timestamp>.xlsx)",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Also export a CSV file alongside the Excel workbook",
    )
    args = parser.parse_args()

    agent = RentalScraperAgent()
    excel_file, listings = agent.run(
        output_filename=args.output,
        also_csv=args.csv,
    )

    print(f"\n{'='*55}")
    print(f"  Scraping complete!")
    print(f"  {len(listings)} unique listings found.")
    print(f"  Results: {excel_file}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
