#!/usr/bin/env python3
"""
Sparkplug Data Exporter — runs locally, exports fresh data to exports/ for the remote agent.

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

# Add servers/ to path so we can import the client
sys.path.insert(0, str(Path(__file__).parent.parent / "servers"))
from client import SparkplugClient

EXPORT_DIR = Path(__file__).parent.parent / "exports"


def export_json(name: str, data, metadata: dict = None):
    """Write data to exports/<name>.json with metadata."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    if metadata:
        payload["metadata"] = metadata
    path = EXPORT_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"  Exported {path.name} ({len(data) if isinstance(data, list) else 'object'})")


def export_csv_file(name: str, rows: list[dict], fieldnames: list[str]):
    """Write rows to exports/<name>.csv."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / f"{name}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Exported {path.name} ({len(rows)} rows)")


def run_export():
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    quarter_ago = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")

    print(f"Sparkplug Data Export — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Date ranges: yesterday={yesterday}, 7d={week_ago}, 30d={month_ago}, 90d={quarter_ago}")
    print()

    client = SparkplugClient()

    # 1. Retailers
    print("[1/6] Fetching retailers...")
    retailers = client.get_retailers()
    export_json("retailers", retailers)

    # 2. Sales totals per retailer (7d, 30d, 90d)
    print("[2/6] Fetching sales totals per retailer...")
    sales_summary = []
    for r in retailers:
        rid = r.get("accountId")
        rname = r.get("accountName", rid)
        if not rid:
            continue
        for label, start in [("7d", week_ago), ("30d", month_ago), ("90d", quarter_ago)]:
            try:
                data = client.get_sales_totals(rid, start, today)
                sales_summary.append({
                    "retailer_id": rid,
                    "retailer_name": rname,
                    "period": label,
                    "date_start": start,
                    "date_end": today,
                    "data": data,
                })
            except Exception as e:
                print(f"    Warning: sales totals failed for {rname} ({label}): {e}")
    export_json("sales_totals", sales_summary)

    # 3. Sales trend (weekly buckets, 30d) per retailer
    print("[3/6] Fetching sales trends...")
    sales_trends = []
    for r in retailers:
        rid = r.get("accountId")
        rname = r.get("accountName", rid)
        if not rid:
            continue
        try:
            data = client.get_sales_buckets(rid, month_ago, today, "weekly")
            sales_trends.append({
                "retailer_id": rid,
                "retailer_name": rname,
                "date_start": month_ago,
                "date_end": today,
                "frequency": "weekly",
                "data": data,
            })
        except Exception as e:
            print(f"    Warning: sales trend failed for {rname}: {e}")
    export_json("sales_trends", sales_trends)

    # 4. Budtender performance (30d) per retailer
    print("[4/6] Fetching budtender performance...")
    budtender_data = []
    for r in retailers:
        rid = r.get("accountId")
        rname = r.get("accountName", rid)
        if not rid:
            continue
        try:
            data = client.get_budtender_performance(rid, month_ago, today)
            budtender_data.append({
                "retailer_id": rid,
                "retailer_name": rname,
                "date_start": month_ago,
                "date_end": today,
                "data": data,
            })
        except Exception as e:
            print(f"    Warning: budtender perf failed for {rname}: {e}")
    export_json("budtender_performance", budtender_data)

    # 5. Snaps list
    print("[5/6] Fetching Snaps...")
    snaps = client.get_snaps_list()
    export_json("snaps", snaps)

    # 6. Snap engagement (all snaps)
    print("[6/6] Fetching Snap engagement...")
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
                    "snap_name": snap_name,
                    "snap_id": snap_id,
                    "Employee": row.get("Employee", ""),
                    "Retailer": row.get("Retailer", ""),
                    "Location": row.get("Location", ""),
                    "Action": row.get("Action", ""),
                    "Slide": row.get("Slide", ""),
                    "Total Slides": row.get("Total Slides", ""),
                })
        except Exception:
            pass
    export_csv_file(
        "snap_engagement",
        engagement_rows,
        ["snap_name", "snap_id", "Employee", "Retailer", "Location", "Action", "Slide", "Total Slides"],
    )
    export_json("snap_engagement_summary", {
        "total_events": len(engagement_rows),
        "unique_employees": len({r["Employee"] for r in engagement_rows if r["Employee"]}),
        "unique_retailers": len({r["Retailer"] for r in engagement_rows if r["Retailer"]}),
        "snaps_with_data": len({r["snap_name"] for r in engagement_rows}),
    })

    # Write manifest
    export_json("_manifest", {
        "export_date": today,
        "export_timestamp": now.isoformat(),
        "retailers_count": len(retailers),
        "snaps_count": len(snaps),
        "files": [
            "retailers.json", "sales_totals.json", "sales_trends.json",
            "budtender_performance.json", "snaps.json",
            "snap_engagement.csv", "snap_engagement_summary.json",
        ],
    })

    print(f"\nDone! Exported to {EXPORT_DIR.resolve()}")
    return True


def git_push():
    """Commit and push the exports."""
    repo_dir = Path(__file__).parent.parent
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        subprocess.run(["git", "add", "exports/"], cwd=repo_dir, check=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=repo_dir, capture_output=True
        )
        if result.returncode == 0:
            print("No changes to commit.")
            return
        subprocess.run(
            ["git", "commit", "-m", f"Daily Sparkplug data export — {today}"],
            cwd=repo_dir, check=True,
        )
        subprocess.run(["git", "push"], cwd=repo_dir, check=True)
        print("Pushed to GitHub.")
    except subprocess.CalledProcessError as e:
        print(f"Git error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    success = run_export()
    if success and "--push" in sys.argv:
        git_push()
