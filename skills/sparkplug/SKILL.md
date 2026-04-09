---
name: sparkplug
description: >
  Use this skill when Giovanni asks about Sparkplug data, budtender performance,
  Snap reach, retailer connections, or wants to sync Sparkplug data to Google Sheets
  or HubSpot. Trigger on: "sparkplug", "budtender sales", "snap reach", "how are we
  performing at Major Bloom", "export sparkplug data", "sync retailers to HubSpot",
  "sync to sheets", "which budtenders are selling our products", "Snaps analytics",
  "how many units did we sell", "sparkplug report", "sparkplug sync".
version: 0.1.0
---

# Sparkplug Skill

This skill guides Claude in using the `sparkplug` MCP server to query and sync Atomic Fungi's Sparkplug data.

## Account Context

- **Vendor**: Atomic Fungi
- **Vendor Group ID**: `691270b4e489475b3f933902`
- **Current retailer partner**: Major Bloom (MA) — ID: `65aedee5ae79f200127e9754`
- **Platform**: Sparkplug (`my.sparkplug.app`)

## Available MCP Tools

| Tool | What it does |
|------|-------------|
| `sparkplug_get_retailers` | List all connected retailer partners |
| `sparkplug_get_sales` | Total units sold at a retailer over a date range |
| `sparkplug_get_sales_trend` | Time-series sales buckets (for trend analysis) |
| `sparkplug_get_budtender_performance` | Units per budtender at a retailer |
| `sparkplug_get_products_with_sales` | Which product IDs actually sold |
| `sparkplug_list_snaps` | List all Snaps with their storifymeSnapId, name, markets, page count |
| `sparkplug_get_snap_engagement` | Per-employee engagement rows for a specific Snap (views, slide progress, actions) |
| `sparkplug_export_all_snap_analytics` | Export engagement data for ALL Snaps to a single CSV |
| `sparkplug_list_snaps` | List Snaps with optional featured filter |
| `sparkplug_get_reach` | Snap reach and engagement breakdown |
| `sparkplug_get_brands` | Sub-brands configured under Atomic Fungi |
| `sparkplug_export_csv` | Export any data to a local CSV file |
| `sparkplug_sync_to_sheets` | Push data to a Google Sheet tab |
| `sparkplug_sync_to_hubspot` | Upsert retailers as HubSpot Companies |
| `sparkplug_setup_check` | Verify auth is working |

## Workflow Patterns

### "How are our sales at Major Bloom?"
1. Call `sparkplug_get_sales` with retailer_id `65aedee5ae79f200127e9754` and the relevant date range.
2. Follow up with `sparkplug_get_sales_trend` for a monthly breakdown.
3. Summarize total units and trend direction.

### "Which budtenders are selling our products?"
1. Call `sparkplug_get_budtender_performance` for the retailer and date range.
2. Sort results by units_sold descending.
3. Present as a leaderboard. Note: employee IDs are Sparkplug internal IDs.

### "Export to CSV / Sheets / HubSpot"
- For CSV: call `sparkplug_export_csv` with the appropriate data_type.
- For Sheets: call `sparkplug_sync_to_sheets` with the spreadsheet_id.
- For HubSpot: call `sparkplug_sync_to_hubspot` (uses HUBSPOT_ACCESS_TOKEN env var).

### "Check our Snaps / export Snap analytics"
1. Call `sparkplug_list_snaps` to get all Snaps and their `storifymeSnapId` values.
2. Call `sparkplug_get_snap_engagement` with a specific snap's storifymeSnapId for per-employee engagement detail.
3. Call `sparkplug_export_all_snap_analytics` to dump every Snap's engagement rows into one CSV — Employee, Retailer, Location, Action, Slide progress.
4. Optionally call `sparkplug_get_reach` for the aggregated reach summary.

## Auth Setup

If tools return an auth error, tell Giovanni to run `/sparkplug-setup` to re-authenticate.
The token is stored at `${CLAUDE_PLUGIN_ROOT}/config/sparkplug.json`.

## Date Defaults

When the user doesn't specify dates, use sensible defaults:
- "this month" → first day of current month to today
- "last month" → full previous month
- "this year" → Jan 1 to today
- "last quarter" → 3-month period ending last month
