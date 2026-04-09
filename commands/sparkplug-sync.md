---
description: Sync all Sparkplug data — retailers to HubSpot, sales to Sheets, export CSVs
allowed-tools: mcp__sparkplug__sparkplug_get_retailers, mcp__sparkplug__sparkplug_sync_to_hubspot, mcp__sparkplug__sparkplug_sync_to_sheets, mcp__sparkplug__sparkplug_export_csv, mcp__sparkplug__sparkplug_get_sales, mcp__sparkplug__sparkplug_get_budtender_performance
---

Run a full Sparkplug data sync for Atomic Fungi.

Arguments: $ARGUMENTS (optional — can specify "hubspot", "sheets", "csv", or leave blank for all)

Steps:
1. Call sparkplug_get_retailers to confirm connectivity and list all retailers.
2. Based on $ARGUMENTS or default (all):
   a. **HubSpot sync**: Call sparkplug_sync_to_hubspot to upsert retailers as Companies.
   b. **Sheets sync**: Ask for the Google Sheets spreadsheet ID if not already known, then call sparkplug_sync_to_sheets for retailers.
   c. **CSV export**: Call sparkplug_export_csv with data_type "retailers" to ~/Desktop/sparkplug_retailers_<date>.csv.
3. For each retailer, pull the last 30 days of sales and budtender performance:
   - sparkplug_get_sales (monthly frequency, last 30 days)
   - sparkplug_get_budtender_performance (monthly, last 30 days)
4. Report a sync summary: retailers synced, rows exported, any errors.

Use today's date for date_end and subtract 30 days for date_start.
Format dates as YYYY-MM-DD.
