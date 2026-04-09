"""
Sync Sparkplug data to external targets:
  - Local CSV files
  - Google Sheets (via gspread)
  - HubSpot CRM (via hubspot-api-client)
"""

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from client import SparkplugClient


# ─── CSV Export ───────────────────────────────────────────────────────────────

def export_retailers_csv(client: SparkplugClient, output_path: str) -> int:
    """Export all retailers to CSV. Returns row count."""
    retailers = client.get_retailers()
    fieldnames = ["id", "name", "markets", "status", "account_status", "share_sales_data", "created_at"]
    rows = [
        {
            "id": r.get("accountId"),
            "name": r.get("accountName"),
            "markets": ",".join(r.get("markets", [])),
            "status": r.get("status"),
            "account_status": r.get("accountStatus"),
            "share_sales_data": r.get("shareSalesData"),
            "created_at": r.get("createdAt"),
        }
        for r in retailers
    ]
    _write_csv(output_path, fieldnames, rows)
    return len(rows)


def export_sales_csv(
    client: SparkplugClient,
    retailer_id: str,
    retailer_name: str,
    date_start: str,
    date_end: str,
    output_path: str,
    frequency: str = "monthly",
) -> int:
    """Export time-series sales buckets to CSV."""
    data = client.get_sales_buckets(retailer_id, date_start, date_end, frequency)
    rows_raw = data.get("rows", []) if isinstance(data, dict) else []
    if not rows_raw:
        rows_raw = [data] if isinstance(data, dict) else []

    rows = []
    for r in rows_raw:
        row = dict(r)
        row["retailer_id"] = retailer_id
        row["retailer_name"] = retailer_name
        row["exported_at"] = datetime.now(timezone.utc).isoformat()
        rows.append(row)

    fieldnames = list(rows[0].keys()) if rows else ["retailer_id", "retailer_name", "exported_at"]
    _write_csv(output_path, fieldnames, rows)
    return len(rows)


def export_budtender_csv(
    client: SparkplugClient,
    retailer_id: str,
    retailer_name: str,
    date_start: str,
    date_end: str,
    output_path: str,
    frequency: str = "monthly",
) -> int:
    """Export per-budtender performance to CSV."""
    data = client.get_budtender_performance(retailer_id, date_start, date_end, frequency)
    if isinstance(data, dict):
        rows = [
            {
                "retailer_id": retailer_id,
                "retailer_name": retailer_name,
                "employee_id": emp_id,
                "units_sold": units,
                "date_start": date_start,
                "date_end": date_end,
                "exported_at": datetime.now(timezone.utc).isoformat(),
            }
            for emp_id, units in data.items()
        ]
    elif isinstance(data, list):
        rows = [
            {**item, "retailer_id": retailer_id, "retailer_name": retailer_name,
             "exported_at": datetime.now(timezone.utc).isoformat()}
            for item in data
        ]
    else:
        rows = []
    fieldnames = ["retailer_id", "retailer_name", "employee_id", "units_sold", "date_start", "date_end", "exported_at"]
    _write_csv(output_path, fieldnames, rows)
    return len(rows)


def _write_csv(path: str, fieldnames: list, rows: list):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ─── Google Sheets Sync ───────────────────────────────────────────────────────

def sync_retailers_to_sheets(
    client: SparkplugClient,
    spreadsheet_id: str,
    worksheet_name: str = "Sparkplug Retailers",
    credentials_path: str = None,
) -> int:
    """
    Sync retailer list to a Google Sheet tab.

    Requires:
      pip install gspread google-auth
      A service account JSON at credentials_path (or GOOGLE_CREDENTIALS_PATH env var).
    """
    import gspread
    from google.oauth2.service_account import Credentials

    creds_path = credentials_path or os.environ.get("GOOGLE_CREDENTIALS_PATH")
    if not creds_path:
        raise RuntimeError("Set GOOGLE_CREDENTIALS_PATH to your service account JSON path.")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    gc = gspread.authorize(creds)

    retailers = client.get_retailers()
    headers = ["ID", "Name", "Markets", "Status", "Account Status", "Shares Sales Data", "Created At", "Last Synced"]
    rows = [
        [
            r.get("accountId", ""),
            r.get("accountName", ""),
            ", ".join(r.get("markets", [])),
            r.get("status", ""),
            r.get("accountStatus", ""),
            str(r.get("shareSalesData", "")),
            r.get("createdAt", ""),
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        ]
        for r in retailers
    ]

    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(worksheet_name, rows=100, cols=20)

    ws.clear()
    ws.update([headers] + rows)
    return len(rows)


def sync_sales_to_sheets(
    client: SparkplugClient,
    retailer_id: str,
    retailer_name: str,
    date_start: str,
    date_end: str,
    spreadsheet_id: str,
    worksheet_name: str = "Sparkplug Sales",
    credentials_path: str = None,
    frequency: str = "monthly",
) -> int:
    """Sync sales time-series data to a Google Sheet tab."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds_path = credentials_path or os.environ.get("GOOGLE_CREDENTIALS_PATH")
    if not creds_path:
        raise RuntimeError("Set GOOGLE_CREDENTIALS_PATH to your service account JSON path.")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    gc = gspread.authorize(creds)

    data = client.get_sales_buckets(retailer_id, date_start, date_end, frequency)
    rows_raw = data.get("rows", []) if isinstance(data, dict) else []

    if not rows_raw:
        return 0

    headers = ["Retailer", "Date", "Units Sold", "Last Synced"]
    rows = []
    for r in rows_raw:
        rows.append([
            retailer_name,
            r.get("key", r.get("date", "")),
            r.get("value", ""),
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        ])

    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(worksheet_name, rows=500, cols=10)

    ws.clear()
    ws.update([headers] + rows)
    return len(rows)


# ─── HubSpot Sync ─────────────────────────────────────────────────────────────

def sync_retailers_to_hubspot(
    client: SparkplugClient,
    hubspot_token: str = None,
) -> dict:
    """
    Upsert Sparkplug retailers as HubSpot Companies.

    Requires:
      pip install hubspot-api-client
      hubspot_token or HUBSPOT_ACCESS_TOKEN env var.
    """
    from hubspot import HubSpot
    from hubspot.crm.companies import SimplePublicObjectInputForCreate

    token = hubspot_token or os.environ.get("HUBSPOT_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("Set HUBSPOT_ACCESS_TOKEN env var or pass hubspot_token.")

    hs = HubSpot(access_token=token)
    retailers = client.get_retailers()

    created = 0
    updated = 0
    errors = []

    for r in retailers:
        name = r.get("accountName", "")
        ext_id = r.get("accountId", "")
        markets = ", ".join(r.get("markets", []))

        properties = {
            "name": name,
            "sparkplug_account_id": ext_id,
            "sparkplug_markets": markets,
            "sparkplug_status": r.get("status", ""),
            "sparkplug_shares_sales_data": str(r.get("shareSalesData", False)).lower(),
            "sparkplug_last_synced": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # Search for existing company by sparkplug ID
            search_resp = hs.crm.companies.search_api.do_search(
                public_object_search_request={
                    "filterGroups": [{
                        "filters": [{
                            "propertyName": "sparkplug_account_id",
                            "operator": "EQ",
                            "value": ext_id,
                        }]
                    }],
                    "properties": ["name", "sparkplug_account_id"],
                    "limit": 1,
                }
            )

            if search_resp.total > 0:
                company_id = search_resp.results[0].id
                hs.crm.companies.basic_api.update(company_id, simple_public_object_input={"properties": properties})
                updated += 1
            else:
                hs.crm.companies.basic_api.create(
                    simple_public_object_input_for_create=SimplePublicObjectInputForCreate(properties=properties)
                )
                created += 1

        except Exception as e:
            errors.append({"name": name, "error": str(e)})

    return {"created": created, "updated": updated, "errors": errors}
