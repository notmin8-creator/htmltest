"""
Export rental listings to Excel (and optionally Google Sheets).
"""

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, numbers
)
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

# Column order in the output sheet
COLUMNS = [
    ("source",        "Source"),
    ("area",          "Area"),
    ("title",         "Title / Description"),
    ("property_type", "Type"),
    ("price_sar",     "Annual Price (SAR)"),
    ("price_label",   "Price Label"),
    ("price_note",    "Price Note"),
    ("furnished",     "Furnished?"),
    ("bedrooms",      "Bedrooms"),
    ("bathrooms",     "Bathrooms"),
    ("size_sqm",      "Size (sqm)"),
    ("phone",         "Phone"),
    ("link",          "Listing Link"),
    ("description",   "Description Snippet"),
    ("scraped_at",    "Scraped At"),
]

AREA_LABELS = {
    "malaz":              "Al Malaz",
    "rabwah":             "Ar Rabwah",
    "sulaimaniyah":       "As Sulaimaniyah",
    "near_metro":         "Near Metro",
    "near_sulaimaniyah":  "Near Sulaimaniyah",
    "Unknown":            "Other / Unknown",
}

# Excel colours
HEADER_FILL   = "1F3864"   # dark navy
HEADER_FONT   = "FFFFFF"
ROW_ALT_FILL  = "EBF0FA"
PREFERRED_FILL = "C6EFCE"  # green  → price ≤ 20k
ACCEPTABLE_FILL = "FFEB9C" # yellow → 20k < price ≤ 23k
UNKNOWN_FILL   = "F2F2F2"

THIN = Side(style="thin", color="CCCCCC")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _col_width(key):
    widths = {
        "source": 18, "area": 16, "title": 45, "property_type": 12,
        "price_sar": 18, "price_label": 18, "price_note": 22,
        "furnished": 16, "bedrooms": 12, "bathrooms": 12, "size_sqm": 12,
        "phone": 18, "link": 50, "description": 40, "scraped_at": 18,
    }
    return widths.get(key, 15)


def _row_fill(price_note: str) -> str:
    if "preferred" in price_note.lower():
        return PREFERRED_FILL
    if "above preferred" in price_note.lower():
        return ACCEPTABLE_FILL
    return UNKNOWN_FILL


def deduplicate(listings):
    seen = set()
    unique = []
    for item in listings:
        key = (item.get("link") or "", item.get("title") or "", item.get("price_sar") or 0)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def to_dataframe(listings):
    if not listings:
        return pd.DataFrame(columns=[h for _, h in COLUMNS])

    rows = []
    for item in listings:
        row = {header: item.get(key, "N/A") for key, header in COLUMNS}
        rows.append(row)

    df = pd.DataFrame(rows)

    # Numeric price for sorting
    df["_price_sort"] = pd.to_numeric(
        df["Annual Price (SAR)"].replace({"Unknown": 0, "N/A": 0}), errors="coerce"
    ).fillna(0)

    df = df.sort_values(["Area", "_price_sort"]).drop(columns=["_price_sort"])
    df.reset_index(drop=True, inplace=True)
    return df


def _write_sheet(ws, df, title="All Listings"):
    headers = [h for _, h in COLUMNS]

    # Header row
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font      = Font(bold=True, color=HEADER_FONT, size=11)
        cell.fill      = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border    = BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = _col_width(
            next(k for k, h in COLUMNS if h == header)
        )

    ws.row_dimensions[1].height = 28

    # Data rows
    for row_idx, row in df.iterrows():
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx + 2, column=col_idx, value=str(row[header]))

            price_note = str(row.get("Price Note", ""))
            fill_color = _row_fill(price_note)
            cell.fill  = PatternFill("solid", fgColor=fill_color)
            cell.border = BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=(col_idx in (3, 13, 14)))

            # Make link column a hyperlink-style
            if header == "Listing Link":
                url = str(row[header])
                if url.startswith("http"):
                    cell.hyperlink = url
                    cell.style = "Hyperlink"

            # Right-align price
            if header == "Annual Price (SAR)":
                cell.alignment = Alignment(horizontal="right")

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def export_to_excel(listings, filename=None):
    if not filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"riyadh_studio_rentals_{ts}.xlsx"

    listings = deduplicate(listings)
    logger.info(f"Exporting {len(listings)} unique listings to {filename}…")

    df_all = to_dataframe(listings)

    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        # All listings sheet
        df_all.to_excel(writer, index=False, sheet_name="All Listings")

        # Per-area sheets
        area_col = "Area"
        if area_col in df_all.columns:
            for area_key, label in AREA_LABELS.items():
                area_df = df_all[
                    df_all[area_col].str.lower().str.contains(area_key.replace("_", " "), na=False)
                ]
                if not area_df.empty:
                    sheet = label[:31]
                    area_df.to_excel(writer, index=False, sheet_name=sheet)

        # Summary sheet
        _write_summary(writer, listings)

    # Post-process with openpyxl for rich formatting
    wb = load_workbook(filename)
    for ws in wb.worksheets:
        if ws.title == "Summary":
            continue
        # Rebuild header formatting (pandas drops it)
        for col_idx, (key, header) in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font      = Font(bold=True, color=HEADER_FONT, size=11)
            cell.fill      = PatternFill("solid", fgColor=HEADER_FILL)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border    = BORDER
            ws.column_dimensions[get_column_letter(col_idx)].width = _col_width(key)

        # Colour data rows
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
            price_note = ""
            for cell in row:
                if cell.column == next(i+1 for i, (k, _) in enumerate(COLUMNS) if k == "price_note"):
                    price_note = str(cell.value or "")
            fill_color = _row_fill(price_note)
            for cell in row:
                cell.fill   = PatternFill("solid", fgColor=fill_color)
                cell.border = BORDER
                if cell.column == next(i+1 for i, (k, _) in enumerate(COLUMNS) if k == "link"):
                    url = str(cell.value or "")
                    if url.startswith("http"):
                        cell.hyperlink = url
                        cell.font = Font(color="0563C1", underline="single")

        ws.freeze_panes = "A2"

    wb.save(filename)
    logger.info(f"Excel saved: {filename}")
    return filename


def _write_summary(writer, listings):
    from collections import Counter
    rows = []
    total = len(listings)
    area_counts = Counter(item.get("area", "Unknown") for item in listings)
    source_counts = Counter(item.get("source", "Unknown") for item in listings)
    furnished_counts = Counter(item.get("furnished", "Not specified") for item in listings)

    rows.append(["Riyadh Studio Rental Listings — Summary", ""])
    rows.append(["Generated at", datetime.now().strftime("%Y-%m-%d %H:%M")])
    rows.append(["Total unique listings", total])
    rows.append([""])
    rows.append(["--- By Area ---", ""])
    for area, count in area_counts.most_common():
        rows.append([AREA_LABELS.get(area, area), count])
    rows.append([""])
    rows.append(["--- By Source ---", ""])
    for source, count in source_counts.most_common():
        rows.append([source, count])
    rows.append([""])
    rows.append(["--- Furnished Status ---", ""])
    for status, count in furnished_counts.most_common():
        rows.append([status, count])

    df = pd.DataFrame(rows, columns=["Category", "Value"])
    df.to_excel(writer, index=False, sheet_name="Summary")


def export_to_csv(listings, filename=None):
    if not filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"riyadh_studio_rentals_{ts}.csv"
    listings = deduplicate(listings)
    df = to_dataframe(listings)
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    logger.info(f"CSV saved: {filename}")
    return filename
