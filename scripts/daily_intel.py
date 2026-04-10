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
ADMIN_RECIPIENTS = ["giovanni@atomicfungi.com", "jakyla@atomicfungi.com"]
ADMIN_CC = ["support@atomicfungi.com"]
ADMIN_PROJECTS = {"label_redesign"}  # Task nags for these projects go to admin only


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


def load_tasks() -> list[dict]:
    """Load persistent task tracker."""
    tasks_path = PROJECT_ROOT / "scripts" / "tasks.json"
    if not tasks_path.exists():
        return []
    import json as _json
    data = _json.loads(tasks_path.read_text())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tasks = data.get("tasks", [])
    # Calculate overdue status
    for t in tasks:
        if t["status"] in ("open", "in_progress") and t.get("due"):
            t["overdue"] = t["due"] < today
            days = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(t["due"], "%Y-%m-%d")).days
            t["days_overdue"] = max(0, days)
        else:
            t["overdue"] = False
            t["days_overdue"] = 0
    return tasks


def _fmt_delta(val):
    if val is None:
        return ""
    sign = "+" if val >= 0 else ""
    return f" ({sign}{val})"


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
    courses_export = load_export("course_completions")
    cta_export = load_export("cta_responses")

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
            # Try direct keys first
            total = data.get("total", data.get("totalUnits", data.get("value", 0)))
            if isinstance(total, dict):
                total = total.get("total", total.get("value", 0))
            # Sparkplug API returns {"rows": [{"value": N}]} format
            if total == 0 and "rows" in data:
                rows = data["rows"]
                if rows and isinstance(rows, list) and len(rows) > 0:
                    total = rows[0].get("value", 0)
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

    # --- Snap stats with daily/weekly deltas ---
    total_interactions = snap_stats_raw.get("total_interactions", 0) if isinstance(snap_stats_raw, dict) else 0
    unique_employees = snap_stats_raw.get("unique_employees", 0) if isinstance(snap_stats_raw, dict) else 0
    unique_retailers = snap_stats_raw.get("unique_retailers", 0) if isinstance(snap_stats_raw, dict) else 0

    # Load yesterday's and last week's snapshots for deltas
    snapshot_dir = EXPORTS_DIR / "snapshots"
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    last_week = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    def _load_snapshot(date_str):
        path = snapshot_dir / f"{date_str}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None

    yesterday_snap = _load_snapshot(yesterday)
    week_ago_snap = _load_snapshot(last_week)

    def _calc_delta(current, snapshot, key):
        if not snapshot or not snapshot.get("totals"):
            return None
        prev = snapshot["totals"].get(key, 0)
        return current - prev

    daily_delta_interactions = _calc_delta(total_interactions, yesterday_snap, "total_interactions")
    daily_delta_employees = _calc_delta(unique_employees, yesterday_snap, "unique_employees")
    weekly_delta_interactions = _calc_delta(total_interactions, week_ago_snap, "total_interactions")
    weekly_delta_employees = _calc_delta(unique_employees, week_ago_snap, "unique_employees")

    snap_stats = {
        "total_snaps": len(snaps),
        "total_interactions": total_interactions,
        "unique_employees": unique_employees,
        "unique_retailers": unique_retailers,
        "daily_delta_interactions": daily_delta_interactions,
        "daily_delta_employees": daily_delta_employees,
        "weekly_delta_interactions": weekly_delta_interactions,
        "weekly_delta_employees": weekly_delta_employees,
    }

    # --- Per-Snap performance ---
    import csv as _csv
    snap_perf = {}
    snap_csv_path = EXPORTS_DIR / "snap_engagement.csv"
    if snap_csv_path.exists():
        with open(snap_csv_path, newline="", encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                sname = row.get("snap_name", "").strip()
                sid = row.get("snap_id", "").strip()
                action = row.get("Action", "").strip()
                if not sname:
                    continue
                key = f"{sid}|{sname}"
                if key not in snap_perf:
                    snap_perf[key] = {"name": sname, "id": sid, "views": 0, "completions": 0, "ctas": 0}
                if action == "Story Started":
                    snap_perf[key]["views"] += 1
                elif action == "Story Complete":
                    snap_perf[key]["completions"] += 1
                elif action == "Story Text Question Answer":
                    snap_perf[key]["ctas"] += 1
    # Enrich with thumbnails and dates from snap metadata
    snap_meta = {}
    for s in snaps:
        sid = str(s.get("storifymeSnapId", ""))
        featured = s.get("featuredPeriods", [])
        live_date = featured[0]["startDate"][:10] if featured else s.get("createdAt", "")[:10]
        snap_meta[sid] = {
            "thumbnail": s.get("thumbnailUrl", ""),
            "date": live_date,
            "pages": s.get("totalPages", 0),
        }
    for key in snap_perf:
        sid = snap_perf[key]["id"]
        meta = snap_meta.get(str(sid), {})
        snap_perf[key]["thumbnail"] = meta.get("thumbnail", "")
        snap_perf[key]["date"] = meta.get("date", "")
        snap_perf[key]["pages"] = meta.get("pages", 0)
    snap_performance = sorted(snap_perf.values(), key=lambda x: x["views"] + x["completions"] + x["ctas"], reverse=True)

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

    # Draft count tracked but not surfaced as action item

    # Snap engagement actions — only flag retailers with zero or very low engagement
    for r in retailers:
        rname = r.get("accountName", "unknown")
        if snap_stats["total_interactions"] > 0 and rname.lower() not in {r.lower() for r in budtender_rankings.keys()}:
            action_items.append({"priority": "low", "text": f"{rname} — zero Snap engagement. Check if budtenders are set up.", "category": "marketing"})

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

    # --- Training Courses ---
    courses_raw = courses_export.get("data", []) if isinstance(courses_export.get("data"), list) else []
    course_responses = []
    for course in courses_raw:
        for r in course.get("responses", []):
            course_responses.append(r)
    completed_courses = [r for r in course_responses if r.get("status") == "completed"]
    in_progress_courses = [r for r in course_responses if r.get("status") == "in_progress"]

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
        "course_completed": completed_courses,
        "course_in_progress": in_progress_courses,
        "all_companies": all_companies,
        "snap_performance": snap_performance,
        "cta_responses": sorted(
            (cta_export.get("data", []) if isinstance(cta_export.get("data"), list) else []),
            key=lambda x: x.get("date", ""), reverse=True
        ),
        "action_items": action_items,
        "tasks": load_tasks(),
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

    # Sales
    for rname, periods in insights["sales_by_retailer"].items():
        s7 = periods.get("7d", 0)
        s30 = periods.get("30d", 0)
        lines.append(f"  {rname}: {s7} units (7d) / {s30} units (30d)")

    # Course completions
    if insights.get("course_completed") or insights.get("course_in_progress"):
        lines.append("")
        lines.append(f"Training: {len(insights.get('course_completed', []))} completed, {len(insights.get('course_in_progress', []))} in progress")

    return "\n".join(lines)[:1000]


def format_marketing_chat(insights: dict) -> str:
    ss = insights["snap_stats"]
    di = ss.get("daily_delta_interactions")
    wi = ss.get("weekly_delta_interactions")
    de = ss.get("daily_delta_employees")
    we = ss.get("weekly_delta_employees")

    day_i = f" | Yesterday: *{di}*" if di is not None else ""
    week_i = f" | This week: *{wi}*" if wi is not None else ""
    day_e = f" | Yesterday: *{de}*" if de is not None else ""
    week_e = f" | This week: *{we}*" if we is not None else ""

    lines = [
        f"*AF Snap Engagement — {insights['date_short']}*", "",
        f"Total interactions: *{ss['total_interactions']}*{day_i}{week_i}",
        f"Budtenders reached: *{ss['unique_employees']}*{day_e}{week_e}",
        f"Retailers: *{ss['unique_retailers']}*",
        f"Published Snaps: *{ss['total_snaps']}*", "",
    ]
    # Course progress
    completed = insights.get("course_completed", [])
    in_progress = insights.get("course_in_progress", [])
    if completed or in_progress:
        lines.append(f"Training: {len(completed)} completed, {len(in_progress)} in progress")
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

    draft_alert = ""

    # Snap Performance table with thumbnails
    snap_perf_html = ""
    if insights.get("snap_performance"):
        sp_rows = ""
        for s in insights["snap_performance"]:
            thumb = s.get("thumbnail", "")
            date = s.get("date", "")
            pages = s.get("pages", "")
            views = s["views"]
            completions = s["completions"]
            ctas = s["ctas"]
            rate = f"{completions/views*100:.0f}%" if views > 0 else "—"
            thumb_html = f'<img src="{thumb}" width="50" height="65" style="border-radius:4px;vertical-align:middle;margin-right:8px">' if thumb else ""
            label = f'{thumb_html}<span style="font-size:12px;color:#666">{date} ({pages}p)</span>'
            sp_rows += f'<tr><td style="padding:5px 10px;border-bottom:1px solid #eee">{label}</td><td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">{views}</td><td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">{completions}</td><td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">{ctas}</td><td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">{rate}</td></tr>'
        snap_perf_html = f'''<h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:30px">Snap Performance</h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
            <tr style="background:#1a3c2e;color:#ffffff"><th style="padding:6px 10px;text-align:left">Snap</th><th style="padding:6px 10px;text-align:center">Views</th><th style="padding:6px 10px;text-align:center">Completions</th><th style="padding:6px 10px;text-align:center">CTAs</th><th style="padding:6px 10px;text-align:center">Rate</th></tr>
            {sp_rows}
        </table>'''

    # CTA Responses — grouped by retailer, with HubSpot contact cross-reference
    cta_section = ""
    cta_responses = insights.get("cta_responses", [])
    if cta_responses:
        # Group by retailer
        by_retailer = {}
        for r in cta_responses:
            retailer = r.get("retailer", "Unknown")
            by_retailer.setdefault(retailer, []).append(r)

        # Cross-reference HubSpot for buyer contacts
        hs_contacts_by_company = {}
        for c in insights.get("all_companies", []):
            cname = (c.get("name") or "").lower()
            email = c.get("domain", "")
            if cname:
                hs_contacts_by_company[cname] = {
                    "domain": email,
                    "last_contacted": c.get("last_contacted", ""),
                    "deals": c.get("num_deals", 0),
                }

        cta_rows = ""
        for retailer in by_retailer:
            responses = by_retailer[retailer]
            # Find HubSpot match
            hs_info = ""
            r_lower = retailer.lower()
            for cn, cdata in hs_contacts_by_company.items():
                if r_lower in cn or cn in r_lower or (len(r_lower.split()[0]) > 3 and r_lower.split()[0] in cn):
                    parts = []
                    if cdata["domain"]:
                        parts.append(cdata["domain"])
                    if cdata["deals"]:
                        parts.append(f'{cdata["deals"]} deal(s)')
                    if cdata["last_contacted"]:
                        parts.append(f'last contact: {cdata["last_contacted"][:10]}')
                    hs_info = " | ".join(parts)
                    break

            # Retailer header row
            hs_badge = f'<span style="color:#888;font-size:11px"> — {hs_info}</span>' if hs_info else ""
            cta_rows += f'<tr style="background:#f0f7f4"><td colspan="3" style="padding:8px 10px;font-weight:bold;border-bottom:1px solid #ddd">{retailer}{hs_badge}</td></tr>'

            for r in responses:
                date = r.get("date", "")
                resp_text = str(r.get("response", "")).replace("\n", " ").strip()[:120]
                cta_rows += f'<tr><td style="padding:4px 10px 4px 20px;border-bottom:1px solid #eee;font-size:12px">{r.get("employee","?")}</td><td style="padding:4px 10px;border-bottom:1px solid #eee;font-size:12px">{date}</td><td style="padding:4px 10px;border-bottom:1px solid #eee;font-size:12px">{resp_text}</td></tr>'

        cta_section = f'''<h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:30px">CTA Responses ({len(cta_responses)})</h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
            <tr style="background:#1a3c2e;color:#ffffff"><th style="padding:6px 10px;text-align:left">Budtender</th><th style="padding:6px 10px;text-align:left">Date</th><th style="padding:6px 10px;text-align:left">Response</th></tr>
            {cta_rows}
        </table>'''

    # Task nagging section — filter admin tasks out of team email
    tasks = insights.get("tasks", [])
    open_tasks = [t for t in tasks if t["status"] in ("open", "in_progress") and t.get("project") not in ADMIN_PROJECTS]
    overdue_tasks = [t for t in open_tasks if t.get("overdue")]
    task_nag_html = ""
    if open_tasks:
        task_rows = ""
        for t in sorted(open_tasks, key=lambda x: (not x.get("overdue"), x.get("due") or "9999")):
            if t.get("overdue"):
                bg = "background:#fde8e8;"
                badge = f'<span style="color:#e74c3c;font-weight:bold">OVERDUE ({t["days_overdue"]}d)</span>'
            elif t["priority"] == "critical":
                bg = "background:#fff3cd;"
                badge = '<span style="color:#e67e22;font-weight:bold">CRITICAL</span>'
            else:
                bg = ""
                badge = t["priority"].upper()
            task_rows += f'<tr style="{bg}"><td style="padding:6px 10px;border-bottom:1px solid #eee">{badge}</td><td style="padding:6px 10px;border-bottom:1px solid #eee">{t["title"]}</td><td style="padding:6px 10px;border-bottom:1px solid #eee">{t.get("due","")}</td></tr>'

        overdue_count = len(overdue_tasks)
        header_color = "#e74c3c" if overdue_count else "#1a3c2e"
        task_nag_html = f'''
        <h2 style="color:{header_color};border-bottom:2px solid {"#e74c3c" if overdue_count else "#c8a45a"};padding-bottom:8px">Open Tasks ({len(open_tasks)}{f" / {overdue_count} OVERDUE" if overdue_count else ""})</h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
            <tr style="background:#f8f8f8"><th style="padding:6px 10px;text-align:left">Priority</th><th style="padding:6px 10px;text-align:left">Task</th><th style="padding:6px 10px">Due</th></tr>
            {task_rows}
        </table>'''

    ss = insights["snap_stats"]
    stale_warning = '<div style="background:#fff3cd;padding:10px;margin-bottom:20px;border-radius:4px">Data may be stale (exported >2 days ago)</div>' if insights["stale_data"] else ""

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:750px;margin:0 auto;background:#f5f5f5;padding:20px">
    <div style="background:#1a3c2e;padding:24px 20px;border-radius:8px 8px 0 0">
        <h1 style="color:#c8a45a;margin:0;font-size:22px">AF Daily Intel</h1>
        <p style="color:#ffffff;margin:5px 0 0 0;font-size:14px">{date}</p>
        <p style="color:#c8a45a;margin:8px 0 0 0;font-size:16px;font-weight:bold">${insights['hs_closed_won']:,.0f} Closed Won &nbsp;|&nbsp; {insights['hs_total_deals']} Deals in Pipeline</p>
    </div>

    <div style="background:#ffffff;padding:24px 20px;border-radius:0 0 8px 8px">
        {stale_warning}

        <!-- SNAP ENGAGEMENT -->
        <h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:0">Snap Engagement</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="background:#f8f8f8"><th style="padding:8px 10px;text-align:left"></th><th style="padding:8px 10px;text-align:center">All Time</th><th style="padding:8px 10px;text-align:center">Yesterday</th><th style="padding:8px 10px;text-align:center">This Week</th></tr>
            <tr><td style="padding:6px 10px">Total Interactions</td><td style="padding:6px 10px;font-weight:bold;text-align:center">{ss['total_interactions']}</td><td style="padding:6px 10px;font-weight:bold;text-align:center">{ss.get('daily_delta_interactions') if ss.get('daily_delta_interactions') is not None else '—'}</td><td style="padding:6px 10px;font-weight:bold;text-align:center">{ss.get('weekly_delta_interactions') if ss.get('weekly_delta_interactions') is not None else '—'}</td></tr>
            <tr><td style="padding:6px 10px">Unique Budtenders</td><td style="padding:6px 10px;font-weight:bold;text-align:center">{ss['unique_employees']}</td><td style="padding:6px 10px;font-weight:bold;text-align:center">{ss.get('daily_delta_employees') if ss.get('daily_delta_employees') is not None else '—'}</td><td style="padding:6px 10px;font-weight:bold;text-align:center">{ss.get('weekly_delta_employees') if ss.get('weekly_delta_employees') is not None else '—'}</td></tr>
            <tr><td style="padding:6px 10px">Unique Retailers</td><td style="padding:6px 10px;font-weight:bold;text-align:center">{ss['unique_retailers']}</td><td colspan="2"></td></tr>
            <tr><td style="padding:6px 10px">Published Snaps</td><td style="padding:6px 10px;font-weight:bold;text-align:center">{ss['total_snaps']}</td><td colspan="2"></td></tr>
        </table>

        <!-- SNAP PERFORMANCE -->
        {snap_perf_html}

        <!-- TRAINING COURSES -->
        {"" if not insights.get("course_completed") and not insights.get("course_in_progress") else f'''<h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:30px">Training Course Progress</h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
            <tr style="background:#1a3c2e;color:#ffffff"><th style="padding:6px 10px;text-align:left">Budtender</th><th style="padding:6px 10px;text-align:left">Retailer</th><th style="padding:6px 10px;text-align:center">Status</th><th style="padding:6px 10px;text-align:center">Incentive</th></tr>
            {"".join(f'<tr style="background:#f0f7f4"><td style="padding:5px 10px;border-bottom:1px solid #eee">{r.get("name","?")}</td><td style="padding:5px 10px;border-bottom:1px solid #eee">{r.get("retailer","?")}</td><td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center;color:#27ae60;font-weight:bold">Completed</td><td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">{r.get("incentive_status","")}</td></tr>' for r in insights.get("course_completed", []))}
            {"".join(f'<tr><td style="padding:5px 10px;border-bottom:1px solid #eee">{r.get("name","?")}</td><td style="padding:5px 10px;border-bottom:1px solid #eee">{r.get("retailer","?")}</td><td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center;color:#e67e22">In Progress (p{r.get("page",0)+1})</td><td style="padding:5px 10px;border-bottom:1px solid #eee;text-align:center">—</td></tr>' for r in insights.get("course_in_progress", []))}
        </table>
        <p style="font-size:12px;color:#666;margin-top:5px">Total: {len(insights.get("course_completed",[]))} completed, {len(insights.get("course_in_progress",[]))} in progress</p>'''}

        <!-- SPARKPLUG SALES -->
        <h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:30px">Sparkplug Sales</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="background:#1a3c2e;color:#ffffff"><th style="padding:8px 10px;text-align:left">Retailer</th><th style="padding:8px 10px;text-align:center">7d</th><th style="padding:8px 10px;text-align:center">30d</th><th style="padding:8px 10px;text-align:center">90d</th></tr>
            {sales_rows}
        </table>

        <!-- BUDTENDER LEADERBOARD -->
        {"" if not leaderboard_rows else f'''<h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:30px">Budtender Leaderboard (Snap Engagement)</h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
            <tr style="background:#1a3c2e;color:#ffffff"><th style="padding:6px 10px">Rank</th><th style="padding:6px 10px;text-align:left">Budtender</th><th style="padding:6px 10px;text-align:left">Retailer</th><th style="padding:6px 10px;text-align:center">Views</th><th style="padding:6px 10px;text-align:center">Completions</th><th style="padding:6px 10px;text-align:center">CTAs</th><th style="padding:6px 10px;text-align:center">Rate</th></tr>
            {leaderboard_rows}
        </table>'''}

        <!-- DEAL PIPELINE -->
        <h2 style="color:#1a3c2e;border-bottom:2px solid #c8a45a;padding-bottom:8px;margin-top:30px">Deal Pipeline</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="background:#f8f8f8"><th style="padding:8px 10px;text-align:left">Stage</th><th style="padding:8px 10px;text-align:center">Deals</th><th style="padding:8px 10px;text-align:right">Value</th></tr>
            {pipeline_rows}
            <tr style="background:#1a3c2e;color:#ffffff"><td style="padding:8px 10px;font-weight:bold">Total</td><td style="padding:8px 10px;text-align:center;font-weight:bold">{insights['hs_total_deals']}</td><td style="padding:8px 10px;text-align:right;font-weight:bold">${insights['hs_total_value']:,.2f}</td></tr>
        </table>

        <!-- CTA RESPONSES -->
        {cta_section}

        <div style="margin-top:30px;padding-top:15px;border-top:1px solid #eee;color:#888;font-size:11px">
            Atomic Fungi Daily Intel — Generated automatically from Sparkplug, HubSpot, and Gmail data
        </div>
    </div>
</body>
</html>"""
    return html


def send_email_func(subject: str, html_body: str, recipients: list[str], dry_run: bool = False, cc: list[str] = None, filename: str = None):
    fname = filename or f"daily_intel_{datetime.now().strftime('%Y%m%d')}.html"
    report_path = EXPORTS_DIR / fname
    report_path.write_text(html_body, encoding="utf-8")
    print(f"  Report saved to {report_path}")
    if dry_run:
        print(f"  [DRY RUN] Email not sent. To: {recipients}{f' CC: {cc}' if cc else ''}")
        return
    from gmail_sender import send_email
    success = send_email(to=recipients, subject=subject, html_body=html_body, cc=cc)
    if not success:
        print(f"  Email failed — report saved at {report_path}")


def main():
    dry_run = "--dry-run" in sys.argv
    chat_only = "--chat-only" in sys.argv

    print(f"=== Atomic Fungi Daily Intel Pipeline ===")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    # Step 0: Inbox cleanup
    print("[0/7] Cleaning inbox...")
    if not dry_run:
        try:
            from email_utils import get_gmail_service
            svc = get_gmail_service()

            # Trash promotions + social
            for q in ["category:promotions", "category:social"]:
                ids = []
                pt = None
                while True:
                    r = svc.users().messages().list(userId="me", q=q, maxResults=500, pageToken=pt).execute()
                    ids.extend([m["id"] for m in r.get("messages", [])])
                    pt = r.get("nextPageToken")
                    if not pt:
                        break
                if ids:
                    for i in range(0, len(ids), 100):
                        svc.users().messages().batchModify(userId="me", body={"ids": ids[i:i+100], "addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX", "UNREAD"]}).execute()
                    print(f"  Trashed {len(ids)} {q.split(':')[1]} emails")

            # Trash known junk domains
            junk_domains = ["redditmail.com", "protect.mcafee.com", "filterkingf.co", "goproqpilot.co",
                            "tuliprivergroup.info", "radiinomy.org", "admetricks.com", "reorderflows.com",
                            "asknutramarketers.com", "adaptwithspring.com", "saasaccountingpro.co",
                            "marketing.base44.com", "newquestex.com"]
            for domain in junk_domains:
                r = svc.users().messages().list(userId="me", q=f"from:{domain} in:inbox", maxResults=100).execute()
                ids = [m["id"] for m in r.get("messages", [])]
                if ids:
                    svc.users().messages().batchModify(userId="me", body={"ids": ids, "addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX", "UNREAD"]}).execute()
        except Exception as e:
            print(f"  Cleanup error: {e}")
    else:
        print("  [DRY RUN] skipped")
    print()

    # Step 1: Export
    print("[1/7] Exporting fresh data...")
    try:
        from export_data import run_export
        run_export()
    except Exception as e:
        print(f"  Export failed: {e}")
        print("  Continuing with existing data...")
    print()

    # Step 2: Analyze
    print("[2/7] Analyzing data...")
    insights = analyze_data()
    print(f"  Retailers: {len(insights['retailers'])}")
    print(f"  Deals: {insights['hs_total_deals']} (${insights['hs_closed_won']:,.0f} closed won)")
    print(f"  Drafts: {insights['total_drafts']}")
    print(f"  Action items: {len(insights['action_items'])}")
    print()

    # Step 3: Google Chat
    print("[3/7] Posting to Google Chat...")
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

    # Step 4: Calendar events for high-priority action items
    print("[4/7] Creating calendar follow-ups...")
    high_priority = [a for a in insights["action_items"] if a["priority"] == "high" and a["category"] == "crm"]
    if high_priority:
        try:
            from email_utils import create_calendar_event
            tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
            for a in high_priority[:3]:  # Max 3 calendar events per day
                text = a["text"][:80]
                if dry_run:
                    print(f"  [DRY RUN] Would create event: {text}")
                else:
                    try:
                        event_id = create_calendar_event(
                            summary=f"AF Follow-Up: {text}",
                            description=f"Auto-generated by AF Daily Intel pipeline.\n\nFull action: {a['text']}",
                            start_date=tomorrow,
                        )
                        print(f"  Created: {text[:50]}... ({event_id})")
                    except Exception as e:
                        print(f"  Failed: {text[:50]}... ({e})")
        except ImportError:
            print("  Calendar not available (missing email_utils)")
    else:
        print("  No high-priority CRM items to schedule")
    print()

    # Step 5: Team email (no admin tasks)
    if not chat_only:
        print("[5/7] Sending team email...")
        subject = f"AF Daily Intel — {insights['date']} | ${insights['hs_closed_won']:,.0f} Closed Won | {insights['hs_total_deals']} Deals"
        html = format_email_html(insights)
        send_email_func(subject, html, RECIPIENTS, dry_run=dry_run)

        # Step 6: Admin nag email (label redesign, kitchen, compliance)
        admin_tasks = [t for t in insights.get("tasks", []) if t["status"] in ("open", "in_progress") and t.get("project") in ADMIN_PROJECTS]
        if admin_tasks:
            print("[6/7] Sending admin task nag email...")
            admin_rows = ""
            for t in sorted(admin_tasks, key=lambda x: (not x.get("overdue"), x.get("due") or "9999")):
                if t.get("overdue"):
                    bg = "background:#fde8e8;"
                    badge = f'<span style="color:#e74c3c;font-weight:bold">OVERDUE ({t["days_overdue"]}d)</span>'
                elif t["priority"] == "critical":
                    bg = "background:#fff3cd;"
                    badge = '<span style="color:#e67e22;font-weight:bold">CRITICAL</span>'
                else:
                    bg = ""
                    badge = t["priority"].upper()
                admin_rows += f'<tr style="{bg}"><td style="padding:6px 10px;border-bottom:1px solid #eee">{badge}</td><td style="padding:6px 10px;border-bottom:1px solid #eee">{t["title"]}</td><td style="padding:6px 10px;border-bottom:1px solid #eee">{t.get("due","")}</td></tr>'
            overdue_admin = [t for t in admin_tasks if t.get("overdue")]
            admin_html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
    <div style="background:#1a3c2e;padding:20px;border-radius:8px 8px 0 0">
        <h1 style="color:#c8a45a;margin:0;font-size:20px">AF Admin Tasks</h1>
        <p style="color:#fff;margin:5px 0 0 0;font-size:13px">{insights['date']}</p>
    </div>
    <div style="background:#fff;padding:20px;border-radius:0 0 8px 8px">
        <h2 style="color:{'#e74c3c' if overdue_admin else '#1a3c2e'};border-bottom:2px solid {'#e74c3c' if overdue_admin else '#c8a45a'};padding-bottom:8px">
            {len(admin_tasks)} Admin Tasks{f' / {len(overdue_admin)} OVERDUE' if overdue_admin else ''}
        </h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
            <tr style="background:#f8f8f8"><th style="padding:6px 10px;text-align:left">Priority</th><th style="padding:6px 10px;text-align:left">Task</th><th style="padding:6px 10px">Due</th></tr>
            {admin_rows}
        </table>
        <p style="color:#888;font-size:11px;margin-top:20px">This email is sent only to admin. Team does not see these tasks.</p>
    </div>
</body></html>"""
            admin_subject = f"AF Admin Tasks — {insights['date']}{' — OVERDUE' if overdue_admin else ''}"
            send_email_func(admin_subject, admin_html, ADMIN_RECIPIENTS, dry_run=dry_run, cc=ADMIN_CC, filename=f"admin_tasks_{datetime.now().strftime('%Y%m%d')}.html")
        else:
            print("[6/7] No admin tasks to nag")
    else:
        print("[5/7] Email skipped (--chat-only)")

    print("\n=== Pipeline complete ===")


if __name__ == "__main__":
    main()
