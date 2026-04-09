#!/usr/bin/env python3
"""
Sparkplug MCP Server — Atomic Fungi
Exposes Sparkplug data (sales, budtenders, retailers, Snaps) as MCP tools.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure local modules are importable
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from client import SparkplugClient
import sync as sp_sync

# ─── Server init ─────────────────────────────────────────────────────────────

server = Server("sparkplug")
client = SparkplugClient()


# ─── Tool definitions ─────────────────────────────────────────────────────────

TOOLS = [
    types.Tool(
        name="sparkplug_get_retailers",
        description="List all retail partners connected to Atomic Fungi in Sparkplug, including their markets, status, and whether they share sales data.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    types.Tool(
        name="sparkplug_get_sales",
        description="Get Atomic Fungi's total units sold at a specific retailer over a date range. Returns a summary row with total units.",
        inputSchema={
            "type": "object",
            "properties": {
                "retailer_id": {"type": "string", "description": "Retailer account ID (get from sparkplug_get_retailers)"},
                "date_start": {"type": "string", "description": "Start date YYYY-MM-DD"},
                "date_end": {"type": "string", "description": "End date YYYY-MM-DD"},
                "frequency": {
                    "type": "string",
                    "enum": ["hourly", "daily", "weekly", "monthly", "yearly"],
                    "description": "Aggregation frequency (default: monthly)",
                    "default": "monthly",
                },
            },
            "required": ["retailer_id", "date_start", "date_end"],
        },
    ),
    types.Tool(
        name="sparkplug_get_sales_trend",
        description="Get time-series sales buckets (units sold over time) for Atomic Fungi products at a retailer. Good for trend charts.",
        inputSchema={
            "type": "object",
            "properties": {
                "retailer_id": {"type": "string"},
                "date_start": {"type": "string", "description": "YYYY-MM-DD"},
                "date_end": {"type": "string", "description": "YYYY-MM-DD"},
                "frequency": {"type": "string", "enum": ["daily", "weekly", "monthly"], "default": "monthly"},
            },
            "required": ["retailer_id", "date_start", "date_end"],
        },
    ),
    types.Tool(
        name="sparkplug_get_budtender_performance",
        description="Get per-budtender unit sales for Atomic Fungi products at a retailer. Returns a map of employee_id → units sold.",
        inputSchema={
            "type": "object",
            "properties": {
                "retailer_id": {"type": "string"},
                "date_start": {"type": "string", "description": "YYYY-MM-DD"},
                "date_end": {"type": "string", "description": "YYYY-MM-DD"},
                "frequency": {"type": "string", "enum": ["daily", "weekly", "monthly", "yearly"], "default": "monthly"},
            },
            "required": ["retailer_id", "date_start", "date_end"],
        },
    ),
    types.Tool(
        name="sparkplug_get_products_with_sales",
        description="Get the list of Atomic Fungi product IDs that recorded at least one sale at a retailer in the date range.",
        inputSchema={
            "type": "object",
            "properties": {
                "retailer_id": {"type": "string"},
                "date_start": {"type": "string", "description": "YYYY-MM-DD"},
                "date_end": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["retailer_id", "date_start", "date_end"],
        },
    ),
    types.Tool(
        name="sparkplug_get_snaps",
        description="List Snaps (brand content posts) published by Atomic Fungi on Sparkplug. Optionally filter to featured Snaps only.",
        inputSchema={
            "type": "object",
            "properties": {
                "featured_only": {"type": "boolean", "description": "Only return featured Snaps (default: true)", "default": True},
            },
            "required": [],
        },
    ),
    types.Tool(
        name="sparkplug_get_reach",
        description="Get Atomic Fungi's Snap reach and engagement breakdown — how many budtenders have been reached.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    types.Tool(
        name="sparkplug_get_brands",
        description="Get the Sparkplug brand sub-brands configured under the Atomic Fungi account.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    types.Tool(
        name="sparkplug_export_csv",
        description="Export Sparkplug data (retailers, sales trend, or budtender performance) to a local CSV file.",
        inputSchema={
            "type": "object",
            "properties": {
                "data_type": {
                    "type": "string",
                    "enum": ["retailers", "sales_trend", "budtender_performance"],
                    "description": "What data to export",
                },
                "retailer_id": {"type": "string", "description": "Required for sales_trend and budtender_performance"},
                "retailer_name": {"type": "string", "description": "Retailer name for labeling rows"},
                "date_start": {"type": "string", "description": "YYYY-MM-DD"},
                "date_end": {"type": "string", "description": "YYYY-MM-DD"},
                "output_path": {
                    "type": "string",
                    "description": "Full path where CSV will be saved (default: ~/Desktop/sparkplug_<type>_<date>.csv)",
                },
            },
            "required": ["data_type"],
        },
    ),
    types.Tool(
        name="sparkplug_sync_to_sheets",
        description=(
            "Sync Sparkplug retailer or sales data into a Google Sheet. "
            "Requires GOOGLE_CREDENTIALS_PATH env var pointing to a service account JSON."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string", "description": "Google Sheets ID (from the URL)"},
                "data_type": {"type": "string", "enum": ["retailers", "sales_trend"], "default": "retailers"},
                "worksheet_name": {"type": "string", "description": "Tab name to write to"},
                "retailer_id": {"type": "string"},
                "retailer_name": {"type": "string"},
                "date_start": {"type": "string"},
                "date_end": {"type": "string"},
                "frequency": {"type": "string", "enum": ["daily", "weekly", "monthly"], "default": "monthly"},
            },
            "required": ["spreadsheet_id"],
        },
    ),
    types.Tool(
        name="sparkplug_sync_to_hubspot",
        description=(
            "Upsert all Sparkplug retailers as Companies in HubSpot. "
            "Requires HUBSPOT_ACCESS_TOKEN env var."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    types.Tool(
        name="sparkplug_list_snaps",
        description=(
            "List all Snaps published by Atomic Fungi on Sparkplug, including their "
            "storifymeSnapId (needed for engagement export), name, markets, and page count."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    types.Tool(
        name="sparkplug_get_snap_engagement",
        description=(
            "Fetch per-employee engagement rows for a specific Snap — who viewed it, "
            "what actions they took (Story Started, Story Progress, etc.), which retailer "
            "and location they're at, and slide-level detail. "
            "Use sparkplug_list_snaps first to get the storifymeSnapId."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "storiyme_snap_id": {
                    "type": "string",
                    "description": "Numeric Snap ID from storifymeSnapId field (e.g. '407108')",
                },
                "snap_name": {
                    "type": "string",
                    "description": "Optional: human-readable name for labeling output",
                },
            },
            "required": ["storiyme_snap_id"],
        },
    ),
    types.Tool(
        name="sparkplug_export_all_snap_analytics",
        description=(
            "Export engagement analytics for ALL Snaps to a single CSV file — "
            "one row per employee engagement event across every published Snap. "
            "Columns: snap_name, snap_id, Employee, Retailer, Location, Action, Slide, Total Slides."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "output_path": {
                    "type": "string",
                    "description": "Where to save the CSV (default: ~/Desktop/sparkplug_snap_analytics_<date>.csv)",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="sparkplug_setup_check",
        description="Check whether Sparkplug authentication is configured and test API connectivity.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
]


@server.list_tools()
async def list_tools():
    return TOOLS


# ─── Tool handler ─────────────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        result = await _dispatch(name, arguments)
        return [types.TextContent(type="text", text=result)]
    except Exception as exc:
        return [types.TextContent(type="text", text=f"❌ Error: {exc}")]


async def _dispatch(name: str, args: dict) -> str:
    # ── Auth check ──────────────────────────────────────────────────────────
    if name == "sparkplug_setup_check":
        try:
            config_path = client.config_path
            exists = config_path.exists()
            token_ok = bool(client.token)
            retailers = client.get_retailers()
            return json.dumps({
                "config_file_exists": exists,
                "token_valid": token_ok,
                "retailers_found": len(retailers),
                "first_retailer": retailers[0].get("accountName") if retailers else None,
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e), "hint": "Run /sparkplug-setup to authenticate."}, indent=2)

    # ── Retailers ────────────────────────────────────────────────────────────
    elif name == "sparkplug_get_retailers":
        retailers = client.get_retailers()
        formatted = [
            {
                "id": r.get("accountId"),
                "name": r.get("accountName"),
                "markets": r.get("markets", []),
                "status": r.get("status"),
                "account_status": r.get("accountStatus"),
                "shares_sales_data": r.get("shareSalesData"),
                "created_at": r.get("createdAt"),
            }
            for r in retailers
        ]
        return json.dumps(formatted, indent=2)

    # ── Sales totals ─────────────────────────────────────────────────────────
    elif name == "sparkplug_get_sales":
        data = client.get_sales_totals(
            args["retailer_id"],
            args["date_start"],
            args["date_end"],
            args.get("frequency", "monthly"),
        )
        return json.dumps(data, indent=2)

    # ── Sales trend (buckets) ────────────────────────────────────────────────
    elif name == "sparkplug_get_sales_trend":
        data = client.get_sales_buckets(
            args["retailer_id"],
            args["date_start"],
            args["date_end"],
            args.get("frequency", "monthly"),
        )
        return json.dumps(data, indent=2)

    # ── Budtender performance ────────────────────────────────────────────────
    elif name == "sparkplug_get_budtender_performance":
        data = client.get_budtender_performance(
            args["retailer_id"],
            args["date_start"],
            args["date_end"],
            args.get("frequency", "monthly"),
        )
        # Format as list for readability
        formatted = [{"employee_id": k, "units_sold": v} for k, v in (data.items() if isinstance(data, dict) else {})]
        formatted.sort(key=lambda x: x["units_sold"], reverse=True)
        return json.dumps(formatted, indent=2)

    # ── Products with sales ──────────────────────────────────────────────────
    elif name == "sparkplug_get_products_with_sales":
        products = client.get_products_with_sales(
            args["retailer_id"], args["date_start"], args["date_end"]
        )
        return json.dumps({"products_with_sales": products, "count": len(products)}, indent=2)

    # ── Snap list ────────────────────────────────────────────────────────────
    elif name == "sparkplug_list_snaps":
        snaps = client.get_snaps_list()
        formatted = [
            {
                "snap_id": s.get("storifymeSnapId"),
                "mongo_id": s.get("_id"),
                "name": s.get("name"),
                "markets": s.get("markets", []),
                "total_pages": s.get("totalPages"),
                "thumbnail": s.get("thumbnailUrl"),
                "created_at": s.get("createdAt"),
            }
            for s in snaps
        ]
        return json.dumps(formatted, indent=2)

    # ── Snap engagement (per-snap) ────────────────────────────────────────────
    elif name == "sparkplug_get_snap_engagement":
        snap_id = args["storiyme_snap_id"]
        snap_name = args.get("snap_name", snap_id)
        rows = client.get_snap_engagement(snap_id)
        summary = {
            "snap_id": snap_id,
            "snap_name": snap_name,
            "total_engagement_events": len(rows),
            "unique_employees": len({r.get("Employee") for r in rows if r.get("Employee")}),
            "unique_retailers": len({r.get("Retailer") for r in rows if r.get("Retailer")}),
            "actions": {},
            "sample_rows": rows[:5],
        }
        for r in rows:
            action = r.get("Action", "unknown")
            summary["actions"][action] = summary["actions"].get(action, 0) + 1
        return json.dumps(summary, indent=2)

    # ── Export ALL snap analytics to CSV ─────────────────────────────────────
    elif name == "sparkplug_export_all_snap_analytics":
        from pathlib import Path
        import csv as csv_mod

        ts = datetime.now().strftime("%Y%m%d")
        default_path = str(Path.home() / "Desktop" / f"sparkplug_snap_analytics_{ts}.csv")
        output_path = args.get("output_path", default_path)

        snaps = client.get_snaps_list()
        all_rows = []
        for snap in snaps:
            snap_id = snap.get("storifymeSnapId")
            snap_name = snap.get("name", str(snap_id))
            if not snap_id:
                continue
            try:
                rows = client.get_snap_engagement(str(snap_id))
                for r in rows:
                    row = {
                        "snap_name": snap_name,
                        "snap_id": snap_id,
                        "Employee": r.get("Employee", ""),
                        "Retailer": r.get("Retailer", ""),
                        "Location": r.get("Location", ""),
                        "Action": r.get("Action", ""),
                        "Slide": r.get("Slide", ""),
                        "Total Slides": r.get("Total Slides", ""),
                        "Component Id": r.get("Component Id", ""),
                    }
                    all_rows.append(row)
            except Exception:
                pass  # Skip snaps with no engagement data

        if all_rows:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            fieldnames = ["snap_name", "snap_id", "Employee", "Retailer", "Location", "Action", "Slide", "Total Slides", "Component Id"]
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv_mod.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(all_rows)

        return json.dumps({
            "snaps_processed": len(snaps),
            "total_engagement_rows": len(all_rows),
            "file": output_path if all_rows else "No data to export",
        }, indent=2)

    # ── Snaps (featured list) ─────────────────────────────────────────────────
    elif name == "sparkplug_get_snaps":
        featured = args.get("featured_only", True)
        data = client._get(
            f"/accounts/{client.group_id}/snaps",
            params={"featured": str(featured).lower()},
        )
        snaps = data if isinstance(data, list) else data.get("snaps", data.get("data", []))
        formatted = [
            {
                "id": s.get("_id") or s.get("id"),
                "title": s.get("title"),
                "type": s.get("type"),
                "status": s.get("status"),
                "featured": s.get("featured"),
                "created_at": s.get("createdAt"),
                "views": s.get("views"),
            }
            for s in (snaps if isinstance(snaps, list) else [snaps])
        ]
        return json.dumps(formatted, indent=2)

    # ── Reach analytics ──────────────────────────────────────────────────────
    elif name == "sparkplug_get_reach":
        data = client._post(f"/accounts/{client.group_id}/reach-with-breakdown", body={})
        return json.dumps(data, indent=2)

    # ── Brands ───────────────────────────────────────────────────────────────
    elif name == "sparkplug_get_brands":
        data = client._get(f"/accounts/{client.group_id}/spark-brands")
        brands = data if isinstance(data, list) else data.get("data", [])
        formatted = [
            {"id": b.get("_id") or b.get("id"), "name": b.get("name"), "photo": b.get("photo")}
            for b in brands
        ]
        return json.dumps(formatted, indent=2)

    # ── CSV Export ───────────────────────────────────────────────────────────
    elif name == "sparkplug_export_csv":
        data_type = args["data_type"]
        ts = datetime.now().strftime("%Y%m%d")
        default_path = str(Path.home() / "Desktop" / f"sparkplug_{data_type}_{ts}.csv")
        output_path = args.get("output_path", default_path)

        if data_type == "retailers":
            count = sp_sync.export_retailers_csv(client, output_path)
        elif data_type == "sales_trend":
            count = sp_sync.export_sales_csv(
                client,
                args["retailer_id"],
                args.get("retailer_name", args["retailer_id"]),
                args["date_start"],
                args["date_end"],
                output_path,
                args.get("frequency", "monthly"),
            )
        elif data_type == "budtender_performance":
            count = sp_sync.export_budtender_csv(
                client,
                args["retailer_id"],
                args.get("retailer_name", args["retailer_id"]),
                args["date_start"],
                args["date_end"],
                output_path,
            )
        else:
            return f"Unknown data_type: {data_type}"

        return json.dumps({"exported_rows": count, "file": output_path}, indent=2)

    # ── Google Sheets Sync ───────────────────────────────────────────────────
    elif name == "sparkplug_sync_to_sheets":
        data_type = args.get("data_type", "retailers")
        worksheet = args.get("worksheet_name", f"Sparkplug {data_type.replace('_', ' ').title()}")

        if data_type == "retailers":
            count = sp_sync.sync_retailers_to_sheets(client, args["spreadsheet_id"], worksheet_name=worksheet)
        elif data_type == "sales_trend":
            count = sp_sync.sync_sales_to_sheets(
                client,
                args["retailer_id"],
                args.get("retailer_name", ""),
                args["date_start"],
                args["date_end"],
                args["spreadsheet_id"],
                worksheet_name=worksheet,
                frequency=args.get("frequency", "monthly"),
            )
        else:
            return f"Unknown data_type: {data_type}"

        return json.dumps({"synced_rows": count, "worksheet": worksheet}, indent=2)

    # ── HubSpot Sync ─────────────────────────────────────────────────────────
    elif name == "sparkplug_sync_to_hubspot":
        result = sp_sync.sync_retailers_to_hubspot(client)
        return json.dumps(result, indent=2)

    else:
        return f"Unknown tool: {name}"


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
