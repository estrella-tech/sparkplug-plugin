#!/usr/bin/env python3
"""
Atomic Fungi Daily Intel Pipeline — full local pipeline.

1. Exports fresh Sparkplug + HubSpot + Gmail data
2. Analyzes everything and generates insights
3. Sends branded HTML email via Gmail OAuth2
4. Posts routed messages to Google Chat spaces (CRM + Digital Marketing)
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "servers"))

PROJECT_ROOT = Path(__file__).parent.parent
EXPORTS_DIR = PROJECT_ROOT / "exports"
WEBHOOKS_PATH = PROJECT_ROOT / "config" / "webhooks.json"
RECIPIENTS = ["giovanni@atomicfungi.com", "jared@atomicfungi.com", "katrinalindseyjones@gmail.com"]


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
    import requests
    resp = requests.post(webhook_url, json={"text": message}, headers={"Content-Type": "application/json"}, timeout=10)
    return resp.status_code


def analyze_data() -> dict:
    now = datetime.now(timezone.utc)
    today = now.strftime("%B %d, %Y")
    today_short = now.strftime("%Y-%m-%d")

    # Load all exports
    retailers_export = load_export("retailers")
    sales_export = load_export("sales_totals")
    trends_export = load_export("sales_trends")
    budtender_export = load_export("budtender_performance")
    snaps_export = load_export("snaps")
    snap_summary = load_export("snap_engagement_summary")
    pipeline_export = load_export("hubspot_pipeline_summary")
    deals_export = load_export("hubspot_deals")
    companies_export = load_export("hubspot_companies")
    drafts_export = load_export("gmail_drafts")
    leaderboard_export = load_export("budtender_leaderboard")
    chat_export = load_export("chat_messages")

    retailers = retailers_export.get("data", [])
    sales_data = sales_export.get("data", [])
    trends_data = trends_export.get("data", [])
    budtender_data = budtender_export.get("data", [])
    snaps = snaps_export.get("data", [])
    snap_stats_raw = snap_summary.get("data", {})
    pipeline = pipeline_export.get("data", {})
    all_deals = deals_export.get("data", [])
    all_companies = companies_export.get("data", [])
    drafts_data = drafts_export.get("data", {})

    # Freshness
    export_ts = retailers_export.get("exported_at", "")
    stale = False
    if export_ts:
        try:
            export_dt = datetime.fromisoformat(export_ts.replace("Z", "+00:00"))
            stale = (now - export_dt).days > 2
        except Exception:
            stale = True

    # --- Sales by retailer ---
    sales_by_retailer = {}
    for entry in sales_data:
        rid = entry.get("retailer_name", entry.get("retailer_id", "unknown"))
        period = entry.get("period", "?")
        data = entry.get("data", {})
        if rid not in sales_by_retailer:
            sales_by_retailer[rid] = {}
        if isinstance(data, dict):
            total = data.get("total", data.get("totalUnits", data.get("value", 0)))
            if isinstance(total, dict):
                total = total.get("total", total.get("value", 0))
        else:
            total = 0
        sales_by_retailer[rid][period] = total

    # --- Budtender rankings ---
    budtender_rankings = {}
    for entry in budtender_data:
        rname = entry.get("retailer_name", "unknown")
        data = entry.get("data", {})
        if isinstance(data, dict):
            ranked = sorted(data.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)
            budtender_rankings[rname] = ranked[:5]

    # --- Snap stats ---
    snap_stats = {
        "total_snaps": len(snaps),
        "total_interactions": snap_stats_raw.get("total_interactions", 0) if isinstance(snap_stats_raw, dict) else 0,
        "unique_employees": snap_stats_raw.get("unique_employees", 0) if isinstance(snap_stats_raw, dict) else 0,
        "unique_retailers": snap_stats_raw.get("unique_retailers", 0) if isinstance(snap_stats_raw, dict) else 0,
    }

    # --- HubSpot Pipeline ---
    hs_pipeline = pipeline if isinstance(pipeline, dict) else {}
    by_stage = hs_pipeline.get("by_stage", {})
    total_deals = hs_pipeline.get("total_deals", 0)
    closed_won_value = hs_pipeline.get("closed_won_value", 0)
    total_pipeline_value = hs_pipeline.get("total_value", 0)

    # Stale companies (not contacted in 14+ days)
    stale_companies = []
    for c in all_companies:
        last = c.get("last_contacted", "")
        name = c.get("name", "Unknown")
        if not last:
            if c.get("num_deals", 0) > 0:
                stale_companies.append({"name": name, "days": "never", "deals": c.get("num_deals", 0)})
            continue
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            days_ago = (now - last_dt).days
            if days_ago >= 14 and c.get("num_deals", 0) > 0:
                stale_companies.append({"name": name, "days": days_ago, "deals": c.get("num_deals", 0)})
        except Exception:
            pass
    stale_companies.sort(key=lambda x: x["days"] if isinstance(x["days"], int) else 999, reverse=True)

    # --- Gmail Drafts ---
    total_drafts = drafts_data.get("total_drafts", 0) if isinstance(drafts_data, dict) else 0
    recent_drafts = drafts_data.get("recent_drafts", []) if isinstance(drafts_data, dict) else []

    # --- Action Items ---
    action_items = []

    # Sales-based actions
    for rname, periods in sales_by_retailer.items():
        s7 = periods.get("7d", 0)
        s30 = periods.get("30d", 0)
        if s30 == 0 and s7 == 0:
            action_items.append({"priority": "high", "text": f"{rname} — zero sales in 30 days. Needs store visit or sample drop.", "category": "crm"})
        elif s7 == 0 and s30 > 0:
            action_items.append({"priority": "medium", "text": f"{rname} — no sales this week ({s30} units/30d). Check stock or budtender engagement.", "category": "crm"})

    # Stale company actions
    for sc in stale_companies[:3]:
        days = f"{sc['days']} days" if isinstance(sc['days'], int) else "never contacted"
        action_items.append({"priority": "high", "text": f"{sc['name']} — {days} since last contact, {sc['deals']} active deal(s). Follow up.", "category": "crm"})

    # Draft actions
    if total_drafts > 5:
        action_items.append({"priority": "medium", "text": f"{total_drafts} unsent email drafts in Gmail. Review and send or discard.", "category": "crm"})

    # Snap engagement actions
    for r in retailers:
        rname = r.get("accountName", "unknown")
        action_items.append({"priority": "low", "text": f"Push latest Snap content to {rname} budtenders.", "category": "marketing"})

    # --- Chat insights ---
    chat_data = chat_export.get("data", {}) if isinstance(chat_export.get("data"), dict) else {}
    store_visits = chat_data.get("store_visits", [])
    recent_chat_messages = chat_data.get("messages", [])[-20:]  # last 20 messages

    if store_visits:
        for sv in store_visits[:3]:
            action_items.append({
                "priority": "high",
                "text": f"Store visit mentioned in {sv.get('space', 'chat')}: \"{sv.get('text', '')[:80]}...\" — generate follow-up emails",
                "category": "crm",
            })

    # --- Budtender Leaderboard (from Snap engagement) ---
    leaderboard = leaderboard_export.get("data", []) if isinstance(leaderboard_export.get("data"), list) else []

    return {
        "date": today,
        "date_short": today_short,
        "stale_data": stale,
        "retailers": retailers,
        "sales_by_retailer": sales_by_retailer,
        "budtender_rankings": budtender_rankings,
        "budtender_leaderboard": leaderboard[:15],
        "snap_stats": snap_stats,
        "hs_pipeline": by_stage,
        "hs_total_deals": total_deals,
        "hs_closed_won": closed_won_value,
        "hs_total_value": total_pipeline_value,
        "stale_companies": stale_companies,
        "total_drafts": total_drafts,
        "recent_drafts": recent_drafts,
        "store_visits": store_visits,
        "recent_chat": recent_chat_messages,
        "action_items": action_items,
    }


def format_crm_chat(insights: dict) -> str:
    lines = [f"*AF CRM Update — {insights['date_short']}*", ""]

    # Pipeline
    if insights["hs_total_deals"]:
        lines.append(f"Pipeline: {insights['hs_total_deals']} deals | ${insights['hs_closed_won']:,.0f} closed won")
        for stage, info in insights["hs_pipeline"].items():
            if info["count"] > 0 and stage not in ("Closed Won", "Closed Lost"):
                lines.append(f"  {stage}: {info['count']} (${info['value']:,.0f})")
        lines.append("")

    # Stale
    for sc in insights["stale_companies"][:3]:
        days = f"{sc['days']}d" if isinstance(sc['days'], int) else "never"
        lines.append(f"  {sc['name']} — {days} since contact")
    if insights["stale_companies"]:
        lines.append("")

    # Drafts
    if insights["total_drafts"] > 0:
        lines.append(f"  {insights['total_drafts']} unsent drafts in Gmail")

    # CRM actions
    crm_actions = [a for a in insights["action_items"] if a["category"] == "crm"]
    if crm_actions:
        lines.append("")
        for a in crm_actions[:4]:
            emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(a["priority"], "📌")
            lines.append(f"{emoji} {a['text']}")

    return "\n".join(lines)[:1000]


def format_marketing_chat(insights: dict) -> str:
    ss = insights["snap_stats"]
    lines = [
        f"*AF Snap Engagement — {insights['date_short']}*", "",
        f"Total interactions: *{ss['total_interactions']}*",
        f"Budtenders reached: *{ss['unique_employees']}*",
        f"Retailers: *{ss['unique_retailers']}*",
        f"Published Snaps: *{ss['total_snaps']}*", "",
    ]
    mkt_actions = [a for a in insights["action_items"] if a["category"] == "marketing"]
    for a in mkt_actions[:3]:
        lines.append(f"📌 {a['text']}")
    return "\n".join(lines)[:1000]


def format_email_html(insights: dict) -> str:
    date = insights["date"]

    # Pipeline rows
    stage_order = ["Hot Lead", "Contacted", "Sampled", "Tasting Done", "Verbal Commitment", "First Order Placed", "Closed Won", "Closed Lost"]
    pipeline_rows = ""
    for stage in stage_order:
        info = insights["hs_pipeline"].get(stage, {"count": 0, "value": 0})
        if info["count"] == 0:
            continue
        color = "#27ae60" if stage == "Closed Won" else "#e74c3c" if stage == "Closed Lost" else "#333"
        pipeline_rows += f'<tr><td style="padding:6px 10px;border-bottom:1px solid #eee;color:{color}">{stage}</td><td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center">{info["count"]}</td><td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right">${info["value"]:,.2f}</td></tr>'

    # Sales rows
    sales_rows = ""
    for rname, periods in insights["sales_by_retailer"].items():
        s7 = periods.get("7d", 0)
        s30 = periods.get("30d", 0)
        s90 = periods.get("90d", 0)
        flag = ' style="color:#e74c3c;font-weight:bold"' if s7 == 0 else ""
        sales_rows += f'<tr><td style="padding:6px 10px;border-bottom:1px solid #eee">{rname}</td><td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center"{flag}>{s7}</td><td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center">{s30}</td><td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center">{s90}</td></tr>'

    # Budtender leaderboard rows (from Snap engagement)
    leaderboard_rows = ""
    for i, bt in enumerate(insights.get("budtender_leaderboard", [])[:15]):
        total = bt.get("total", 0)
        views = bt.get("views", 0)
        completions = bt.get("completions", 0)
        ctas = bt.get("ctas", 0)
        rate = f"{completions/views*100:.0f}%" if views > 0 else "—"
        bg = "background:#f0f7f4;" if i < 3 else ""
        rank_style = "font-weight:bold;color:#c8a45a;" if i < 3 else ""
        leaderboard_rows += f'<tr style="{bg}"><td style="padding:5px 10px;border-bottom:1px solid #eee;{rank_style}">#{i+1}</td><td style="padding:5px 10px;border-bottom:1px solid #eee">{bt.get("name", "?")}</td><td style="padding:5px 10px;border-bottom:1px solid #eee;font-size:12px">{bt.get("retailer", "?")}</td><td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">{views}</td><td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">{completions}</td><td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">{ctas}</td><td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">{rate}</td></tr>'

    # Action items
    action_html = ""
    priority_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    for a in insights["action_items"][:8]:
        icon = priority_icons.get(a["priority"], "📌")
        action_html += f'<tr><td style="padding:6px 10px;border-bottom:1px solid #eee;width:30px">{icon}</td><td style="padding:6px 10px;border-bottom:1px solid #eee">{a["text"]}</td></tr>'

    # Stale companies
    stale_html = ""
    for sc in insights["stale_companies"][:5]:
        days = f"{sc['days']} days" if isinstance(sc['days'], int) else "Never"
        stale_html += f'<tr><td style="padding:4px 10px;border-bottom:1px solid #eee">{sc["name"]}</td><td style="padding:4px 10px;border-bottom:1px solid #eee;text-align:center">{days}</td><td style="padding:4px 10px;border-bottom:1px solid #eee;text-align:center">{sc["deals"]}</td></tr>'

    # Draft alert
    draft_alert = ""
    if insights["total_drafts"] > 0:
        draft_alert = f'''<div style="background:#fff3cd;border-left:4px solid #c8a45a;padding:12px 16px;margin:20px 0;border-radius:0 4px 4px 0">
            <b>{insights["total_drafts"]} unsent email drafts</b> sitting in Gmail. Review and send or discard to keep the pipeline moving.
        </div>'''

    ss = insights["snap_stats"]
    stale_warning = '<div style="background:#fff3cd;padding:10px;margin-bottom:20px;border-radius:4px">Data may be stale (exported >2 days ago)</div>' if insights["stale_data"] else ""

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:750px;margin:0 auto;background:#f5f5f5;padding:20px">
    <div style="background:#1a3c2e;padding:24px 20px;border-radius:8px 8px 0 0">
        <h1 style="color:#c8a45a;margin:0;font-size:22px">AF Daily Intel</h1>
        <p style="color:#ffffff;margin:5px 0 0 0;font-size:14px">{date}</p>
        <p style="color:#c8a45a;margin:8px 0 0 0;font-size:16px;font-weight:bold">${insights['hs_closed_won']:,.0f} Closed Won &nbsp;|&nbsp; {insights['hs_total_deals']} Deals in Pipeline &nbsp;|&nbsp; {insights['total_drafts']} Unsent Drafts</p>
    </div>

    <div style="background:#ffffff;padding:24px 20px;border-radius:0 0 8px 8px">
        {stale_warning}

        <!-- ACTION ITEMS -->
        <h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:0">Action Items</h2>
        <table style="width:100%;border-collapse:collapse">{action_html}</table>

        {draft_alert}

        <!-- DEAL PIPELINE -->
        <h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:30px">Deal Pipeline</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="background:#f8f8f8"><th style="padding:8px 10px;text-align:left">Stage</th><th style="padding:8px 10px;text-align:center">Deals</th><th style="padding:8px 10px;text-align:right">Value</th></tr>
            {pipeline_rows}
            <tr style="background:#1a3c2e;color:#ffffff"><td style="padding:8px 10px;font-weight:bold">Total</td><td style="padding:8px 10px;text-align:center;font-weight:bold">{insights['hs_total_deals']}</td><td style="padding:8px 10px;text-align:right;font-weight:bold">${insights['hs_total_value']:,.2f}</td></tr>
        </table>

        <!-- STALE CONTACTS -->
        {"" if not stale_html else f'''<h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:30px">Needs Follow-Up (14+ days)</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="background:#f8f8f8"><th style="padding:6px 10px;text-align:left">Company</th><th style="padding:6px 10px;text-align:center">Last Contact</th><th style="padding:6px 10px;text-align:center">Active Deals</th></tr>
            {stale_html}
        </table>'''}

        <!-- SPARKPLUG SALES -->
        <h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:30px">Sparkplug Sales</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="background:#1a3c2e;color:#ffffff"><th style="padding:8px 10px;text-align:left">Retailer</th><th style="padding:8px 10px;text-align:center">7d</th><th style="padding:8px 10px;text-align:center">30d</th><th style="padding:8px 10px;text-align:center">90d</th></tr>
            {sales_rows}
        </table>

        <!-- BUDTENDER PERFORMANCE -->
        {"" if not leaderboard_rows else f'''<h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:30px">Budtender Leaderboard (Snap Engagement)</h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
            <tr style="background:#1a3c2e;color:#ffffff"><th style="padding:6px 10px">Rank</th><th style="padding:6px 10px;text-align:left">Budtender</th><th style="padding:6px 10px;text-align:left">Retailer</th><th style="padding:6px 10px;text-align:center">Views</th><th style="padding:6px 10px;text-align:center">Completions</th><th style="padding:6px 10px;text-align:center">CTAs</th><th style="padding:6px 10px;text-align:center">Rate</th></tr>
            {leaderboard_rows}
        </table>'''}


        <!-- SNAP ENGAGEMENT -->
        <h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:30px">Snap Engagement</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr><td style="padding:6px 10px">Total Interactions</td><td style="padding:6px 10px;font-weight:bold">{ss['total_interactions']}</td></tr>
            <tr><td style="padding:6px 10px">Unique Budtenders</td><td style="padding:6px 10px;font-weight:bold">{ss['unique_employees']}</td></tr>
            <tr><td style="padding:6px 10px">Unique Retailers</td><td style="padding:6px 10px;font-weight:bold">{ss['unique_retailers']}</td></tr>
            <tr><td style="padding:6px 10px">Published Snaps</td><td style="padding:6px 10px;font-weight:bold">{ss['total_snaps']}</td></tr>
        </table>

        <div style="margin-top:30px;padding-top:15px;border-top:1px solid #eee;color:#888;font-size:11px">
            Atomic Fungi Daily Intel — Generated automatically from Sparkplug, HubSpot, and Gmail data
        </div>
    </div>
</body>
</html>"""
    return html


def send_email_func(subject: str, html_body: str, recipients: list[str], dry_run: bool = False):
    report_path = EXPORTS_DIR / f"daily_intel_{datetime.now().strftime('%Y%m%d')}.html"
    report_path.write_text(html_body, encoding="utf-8")
    print(f"  Report saved to {report_path}")
    if dry_run:
        print("  [DRY RUN] Email not sent.")
        return
    from gmail_sender import send_email
    success = send_email(to=recipients, subject=subject, html_body=html_body)
    if not success:
        print(f"  Email failed — report saved at {report_path}")


def main():
    dry_run = "--dry-run" in sys.argv
    chat_only = "--chat-only" in sys.argv

    print(f"=== Atomic Fungi Daily Intel Pipeline ===")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    # Step 1: Export
    print("[1/4] Exporting fresh data...")
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
    print(f"  Deals: {insights['hs_total_deals']} (${insights['hs_closed_won']:,.0f} closed won)")
    print(f"  Drafts: {insights['total_drafts']}")
    print(f"  Action items: {len(insights['action_items'])}")
    print()

    # Step 3: Google Chat
    print("[3/4] Posting to Google Chat...")
    webhooks = load_webhooks()
    chat_messages = {
        "crm": format_crm_chat(insights),
        "digital_marketing": format_marketing_chat(insights),
    }
    for key, msg in chat_messages.items():
        if not msg:
            print(f"  {webhooks[key]['name']}: skipped")
            continue
        if dry_run:
            print(f"  {webhooks[key]['name']}: [DRY RUN] {len(msg)} chars")
            continue
        status = post_to_chat(webhooks[key]["url"], msg)
        print(f"  {webhooks[key]['name']}: {'sent' if status == 200 else f'FAILED ({status})'}")
    print()

    # Step 4: Email
    if not chat_only:
        print("[4/4] Sending email...")
        subject = f"AF Daily Intel — {insights['date']} | ${insights['hs_closed_won']:,.0f} Closed Won | {insights['total_drafts']} Unsent Drafts"
        html = format_email_html(insights)
        send_email_func(subject, html, RECIPIENTS, dry_run=dry_run)
    else:
        print("[4/4] Email skipped (--chat-only)")

    print("\n=== Pipeline complete ===")


if __name__ == "__main__":
    main()
