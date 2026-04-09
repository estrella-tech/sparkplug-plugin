# Sparkplug Plugin for Atomic Fungi

Connects Claude in Cowork to the Sparkplug API, letting you query sales data, budtender performance, Snaps analytics, and retailer info — and sync it all to Google Sheets and HubSpot.

## Quick Start

1. Install the plugin in Cowork (accept the `.plugin` file)
2. Run `/sparkplug-setup` to authenticate
3. Run `/sparkplug-report` to generate your first report

## Commands

| Command | What it does |
|---------|-------------|
| `/sparkplug-setup` | Authenticate with Sparkplug (first-time setup) |
| `/sparkplug-report [period]` | Full performance report — sales, budtender leaderboard, Snaps |
| `/sparkplug-sync [target]` | Sync data to HubSpot, Google Sheets, or CSV |

## MCP Tools

The plugin exposes 12 tools to Claude:

- `sparkplug_get_retailers` — connected retail partners
- `sparkplug_get_sales` — total units sold at a retailer
- `sparkplug_get_sales_trend` — time-series sales buckets
- `sparkplug_get_budtender_performance` — per-budtender unit totals
- `sparkplug_get_products_with_sales` — which SKUs recorded sales
- `sparkplug_get_snaps` — Snaps (brand content) published
- `sparkplug_get_reach` — Snap reach and engagement
- `sparkplug_get_brands` — sub-brands under Atomic Fungi
- `sparkplug_export_csv` — export to local CSV
- `sparkplug_sync_to_sheets` — push to Google Sheet
- `sparkplug_sync_to_hubspot` — upsert retailers in HubSpot
- `sparkplug_setup_check` — verify auth is working

## Authentication

The plugin uses your Sparkplug JWT token, extracted automatically via Playwright.
Token is stored at `config/sparkplug.json` (gitignored).

Run `/sparkplug-setup` anytime the token expires.

## Optional Env Vars

| Variable | Required for |
|----------|-------------|
| `GOOGLE_CREDENTIALS_PATH` | Google Sheets sync (`sparkplug_sync_to_sheets`) |
| `HUBSPOT_ACCESS_TOKEN` | HubSpot sync (`sparkplug_sync_to_hubspot`) |

Set these in your system environment or in Cowork's plugin settings.

## Current Retailers

| Name | ID | Market |
|------|----|--------|
| Major Bloom | `65aedee5ae79f200127e9754` | MA |

More retailers will appear automatically as you connect them in Sparkplug.
