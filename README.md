# Sparkplug Plugin for Atomic Fungi

Custom MCP server + daily intel pipeline that reverse-engineers Sparkplug's internal API for budtender incentive analytics, integrated with HubSpot CRM and Gmail.

## Overview

Sparkplug has no public API. This plugin intercepts the internal API at `api-server-production.sparkplug-technology.io` to pull sales, budtender performance, and Snap engagement data for Atomic Fungi's cannabis dispensary partners.

**Owner:** Giovanni Estrella / Atomic Fungi
**Vendor Group ID:** `691270b4e489475b3f933902`

## Daily Intel Pipeline

Runs daily at **9:00 AM ET** via Windows Task Scheduler:

1. **Export** — Pulls fresh data from Sparkplug API, HubSpot CRM, and Gmail
2. **Analyze** — Aggregates sales, budtender leaderboard, deal pipeline, stale contacts
3. **Google Chat** — Posts routed insights to CRM and Digital Marketing spaces
4. **Email** — Sends branded HTML report to team via Gmail OAuth2

```bash
python scripts/daily_intel.py              # full pipeline
python scripts/daily_intel.py --chat-only  # skip email
python scripts/daily_intel.py --dry-run    # preview without sending
```

## Outreach Tools

### Rewrite Drafts
Rewrites outreach email drafts using Gemini AI + Sparkplug/HubSpot enrichment:
```bash
python scripts/rewrite_drafts.py --dry-run --limit 5
python scripts/rewrite_drafts.py --limit 20
```

### Store Visit Follow-Ups
Generate follow-up emails after store visits:
```bash
python scripts/store_visit_followup.py "Embr, Resinate" --visitor Jared --tasting
```

## MCP Tools (14)

| Tool | Description |
|------|-------------|
| `sparkplug_get_retailers` | All connected dispensary accounts |
| `sparkplug_get_sales` | Sales totals for a date range |
| `sparkplug_get_sales_trend` | Weekly/daily bucketed trend data |
| `sparkplug_get_budtender_performance` | Per-employee sales performance |
| `sparkplug_get_products_with_sales` | Products with sales data |
| `sparkplug_list_snaps` | All Snaps with optional featured filter |
| `sparkplug_get_snap_engagement` | Per-employee engagement for one Snap |
| `sparkplug_export_all_snap_analytics` | Full engagement export across all Snaps |
| `sparkplug_get_reach` | Overall Snap reach summary |
| `sparkplug_get_brands` | Brand list |
| `sparkplug_export_csv` | Export retailers/sales/budtenders to CSV |
| `sparkplug_sync_to_sheets` | Sync to Google Sheets |
| `sparkplug_sync_to_hubspot` | Upsert retailers as HubSpot Companies |
| `sparkplug_setup_check` | Verify auth config |

## Authentication

| Service | Location | Notes |
|---------|----------|-------|
| Sparkplug JWT | `~/.sparkplug/sparkplug.json` | Expires ~30 days, refresh from browser localStorage |
| Gmail OAuth2 | `~/.sparkplug/gmail_token.json` + `gmail_credentials.json` | Auto-refreshes |
| HubSpot | `~/.sparkplug/hubspot_token.txt` | Private app token |
| Gemini AI | `~/.sparkplug/gemini_key.txt` | Free tier (15 RPM) |

## Data Exports

The pipeline exports to `exports/` on each run:

| File | Source | Contents |
|------|--------|----------|
| `retailers.json` | Sparkplug | Connected retail partners |
| `sales_totals.json` | Sparkplug | 7d/30d/90d sales per retailer |
| `sales_trends.json` | Sparkplug | Weekly time-series buckets |
| `budtender_performance.json` | Sparkplug | Per-budtender unit sales |
| `snaps.json` | Sparkplug | All published Snaps |
| `snap_engagement.csv` | Sparkplug | Per-budtender engagement rows |
| `budtender_leaderboard.json` | Sparkplug | Top 50 by views/completions/CTAs |
| `hubspot_deals.json` | HubSpot | All deals with stages and amounts |
| `hubspot_pipeline_summary.json` | HubSpot | Pipeline by stage |
| `hubspot_companies.json` | HubSpot | Companies with contact history |
| `gmail_drafts.json` | Gmail | Draft count and metadata |

## Project Structure

```
sparkplug-plugin/
├── servers/
│   ├── server.py              # MCP server (14 tools)
│   ├── client.py              # Sparkplug HTTP API client
│   ├── auth.py                # JWT token extraction via Playwright
│   ├── gmail_sender.py        # Gmail OAuth2 email sender
│   ├── sync.py                # Google Sheets + HubSpot sync
│   ├── start.sh               # Cross-platform server launcher
│   └── requirements.txt
├── scripts/
│   ├── daily_intel.py         # Daily pipeline (export > analyze > email > chat)
│   ├── export_data.py         # Data exporter (Sparkplug + HubSpot + Gmail)
│   ├── email_utils.py         # Shared Gmail/Gemini/enrichment utilities
│   ├── rewrite_drafts.py      # AI outreach draft rewriter
│   ├── store_visit_followup.py # Post-visit follow-up generator
│   └── daily_intel.bat        # Windows Task Scheduler wrapper
├── config/
│   ├── webhooks.json          # Google Chat webhook URLs
│   ├── gold_standard_email.txt # Tone reference for AI rewrites
│   ├── rewrite_prompt.txt     # System prompt for draft rewrites
│   └── followup_prompt.txt    # System prompt for visit follow-ups
├── exports/                   # Data cache (refreshed daily)
├── skills/sparkplug/SKILL.md
├── commands/                  # Cowork slash commands
└── .claude-plugin/plugin.json
```

## Google Chat Spaces

| Space | Purpose |
|-------|---------|
| AF - CRM | Pipeline alerts, stale deals, follow-up reminders |
| AF - Digital Marketing | Snap engagement metrics, content suggestions |
| AF - Team Chat | General updates (not auto-posted) |
| AF - Sample Requests | Sample drop suggestions (not auto-posted) |
