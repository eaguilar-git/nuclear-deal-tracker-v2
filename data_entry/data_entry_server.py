"""
data_entry_server.py — local Flask server for the Nuclear Deal Tracker data entry form
=====================================================================================

Provides a tiny local API that the data_entry.html frontend talks to. Wraps the
Google Sheets service-account credentials so they never leave your machine.

Usage (in the repo dir, with env vars set):
    pip3 install flask flask-cors gspread google-auth openpyxl   # one-time
    python3 data_entry_server.py

Then open data_entry.html in your browser. The HTML file expects this server
to be running at http://localhost:8001.

The server exposes:
  GET  /api/tables                 → all 6 entity tables (live from Sheet)
  GET  /api/tables/<name>          → single table
  POST /api/push                   → batch apply pending changes to Sheet
  GET  /api/health                 → simple status check
  GET  /api/export                 → download all tables as a single .xlsx

All env vars match what the scraper uses:
    GOOGLE_SERVICE_ACCOUNT_JSON
    GOOGLE_SHEET_ID
"""

import os
import io
import json
import time
from datetime import datetime

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

import gspread
from google.oauth2.service_account import Credentials
from openpyxl import Workbook


# ─── Tab name → ordered column list ─────────────────────────────────────────
# Source of truth for what columns exist in each entity table.
# These must match the live Sheet exactly.

TABLE_SCHEMAS = {
    "Sites": [
        "site_id", "site_name", "state", "county", "latitude", "longitude",
        "operator", "owner", "nrc_region", "notes",
    ],
    "Reactor Units": [
        "unit_id", "site_id", "unit_name", "asset_status",
        "reactor_technology", "reactor_manufacturer", "reactor_class",
        "nameplate_mwe", "thermal_mwt",
        "commercial_operation_date", "original_license_expiration",
        "current_license_expiration", "nrc_docket", "notes",
    ],
    "Projects": [
        "project_id", "project_name", "project_type", "layer",
        "lead_developer", "project_stage", "project_status",
        "size_scale_mw", "size_scale_tier",
        "project_cost_usd", "project_cost_source", "project_cost_as_of",
        "target_operation_date",
        "nrc_application_type", "nrc_application_status",
        "linked_unit_ids", "context_ids", "notes",
    ],
    "Deals": [
        "deal_id", "confirmation_status", "deal_name",
        "project_ids", "context_ids", "deal_type", "deal_stage",
        "economic_type", "capital_value_usd", "capital_value_disclosure",
        "cost_contribution_usd", "is_portfolio_deal", "allocations",
        "term_years", "lead_entity", "lead_entity_type",
        "partners", "technology_provider", "state", "region",
        "capacity_at_stake_mw", "cost_recovery", "government_support",
        "announcement_date", "close_date", "source_url", "notes",
    ],
    "Context Items": [
        "context_id", "context_name", "context_type", "scope", "state",
        "lead_entity", "partners",
        "start_date", "end_date", "status",
        "headline_value_usd", "target_capacity_mw",
        "relevant_layers", "promoted_to_project_id", "source_url", "notes",
    ],
    "Announcements": [
        "announcement_id", "headline", "source", "source_url",
        "published_date", "captured_date",
        "site_ids", "unit_ids", "project_ids", "deal_ids", "context_ids",
        "announcement_scope", "new_entity_flags", "confidence",
        "summary", "raw_body", "notes",
    ],
}

# ID column for each table (used for finding rows on edit)
ID_COL = {
    "Sites": "site_id",
    "Reactor Units": "unit_id",
    "Projects": "project_id",
    "Deals": "deal_id",
    "Context Items": "context_id",
    "Announcements": "announcement_id",
}


# ─── Controlled vocabularies (for dropdowns in the UI) ──────────────────────
# Mirrors what the scraper accepts. Values reflect actual data in the live Sheet
# as of the v0.4 schema lock. Edit these as schema evolves.

CONTROLLED_VOCABS = {
    "asset_status": ["Operating", "Planned", "Shut Down", "Under Construction", "Decommissioning"],
    "project_type": [
        "Extension / Renewal", "New Build — Advanced/SMR",
        "New Build — Large", "Restart", "Uprate",
    ],
    "layer": ["Layer 1", "Layer 2", "Layer 3", "Layer 4a", "Layer 4b"],
    "project_stage": [
        "Announcement", "Pre-application / Planning",
        "Permitting / Licensing", "Permitted / Licensed",
        "Construction", "Operation", "Decommissioning",
    ],
    "project_status": ["Active", "Completed", "Paused", "Cancelled"],
    "deal_type": [
        "PPA", "MOU", "LOI", "Joint Development Agreement",
        "Loan", "Loan Guarantee", "Equity Investment", "Grant",
        "Construction Contract", "Service Contract", "EPC",
        "Subsidy/Credit", "Off-take Agreement", "Master Power Agreement",
        "Funding Agreement", "License Action", "Strategic Partnership",
    ],
    "deal_stage": ["Announced", "MOU", "LOI", "FID", "Closed", "Withdrawn"],
    "economic_type": [
        "Grant", "Equity", "Debt", "Refinancing",
        "Subsidy/Credit Program", "Revenue Contract",
        "Service Contract", "Partnership",
    ],
    "capital_value_disclosure": ["Disclosed", "Estimated", "Undisclosed"],
    "lead_entity_type": [
        "Government", "Hyperscaler", "Utility", "Reactor Vendor",
        "Investor", "Industrial", "Fuel Supplier",
    ],
    "context_type": [
        "Federal Program", "Federal Policy", "State Policy", "State Program",
        "Hyperscaler Portfolio", "Vendor/Corporate",
        "Aspirational Pipeline", "Industry Framework",
    ],
    "announcement_scope": [
        "Project-Specific", "Context-Specific",
        "Cross-Cutting", "Industry Commentary",
    ],
    "confidence": ["High", "Medium", "Low"],
    "confirmation_status": ["Confirmed", "Proposed (scraper)", "Proposed (manual)", "Disputed"],

    # ── New dropdowns added based on actual live-Sheet values ──
    "nrc_region": ["Region I", "Region II", "Region III", "Region IV"],
    "reactor_class": ["Large LWR", "SMR", "Microreactor", "Demonstrator", "Advanced"],
    "size_scale_tier": [
        "Large (>1,000)", "Mid (300–1,000)", "SMR-scale (50–300)", "Micro (<50)",
    ],
    "nrc_application_status": [
        "Approved", "Under Review", "Filed", "Pre-application", "Withdrawn", "N/A",
    ],
    "scope": ["National", "State", "Multi-state", "Bilateral", "Vendor-specific"],
    "status": ["Active", "Completed", "Proposed", "Cancelled"],
    "cost_recovery": ["Commercial PPA", "Rate Payer", "Mixed"],
    "government_support": [
        "DOE Cost-Share", "Federal Loan", "Loan Guarantee",
        "USDA Loan", "Federal Subsidy/Credit", "EXIM Financing",
    ],
    "is_portfolio_deal": ["TRUE", "FALSE"],
    "state": [
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC",
    ],
}


# ─── Flask app ──────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)  # allow data_entry.html (opened locally) to talk to us


def get_sheet():
    """Authenticate and return the live Google Sheet handle."""
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(os.environ["GOOGLE_SHEET_ID"])


def fetch_table(sheet, tab_name):
    """Read all rows from a tab as list of dicts (key = column name)."""
    ws = sheet.worksheet(tab_name)
    rows = ws.get_all_values()
    if not rows:
        return []
    headers = rows[0]
    out = []
    for row in rows[1:]:
        d = {}
        for i, h in enumerate(headers):
            d[h] = row[i] if i < len(row) else ""
        out.append(d)
    return out


# ─── API routes ─────────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    try:
        sheet = get_sheet()
        # quick sanity check — fetch first tab title
        title = sheet.worksheets()[0].title
        return jsonify({
            "ok": True,
            "sheet_id": os.environ.get("GOOGLE_SHEET_ID", ""),
            "first_tab": title,
            "time": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/tables", methods=["GET"])
def all_tables():
    """Return all 6 entity tables plus the schemas and vocabularies."""
    try:
        sheet = get_sheet()
        data = {}
        for tab_name, cols in TABLE_SCHEMAS.items():
            try:
                rows = fetch_table(sheet, tab_name)
                data[tab_name] = rows
            except gspread.exceptions.WorksheetNotFound:
                data[tab_name] = []
        return jsonify({
            "tables": data,
            "schemas": TABLE_SCHEMAS,
            "id_cols": ID_COL,
            "vocabularies": CONTROLLED_VOCABS,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tables/<tab_name>", methods=["GET"])
def one_table(tab_name):
    """Return a single table."""
    if tab_name not in TABLE_SCHEMAS:
        return jsonify({"error": f"Unknown table: {tab_name}"}), 404
    try:
        sheet = get_sheet()
        rows = fetch_table(sheet, tab_name)
        return jsonify({"rows": rows, "schema": TABLE_SCHEMAS[tab_name]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/push", methods=["POST"])
def push_changes():
    """Apply a batch of pending changes to the live Sheet.

    Request body:
    {
      "changes": [
        {"table": "Deals", "op": "add",  "row": {...}},
        {"table": "Sites", "op": "edit", "id": "vogtle", "row": {...}},
        ...
      ]
    }
    Returns a summary of what was applied and any errors.
    """
    try:
        data = request.get_json(force=True)
        changes = data.get("changes", [])
        if not changes:
            return jsonify({"ok": True, "applied": 0, "errors": [], "results": []})

        sheet = get_sheet()
        results = []
        errors = []

        # Group by table to minimize Sheet API calls
        for change in changes:
            tab_name = change.get("table")
            op = change.get("op")
            row = change.get("row", {})
            if tab_name not in TABLE_SCHEMAS:
                errors.append({"change": change, "error": f"Unknown table: {tab_name}"})
                results.append({"ok": False, "change": change})
                continue
            try:
                ws = sheet.worksheet(tab_name)
                cols = TABLE_SCHEMAS[tab_name]

                if op == "add":
                    # Build row in column order
                    row_values = [str(row.get(c, "")) for c in cols]
                    ws.append_row(row_values, value_input_option="USER_ENTERED")
                    results.append({"ok": True, "change": change})

                elif op == "edit":
                    # Find existing row by ID
                    id_col_name = ID_COL[tab_name]
                    target_id = change.get("id") or row.get(id_col_name)
                    if not target_id:
                        raise ValueError(f"No ID provided for edit in {tab_name}")
                    all_values = ws.get_all_values()
                    if not all_values:
                        raise ValueError(f"{tab_name} is empty")
                    headers = all_values[0]
                    id_col_idx = headers.index(id_col_name)
                    row_num = None
                    for i, r in enumerate(all_values[1:], start=2):
                        if i - 1 < len(all_values) - 1 and id_col_idx < len(r) and r[id_col_idx] == target_id:
                            row_num = i
                            break
                    if row_num is None:
                        raise ValueError(f"Row {target_id} not found in {tab_name}")
                    # Update row in place
                    row_values = [str(row.get(c, "")) for c in cols]
                    # Compute the A1 range like A5:Z5
                    end_col_letter = _col_letter(len(cols))
                    range_str = f"A{row_num}:{end_col_letter}{row_num}"
                    ws.update(values=[row_values], range_name=range_str, value_input_option="USER_ENTERED")
                    results.append({"ok": True, "change": change})

                else:
                    errors.append({"change": change, "error": f"Unsupported op: {op}"})
                    results.append({"ok": False, "change": change})
                    continue

                time.sleep(0.4)  # Sheets API rate limit
            except Exception as e:
                errors.append({"change": change, "error": str(e)})
                results.append({"ok": False, "change": change})

        return jsonify({
            "ok": len(errors) == 0,
            "applied": sum(1 for r in results if r["ok"]),
            "errors": errors,
            "results": results,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export", methods=["GET"])
def export_xlsx():
    """Export all 6 entity tables as a single .xlsx file."""
    try:
        sheet = get_sheet()
        wb = Workbook()
        wb.remove(wb.active)  # drop default sheet
        for tab_name, cols in TABLE_SCHEMAS.items():
            try:
                rows = fetch_table(sheet, tab_name)
            except gspread.exceptions.WorksheetNotFound:
                continue
            # Excel-safe tab name: ≤31 chars
            safe_name = tab_name[:31]
            ws = wb.create_sheet(safe_name)
            ws.append(cols)  # header
            for r in rows:
                ws.append([r.get(c, "") for c in cols])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"nuclear_deal_tracker_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx",
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _col_letter(n):
    """1 → 'A', 26 → 'Z', 27 → 'AA'."""
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


# ─── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Sanity check env vars
    missing = [k for k in ("GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_SHEET_ID") if k not in os.environ]
    if missing:
        print(f"ERROR: missing env vars: {', '.join(missing)}")
        print("Set them with:")
        print('  export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat ~/Documents/credentials_deal_tracker/rugged-abacus-405804-effe0cb0fe9b.json)"')
        print('  export GOOGLE_SHEET_ID="1UHKrpeS56Bgt5ZQ2si6i9LunogM88V4VDKZ93PoqTeg"')
        exit(1)

    print("=" * 70)
    print("Nuclear Deal Tracker — Data Entry Server")
    print("=" * 70)
    print(f"Sheet ID:   {os.environ['GOOGLE_SHEET_ID']}")
    print(f"Listening:  http://localhost:8001")
    print(f"Open:       data_entry.html (in this same directory) in your browser")
    print("=" * 70)
    print()
    app.run(host="127.0.0.1", port=8001, debug=False)
