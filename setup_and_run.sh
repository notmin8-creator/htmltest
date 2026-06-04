#!/usr/bin/env bash
# ============================================================
# Setup and run the Riyadh Rental Scraper Agent
# ============================================================
set -e

echo "===================================================="
echo "  Riyadh Studio Rental Scraper — Setup"
echo "===================================================="

# 1. Install dependencies
echo ""
echo "[1/3] Installing Python dependencies…"
pip install -q -r requirements.txt

# 2. Run the scraper
echo ""
echo "[2/3] Running scraper (this may take 5-10 minutes)…"
python rental_scraper_agent.py --csv

# 3. Show output files
echo ""
echo "[3/3] Output files:"
ls -lh riyadh_studio_rentals_*.xlsx 2>/dev/null || true
ls -lh riyadh_studio_rentals_*.csv  2>/dev/null || true

echo ""
echo "Done!  Open the .xlsx file in Excel or Google Sheets."
echo "===================================================="
