---
description: Generate a Sparkplug performance report with sales, budtender leaderboard, and Snaps reach
allowed-tools: mcp__sparkplug__sparkplug_get_retailers, mcp__sparkplug__sparkplug_get_sales, mcp__sparkplug__sparkplug_get_sales_trend, mcp__sparkplug__sparkplug_get_budtender_performance, mcp__sparkplug__sparkplug_get_products_with_sales, mcp__sparkplug__sparkplug_get_snaps, mcp__sparkplug__sparkplug_get_reach, mcp__sparkplug__sparkplug_export_csv
---

Generate a Sparkplug performance report for Atomic Fungi.

Arguments: $ARGUMENTS (optional date range like "March 2026" or "last 90 days"; defaults to current month)

Steps:
1. Parse the date range from $ARGUMENTS, defaulting to the current calendar month.
2. Call sparkplug_get_retailers to get all connected retailers.
3. For each retailer, gather:
   - sparkplug_get_sales — total units for the period
   - sparkplug_get_sales_trend — monthly buckets to show trend
   - sparkplug_get_budtender_performance — per-budtender unit totals
   - sparkplug_get_products_with_sales — which SKUs moved
4. Call sparkplug_get_snaps and sparkplug_get_reach for content/Snaps analytics.
5. Compose the report with these sections:
   - **Sales Summary** — total units by retailer
   - **Sales Trend** — monthly breakdown table
   - **Budtender Leaderboard** — top performers ranked by units sold
   - **Products Moving** — which product IDs recorded sales
   - **Snaps & Reach** — content stats and budtender reach
6. Offer to export the report as CSV (sparkplug_export_csv).

Keep the report concise and scannable. Lead with the most actionable insight.
