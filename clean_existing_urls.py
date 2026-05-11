"""
clean_existing_urls.py — one-time cleanup
=====================================================================
Fixes existing rows in the Sheet that have double-slash URLs from the
first scraper run (before the URL normalization patch).

Cleans the `source_url` column in:
  - Announcements tab
  - Deals tab

Run once after applying the scraper patch:
    python3 clean_existing_urls.py

Then delete or archive this script — it's a one-shot.
"""

import os
import re
import json
import time
import gspread
from google.oauth2.service_account import Credentials


def clean_url(url):
    """Normalize URLs: collapse accidental double slashes in path."""
    if not url:
        return ""
    url = str(url).strip()
    m = re.match(r'^(https?://)(.*)$', url)
    if m:
        scheme, rest = m.group(1), m.group(2)
        rest = re.sub(r'/{2,}', '/', rest)
        return scheme + rest
    return url


def fix_tab(sheet, tab_name, url_col_name):
    """Find double-slash URLs in a tab's url column and fix them in place."""
    ws = sheet.worksheet(tab_name)
    all_values = ws.get_all_values()
    if not all_values:
        return 0
    headers = all_values[0]
    if url_col_name not in headers:
        print(f"  {tab_name}: column '{url_col_name}' not found, skipping")
        return 0
    col_idx = headers.index(url_col_name)
    col_letter = chr(ord('A') + col_idx)

    fixes = []
    for row_idx, row in enumerate(all_values[1:], start=2):
        if col_idx >= len(row):
            continue
        raw = row[col_idx]
        cleaned = clean_url(raw)
        if cleaned != raw:
            fixes.append((row_idx, raw, cleaned))

    if not fixes:
        print(f"  {tab_name}: no double-slash URLs found ({len(all_values)-1} rows checked)")
        return 0

    print(f"  {tab_name}: found {len(fixes)} rows to fix:")
    for row_idx, raw, cleaned in fixes[:5]:
        print(f"    Row {row_idx}: {raw[:60]}... → ...{cleaned[-40:]}")
    if len(fixes) > 5:
        print(f"    ... and {len(fixes) - 5} more")

    # Batch update
    updates = [
        {"range": f"{col_letter}{row_idx}", "values": [[cleaned]]}
        for row_idx, _, cleaned in fixes
    ]
    ws.batch_update(updates, value_input_option="RAW")
    time.sleep(1)
    print(f"  {tab_name}: ✓ fixed {len(fixes)} rows")
    return len(fixes)


def main():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"])

    print("Cleaning double-slash URLs in the Sheet...\n")
    total = 0
    total += fix_tab(sheet, "Announcements", "source_url")
    total += fix_tab(sheet, "Deals", "source_url")
    total += fix_tab(sheet, "Seen", "url")
    print(f"\n✓ Done. Fixed {total} URL(s) total.")


if __name__ == "__main__":
    main()
