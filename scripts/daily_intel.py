#!/usr/bin/env python3
"""
Atomic Fungi Daily Intel Pipeline — runs locally.

1. Exports fresh Sparkplug data
2. Analyzes it and generates insights
3. Sends branded HTML email via Gmail API (using Claude API to compose)
4. Posts routed messages to Google Chat spaces

Usage:
    python scripts/daily_intel.py              # full pipeline
    python scripts/daily_intel.py --chat-only  # skip email, just post to chat
    python scripts/daily_intel.py --dry-run    # generate report but don't send
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add servers/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "servers"))
from client import SparkplugClient

PROJECT_ROOT = Path(__file__).parent.parent
EXPORTS_DIR = PROJECT_ROOT / "exports"
WEBHOOKS_PATH = PROJECT_ROOT / "config" / "webhooks.json"

RECIPIENTS = [
    "giovanni@atomicfungi.com",
    "jared@atomicfungi.com",
    "katrinalindseyjones@gmail.com",
]


def load_webhooks() -> dict:
    with open(WEBHOOKS_PATH) as f:
        return json.load(f)["google_chat_webhooks"]


def load_export(name: str) -> dict:
    path = EXPORTS_DIR / f"{name}.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def post_to_chat(webhook_url: str, message: str) -> int:
    """Post a message to Google Chat. Returns HTTP status code."""
    import requests
    resp = requests.post(
        webhook_url,
        json={"text": message},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    return resp.status_code


def analyze_data() -> dict:
    """Analyze all exported data and produce structured insights."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    retailers_export = load_export("retailers")
    sales_export = load_export("sales_totals")
    trends_export = load_export("sales_trends")
    budtender_export = load_export("budtender_performance")
    snaps_export = load_export("snaps")
    snap_summary = load_export("snap_engagement_summary")

    retailers = retailers_export.get("data", [])
    sales_data = sales_export.get("data", [])
    trends_data = trends_export.get("data", [])
    budtender_data = budtender_export.get("data", [])
    snaps = snaps_export.get("data", [])

    # Export freshness check
    export_ts = retailers_export.get("exported_at", "")
    stale = False
    if export_ts:
        try:
            export_dt = datetime.fromisoformat(export_ts.replace("Z", "+00:00"))
            stale = (now - export_dt).days > 2
        except Exception:
            stale = True

    # Sales summary per retailer per period
    sales_by_retailer = {}
    for entry in sales_data:
        rid = entry.get("retailer_name", entry.get("retailer_id", "unknown"))
        period = entry.get("period", "?")
        data = entry.get("data", {})
        if rid not in sales_by_retailer:
            sales_by_retailer[rid] = {}
        # Try to extract total units from various response shapes
        if isinstance(data, dict):
            total = data.get("total", data.get("totalUnits", data.get("value", 0)))
            if isinstance(total, dict):
                total = total.get("total", total.get("value", 0))
        else:
            total = 0
        sales_by_retailer[rid][period] = total

    # Budtender rankings per retailer
    budtender_rankings = {}
    for entry in budtender_data:
        rname = entry.get("retailer_name", "unknown")
        data = entry.get("data", {})
        if isinstance(data, dict):
            ranked = sorted(data.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)
            budtender_rankings[rname] = ranked[:5]
        elif isinstance(data, list):
            budtender_rankings[rname] = data[:5]

    # Trends
    trend_summaries = {}
    for entry in trends_data:
        rname = entry.get("retailer_name", "unknown")
        data = entry.get("data", {})
        buckets = data.get("rows", data.get("buckets", []))
        if isinstance(buckets, list):
            trend_summaries[rname] = buckets

    # Snap stats
    snap_stats = {
        "total_snaps": len(snaps),
        "total_interactions": snap_summary.get("data", {}).get("total_interactions", 0) if isinstance(snap_summary.get("data"), dict) else snap_summary.get("data", 0),
        "unique_employees": snap_summary.get("data", {}).get("unique_employees", 0) if isinstance(snap_summary.get("data"), dict) else 0,
        "unique_retailers": snap_summary.get("data", {}).get("unique_retailers", 0) if isinstance(snap_summary.get("data"), dict) else 0,
    }

    # Build action items
    action_items = []

    for rname, periods in sales_by_retailer.items():
        sales_7d = periods.get("7d", 0)
        sales_30d = periods.get("30d", 0)
        if sales_30d == 0 and sales_7d == 0:
            action_items.append(f"URGENT: {rname} — zero sales in 30 days. Needs store visit or sample drop.")
        elif sales_7d == 0 and sales_30d > 0:
            action_items.append(f"{rname} — no sales this week but {sales_30d} units in 30d. Check if stock issue or budtender engagement dropped.")

    # Retailers with no snap engagement
    for r in retailers:
        rname = r.get("accountName", "unknown")
        action_items.append(f"Push Snap content to {rname} — check if budtenders have engaged with training materials.")

    return {
        "date": today,
        "stale_data": stale,
        "retailers": retailers,
        "sales_by_retailer": sales_by_retailer,
        "budtender_rankings": budtender_rankings,
        "trend_summaries": trend_summaries,
        "snap_stats": snap_stats,
        "action_items": action_items[:5],
    }


def format_team_chat(insights: dict) -> str:
    """Format the main Team Chat message."""
    lines = [f"📊 *AF Daily Intel — {insights['date']}*"]
    if insights["stale_data"]:
        lines.append("⚠️ Data may be stale (>2 days old)")
    lines.append("")

    # Sales
    for rname, periods in insights["sales_by_retailer"].items():
        s7 = periods.get("7d", 0)
        s30 = periods.get("30d", 0)
        s90 = periods.get("90d", 0)
        lines.append(f"*{rname}*: {s7} units/7d | {s30}/30d | {s90}/90d")
    lines.append("")

    # Snaps
    ss = insights["snap_stats"]
    lines.append(f"📱 Snaps: {ss['total_interactions']} interactions | {ss['unique_employees']} budtenders | {ss['unique_retailers']} retailers")
    lines.append("")

    # Action items
    lines.append("*Action Items:*")
    emojis = ["🔥", "📞", "📊", "🎯", "📦"]
    for i, item in enumerate(insights["action_items"]):
        emoji = emojis[i % len(emojis)]
        lines.append(f"{emoji} {item}")

    return "\n".join(lines)[:1000]


def format_crm_chat(insights: dict) -> str:
    """Format CRM-specific message."""
    lines = [f"📋 *AF CRM Update — {insights['date']}*", ""]
    has_content = False
    for rname, periods in insights["sales_by_retailer"].items():
        s7 = periods.get("7d", 0)
        s30 = periods.get("30d", 0)
        if s7 == 0 or s30 == 0:
            lines.append(f"⚠️ *{rname}*: {s7} units/7d, {s30}/30d — needs follow-up")
            has_content = True
    if not has_content:
        return ""
    lines.append("")
    lines.append("_Check HubSpot for last contact dates and deal stages._")
    return "\n".join(lines)[:1000]


def format_marketing_chat(insights: dict) -> str:
    """Format Digital Marketing message."""
    ss = insights["snap_stats"]
    lines = [
        f"📱 *AF Snap Engagement — {insights['date']}*",
        "",
        f"Total Interactions: *{ss['total_interactions']}*",
        f"Unique budtenders reached: *{ss['unique_employees']}*",
        f"Unique retailers: *{ss['unique_retailers']}*",
        f"Published Snaps: *{ss['total_snaps']}*",
        "",
    ]
    # Add marketing-specific action items
    for item in insights["action_items"]:
        if "snap" in item.lower() or "content" in item.lower() or "engag" in item.lower():
            lines.append(f"📌 {item}")
    return "\n".join(lines)[:1000]


def format_samples_chat(insights: dict) -> str:
    """Format Sample Requests message — only if there's something actionable."""
    lines = []
    for rname, periods in insights["sales_by_retailer"].items():
        s30 = periods.get("30d", 0)
        if s30 == 0:
            lines.append(f"📦 *{rname}*: 0 sales in 30d — consider sample drop / tasting session")
    if not lines:
        return ""
    header = [f"🧪 *AF Sample Suggestions — {insights['date']}*", ""]
    return "\n".join(header + lines)[:1000]


def format_email_html(insights: dict) -> str:
    """Generate branded HTML email."""
    date = insights["date"]

    # Sales table rows
    sales_rows = ""
    for rname, periods in insights["sales_by_retailer"].items():
        sales_rows += f"""<tr>
            <td style="padding:8px;border-bottom:1px solid #eee">{rname}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center"><b>{periods.get('7d', 0)}</b></td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center"><b>{periods.get('30d', 0)}</b></td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center"><b>{periods.get('90d', 0)}</b></td>
        </tr>"""

    # Action items
    action_html = ""
    for item in insights["action_items"]:
        action_html += f'<li style="margin-bottom:8px">{item}</li>'

    # Snap stats
    ss = insights["snap_stats"]

    stale_warning = ""
    if insights["stale_data"]:
        stale_warning = '<div style="background:#fff3cd;padding:10px;margin-bottom:20px;border-radius:4px">⚠️ Data may be stale (exported >2 days ago)</div>'

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;background:#f5f5f5;padding:20px">
    <div style="background:#1a3c2e;padding:20px;border-radius:8px 8px 0 0">
        <h1 style="color:#c8a45a;margin:0;font-size:24px">AF Daily Intel</h1>
        <p style="color:#ffffff;margin:5px 0 0 0;font-size:14px">{date}</p>
    </div>

    <div style="background:#ffffff;padding:20px;border-radius:0 0 8px 8px">
        {stale_warning}

        <h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px">🎯 Action Items</h2>
        <ol style="padding-left:20px">{action_html}</ol>

        <h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px">📊 Sales Summary</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="background:#1a3c2e;color:#ffffff">
                <th style="padding:10px;text-align:left">Retailer</th>
                <th style="padding:10px;text-align:center">7d</th>
                <th style="padding:10px;text-align:center">30d</th>
                <th style="padding:10px;text-align:center">90d</th>
            </tr>
            {sales_rows}
        </table>

        <h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:30px">📱 Snap Engagement</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr><td style="padding:6px">Total Interactions</td><td style="padding:6px"><b>{ss['total_interactions']}</b></td></tr>
            <tr><td style="padding:6px">Unique Budtenders</td><td style="padding:6px"><b>{ss['unique_employees']}</b></td></tr>
            <tr><td style="padding:6px">Unique Retailers</td><td style="padding:6px"><b>{ss['unique_retailers']}</b></td></tr>
            <tr><td style="padding:6px">Published Snaps</td><td style="padding:6px"><b>{ss['total_snaps']}</b></td></tr>
        </table>

        <div style="margin-top:30px;padding-top:15px;border-top:1px solid #eee;color:#888;font-size:12px">
            Atomic Fungi Daily Intel — Generated automatically from Sparkplug + HubSpot data
        </div>
    </div>
</body>
</html>"""
    return html


def send_email(subject: str, html_body: str, recipients: list[str], dry_run: bool = False):
    """Send email via gmail_sender module (OAuth2 or App Password)."""
    # Always save a copy
    report_path = EXPORTS_DIR / f"daily_intel_{datetime.now().strftime('%Y%m%d')}.html"
    report_path.write_text(html_body, encoding="utf-8")
    print(f"  Report saved to {report_path}")

    if dry_run:
        print("  [DRY RUN] Email not sent.")
        return

    sys.path.insert(0, str(PROJECT_ROOT / "servers"))
    from gmail_sender import send_email as gmail_send
    success = gmail_send(to=recipients, subject=subject, html_body=html_body)
    if not success:
        print(f"  Email failed — report saved at {report_path}")


def main():
    dry_run = "--dry-run" in sys.argv
    chat_only = "--chat-only" in sys.argv

    print(f"=== Atomic Fungi Daily Intel Pipeline ===")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    # Step 1: Export fresh data
    print("[1/4] Exporting fresh Sparkplug data...")
    try:
        from export_data import run_export
        run_export()
    except Exception as e:
        print(f"  Export failed: {e}")
        print("  Continuing with existing data...")
    print()

    # Step 2: Analyze
    print("[2/4] Analyzing data...")
    insights = analyze_data()
    print(f"  Retailers: {len(insights['retailers'])}")
    print(f"  Action items: {len(insights['action_items'])}")
    print()

    # Step 3: Post to Google Chat
    print("[3/4] Posting to Google Chat spaces...")
    webhooks = load_webhooks()

    chat_messages = {
        "crm": format_crm_chat(insights),
        "digital_marketing": format_marketing_chat(insights),
    }

    for key, msg in chat_messages.items():
        if not msg:
            print(f"  {webhooks[key]['name']}: skipped (no relevant content)")
            continue
        if dry_run:
            print(f"  {webhooks[key]['name']}: [DRY RUN] would post {len(msg)} chars")
            continue
        status = post_to_chat(webhooks[key]["url"], msg)
        print(f"  {webhooks[key]['name']}: {'sent' if status == 200 else f'FAILED ({status})'}")
    print()

    # Step 4: Send email
    if not chat_only:
        print("[4/4] Sending email...")
        subject = f"AF Daily Intel — {insights['date']}"
        html = format_email_html(insights)
        send_email(subject, html, RECIPIENTS, dry_run=dry_run)
    else:
        print("[4/4] Email skipped (--chat-only)")

    print()
    print("=== Pipeline complete ===")


if __name__ == "__main__":
    main()
