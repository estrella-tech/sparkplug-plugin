#!/usr/bin/env python3
"""
Sparkplug + HubSpot + Gmail Data Exporter — runs locally.
Exports fresh data to exports/ for the daily intel pipeline.

Usage:
    python scripts/export_data.py          # export all data
    python scripts/export_data.py --push   # export + git commit & push
"""

import csv
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "servers"))
from client import SparkplugClient

PROJECT_ROOT = Path(__file__).parent.parent
EXPORT_DIR = PROJECT_ROOT / "exports"
CONFIG_DIR = Path.home() / ".sparkplug"


def export_json(name: str, data, metadata: dict = None):
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"exported_at": datetime.now(timezone.utc).isoformat(), "data": data}
    if metadata:
        payload["metadata"] = metadata
    path = EXPORT_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"  Exported {path.name} ({len(data) if isinstance(data, list) else 'object'})")


def export_csv_file(name: str, rows: list[dict], fieldnames: list[str]):
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / f"{name}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Exported {path.name} ({len(rows)} rows)")


def export_sparkplug():
    """Export all Sparkplug data."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    quarter_ago = (now - timedelta(days=90)).strftime("%Y-%m-%d")

    client = SparkplugClient()

    print("[Sparkplug] Fetching retailers...")
    retailers = client.get_retailers()
    export_json("retailers", retailers)

    print("[Sparkplug] Fetching sales totals per retailer...")
    sales_summary = []
    for r in retailers:
        rid = r.get("accountId")
        rname = r.get("accountName", rid)
        if not rid:
            continue
        for label, start in [("7d", week_ago), ("30d", month_ago), ("90d", quarter_ago)]:
            try:
                data = client.get_sales_totals(rid, start, today)
                sales_summary.append({"retailer_id": rid, "retailer_name": rname, "period": label, "date_start": start, "date_end": today, "data": data})
            except Exception as e:
                print(f"    Warning: sales totals failed for {rname} ({label}): {e}")
    export_json("sales_totals", sales_summary)

    print("[Sparkplug] Fetching sales trends...")
    sales_trends = []
    for r in retailers:
        rid = r.get("accountId")
        rname = r.get("accountName", rid)
        if not rid:
            continue
        try:
            data = client.get_sales_buckets(rid, month_ago, today, "weekly")
            sales_trends.append({"retailer_id": rid, "retailer_name": rname, "date_start": month_ago, "date_end": today, "frequency": "weekly", "data": data})
        except Exception as e:
            print(f"    Warning: sales trend failed for {rname}: {e}")
    export_json("sales_trends", sales_trends)

    print("[Sparkplug] Fetching budtender performance...")
    budtender_data = []
    for r in retailers:
        rid = r.get("accountId")
        rname = r.get("accountName", rid)
        if not rid:
            continue
        try:
            data = client.get_budtender_performance(rid, month_ago, today)
            budtender_data.append({"retailer_id": rid, "retailer_name": rname, "date_start": month_ago, "date_end": today, "data": data})
        except Exception as e:
            print(f"    Warning: budtender perf failed for {rname}: {e}")
    export_json("budtender_performance", budtender_data)

    print("[Sparkplug] Fetching Snaps...")
    snaps = client.get_snaps_list()
    export_json("snaps", snaps)

    print("[Sparkplug] Fetching Snap engagement...")
    engagement_rows = []
    for snap in snaps:
        snap_id = snap.get("storifymeSnapId")
        snap_name = snap.get("name", str(snap_id))
        if not snap_id:
            continue
        try:
            rows = client.get_snap_engagement(str(snap_id))
            for row in rows:
                engagement_rows.append({
                    "snap_name": snap_name, "snap_id": snap_id,
                    "Employee": row.get("Employee", ""), "Retailer": row.get("Retailer", ""),
                    "Location": row.get("Location", ""), "Action": row.get("Action", ""),
                    "Slide": row.get("Slide", ""), "Total Slides": row.get("Total Slides", ""),
                })
        except Exception:
            pass
    export_csv_file("snap_engagement", engagement_rows,
                     ["snap_name", "snap_id", "Employee", "Retailer", "Location", "Action", "Slide", "Total Slides"])
    # Aggregate per-budtender leaderboard
    bt_stats = {}
    for row in engagement_rows:
        emp = row.get("Employee", "").strip()
        retailer = row.get("Retailer", "").strip()
        action = row.get("Action", "").strip()
        if not emp:
            continue
        key = f"{emp}||{retailer}"
        if key not in bt_stats:
            bt_stats[key] = {"name": emp, "retailer": retailer, "views": 0, "completions": 0, "ctas": 0, "total": 0}
        if action == "Story Started":
            bt_stats[key]["views"] += 1
        elif action == "Story Complete":
            bt_stats[key]["completions"] += 1
        elif action == "Story Text Question Answer":
            bt_stats[key]["ctas"] += 1
        bt_stats[key]["total"] = bt_stats[key]["views"] + bt_stats[key]["completions"] + bt_stats[key]["ctas"]

    leaderboard = sorted(bt_stats.values(), key=lambda x: x["total"], reverse=True)

    export_json("snap_engagement_summary", {
        "total_interactions": len(engagement_rows),
        "unique_employees": len({r["Employee"] for r in engagement_rows if r["Employee"]}),
        "unique_retailers": len({r["Retailer"] for r in engagement_rows if r["Retailer"]}),
        "snaps_with_data": len({r["snap_name"] for r in engagement_rows}),
    })
    export_json("budtender_leaderboard", leaderboard[:50])


def export_hubspot():
    """Export HubSpot deals, companies, contacts."""
    token_path = CONFIG_DIR / "hubspot_token.txt"
    if not token_path.exists():
        print("[HubSpot] No token found, skipping.")
        return

    token = token_path.read_text().strip()
    from hubspot import HubSpot
    hs = HubSpot(access_token=token)

    # Deal stages mapping
    stage_labels = {
        "appointmentscheduled": "Hot Lead",
        "qualifiedtobuy": "Contacted",
        "presentationscheduled": "Sampled",
        "decisionmakerboughtin": "Tasting Done",
        "contractsent": "Verbal Commitment",
        "3335917290": "First Order Placed",
        "closedwon": "Closed Won",
        "closedlost": "Closed Lost",
    }

    # Deals
    print("[HubSpot] Fetching deals...")
    all_deals = []
    after = None
    while True:
        page = hs.crm.deals.basic_api.get_page(
            limit=100, after=after,
            properties=["dealname", "amount", "dealstage", "closedate", "pipeline", "hubspot_owner_id", "createdate"]
        )
        for d in page.results:
            props = d.properties
            all_deals.append({
                "id": d.id,
                "name": props.get("dealname", ""),
                "amount": float(props.get("amount") or 0),
                "stage": props.get("dealstage", ""),
                "stage_label": stage_labels.get(props.get("dealstage", ""), props.get("dealstage", "")),
                "closedate": props.get("closedate", ""),
                "createdate": props.get("createdate", ""),
                "owner_id": props.get("hubspot_owner_id", ""),
            })
        if page.paging and page.paging.next:
            after = page.paging.next.after
        else:
            break
    export_json("hubspot_deals", all_deals)

    # Pipeline summary
    pipeline = {}
    total_value = 0
    closed_won_value = 0
    for d in all_deals:
        label = d["stage_label"]
        pipeline.setdefault(label, {"count": 0, "value": 0})
        pipeline[label]["count"] += 1
        pipeline[label]["value"] += d["amount"]
        total_value += d["amount"]
        if d["stage"] == "closedwon":
            closed_won_value += d["amount"]

    export_json("hubspot_pipeline_summary", {
        "total_deals": len(all_deals),
        "total_value": total_value,
        "closed_won_value": closed_won_value,
        "by_stage": pipeline,
        "stage_order": list(stage_labels.values()),
    })

    # Companies
    print("[HubSpot] Fetching companies...")
    all_companies = []
    after = None
    while True:
        page = hs.crm.companies.basic_api.get_page(
            limit=100, after=after,
            properties=["name", "domain", "notes_last_contacted", "notes_last_updated", "num_associated_contacts", "num_associated_deals"]
        )
        for c in page.results:
            props = c.properties
            all_companies.append({
                "id": c.id,
                "name": props.get("name", ""),
                "domain": props.get("domain", ""),
                "last_contacted": props.get("notes_last_contacted", ""),
                "last_updated": props.get("notes_last_updated", ""),
                "num_contacts": int(props.get("num_associated_contacts") or 0),
                "num_deals": int(props.get("num_associated_deals") or 0),
            })
        if page.paging and page.paging.next:
            after = page.paging.next.after
        else:
            break
    export_json("hubspot_companies", all_companies)


def export_gmail_drafts():
    """Count Gmail drafts using existing OAuth2 token."""
    token_path = CONFIG_DIR / "gmail_token.json"
    creds_path = CONFIG_DIR / "gmail_credentials.json"
    if not token_path.exists() or not creds_path.exists():
        print("[Gmail] No OAuth2 token found, skipping draft count.")
        return

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose"]
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        service = build("gmail", "v1", credentials=creds)

        # Get draft list
        drafts_resp = service.users().drafts().list(userId="me", maxResults=500).execute()
        drafts = drafts_resp.get("drafts", [])
        total_drafts = len(drafts)

        # Get details for recent drafts
        draft_details = []
        for draft in drafts[:30]:
            try:
                msg = service.users().drafts().get(userId="me", id=draft["id"], format="metadata",
                                                     metadataHeaders=["To", "Subject", "Date"]).execute()
                headers = {h["name"]: h["value"] for h in msg.get("message", {}).get("payload", {}).get("headers", [])}
                draft_details.append({
                    "to": headers.get("To", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                })
            except Exception:
                pass

        export_json("gmail_drafts", {
            "total_drafts": total_drafts,
            "recent_drafts": draft_details,
        })
        print(f"  Exported gmail_drafts.json ({total_drafts} drafts)")
    except Exception as e:
        print(f"[Gmail] Draft export failed: {e}")


def export_chat_messages():
    """Read recent messages from all AF Google Chat spaces."""
    token_path = CONFIG_DIR / "gmail_token.json"
    creds_path = CONFIG_DIR / "gmail_credentials.json"
    if not token_path.exists() or not creds_path.exists():
        print("[Chat] No OAuth2 token found, skipping.")
        return

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        SCOPES = [
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/chat.spaces.readonly",
            "https://www.googleapis.com/auth/chat.messages.readonly",
        ]
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        chat = build("chat", "v1", credentials=creds)

        spaces_map = {
            "AAQAp0pxBP8": "AF - Team Chat",
            "AAQAO26pLzI": "AF - CRM",
            "AAQAuAbDFSQ": "AF - Digital Marketing",
            "AAQAo3Jic_4": "AF - Sample Requests",
        }

        all_messages = []
        for space_id, space_name in spaces_map.items():
            try:
                msgs = chat.spaces().messages().list(
                    parent=f"spaces/{space_id}", pageSize=50
                ).execute()
                for m in msgs.get("messages", []):
                    sender = m.get("sender", {}).get("displayName", "Unknown")
                    text = m.get("text", "") or ""
                    created = m.get("createTime", "")
                    all_messages.append({
                        "space": space_name,
                        "space_id": space_id,
                        "sender": sender,
                        "text": text,
                        "created": created,
                    })
            except Exception as e:
                print(f"  Warning: failed to read {space_name}: {e}")

        # Extract store visit mentions
        visit_keywords = ["visited", "stopped by", "went to", "dropped off", "sampling event", "tasting"]
        store_visits = []
        for msg in all_messages:
            text_lower = msg["text"].lower()
            if any(kw in text_lower for kw in visit_keywords):
                store_visits.append(msg)

        export_json("chat_messages", {
            "total_messages": len(all_messages),
            "messages": all_messages,
            "store_visits": store_visits,
        })
        print(f"  Exported chat_messages.json ({len(all_messages)} messages, {len(store_visits)} store visits)")
    except Exception as e:
        print(f"[Chat] Export failed: {e}")


def run_export():
    now = datetime.now(timezone.utc)
    print(f"=== Data Export — {now.strftime('%Y-%m-%d %H:%M UTC')} ===\n")

    export_sparkplug()
    print()
    export_hubspot()
    print()
    export_gmail_drafts()
    print()
    export_chat_messages()

    # Write manifest
    export_json("_manifest", {
        "export_date": now.strftime("%Y-%m-%d"),
        "export_timestamp": now.isoformat(),
    })

    print(f"\nDone! Exported to {EXPORT_DIR.resolve()}")
    return True


def git_push():
    repo_dir = Path(__file__).parent.parent
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        subprocess.run(["git", "add", "exports/"], cwd=repo_dir, check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo_dir, capture_output=True)
        if result.returncode == 0:
            print("No changes to commit.")
            return
        subprocess.run(["git", "commit", "-m", f"Daily data export — {today}"], cwd=repo_dir, check=True)
        subprocess.run(["git", "push"], cwd=repo_dir, check=True)
        print("Pushed to GitHub.")
    except subprocess.CalledProcessError as e:
        print(f"Git error: {e}", file=sys.stderr)


if __name__ == "__main__":
    success = run_export()
    if success and "--push" in sys.argv:
        git_push()
