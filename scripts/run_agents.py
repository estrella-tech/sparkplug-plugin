#!/usr/bin/env python3
"""
Atomic Fungi Agent Runner — CLI for running individual agents or the full pipeline.

Usage:
    python scripts/run_agents.py inbox --dry-run       # Triage inbox
    python scripts/run_agents.py respond --dry-run     # Draft replies to starred emails
    python scripts/run_agents.py tasks --dry-run       # Task nag + email scan
    python scripts/run_agents.py all --dry-run         # Full pipeline: inbox → respond → tasks
    python scripts/run_agents.py all                   # Live run
"""

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows console encoding for emoji output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))


def run_inbox(dry_run: bool = False, limit: int = 30):
    print("=" * 60)
    print("INBOX AGENT — Triaging unread emails")
    print("=" * 60)
    from agents.inbox_agent import run
    result = run(max_emails=limit, dry_run=dry_run)
    print(result)
    print()
    return result


def run_respond(dry_run: bool = False):
    print("=" * 60)
    print("AUTO-RESPOND AGENT — Drafting replies to starred emails")
    print("=" * 60)
    from agents.auto_respond import run
    result = run(dry_run=dry_run)
    print(result)
    print()
    return result


def run_tasks(dry_run: bool = False, scan_emails: bool = True):
    print("=" * 60)
    print("TASK AGENT — Reviewing tasks and scanning for new ones")
    print("=" * 60)
    from agents.task_agent import run
    result = run(scan_emails=scan_emails, dry_run=dry_run)
    print(result)
    print()
    return result


def run_all(dry_run: bool = False):
    """Full agent pipeline: inbox triage → auto-respond → task management."""
    start = time.time()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'=' * 60}")
    print(f"ATOMIC FUNGI AGENT PIPELINE — {now}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'=' * 60}\n")

    results = {}

    # Stage 1: Inbox triage (stars actionable emails)
    print("[1/3] Running inbox agent...")
    results["inbox"] = run_inbox(dry_run=dry_run)

    # Stage 2: Auto-respond (processes starred emails from stage 1)
    print("[2/3] Running auto-respond agent...")
    results["respond"] = run_respond(dry_run=dry_run)

    # Stage 3: Task management (nags + scans recent emails for new tasks)
    print("[3/3] Running task agent...")
    results["tasks"] = run_tasks(dry_run=dry_run)

    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print(f"Pipeline complete in {elapsed:.1f}s")
    print(f"{'=' * 60}")

    return results


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    if not args:
        print(__doc__)
        return

    command = args[0]

    if command == "inbox":
        limit = 30
        if "--limit" in args:
            idx = args.index("--limit")
            limit = int(args[idx + 1])
        run_inbox(dry_run=dry_run, limit=limit)
    elif command == "respond":
        run_respond(dry_run=dry_run)
    elif command == "tasks":
        no_email = "--no-email-scan" in args
        run_tasks(dry_run=dry_run, scan_emails=not no_email)
    elif command == "research":
        limit = 5
        if "--limit" in args:
            idx = args.index("--limit")
            limit = int(args[idx + 1])
        print("=" * 60)
        print(f"RESEARCH AGENT — Finding social profiles {'(DRY RUN)' if dry_run else ''}")
        print("=" * 60)
        from agents.research_agent import run as run_research_fn
        # Build targets from Tasting Done / Sampled / Verbal Commitment deals
        import json
        from email_utils import load_enrichment_data, fuzzy_match
        enrichment = load_enrichment_data()
        deals = json.loads((Path(__file__).parent.parent / "exports" / "hubspot_deals.json").read_text()).get("data", [])
        apex = json.loads((Path(__file__).parent.parent / "exports" / "apex_contacts_deduped.json").read_text())
        target_stages = {"Tasting Done", "Sampled", "Verbal Commitment"}
        targets = []
        seen = set()
        for d in deals:
            if d.get("stage_label") in target_stages:
                name = d["name"].split("\u2014")[0].split("\u2013")[0].strip()
                if name.lower() in seen:
                    continue
                seen.add(name.lower())
                company = {"name": name}
                bt_key, _ = fuzzy_match(name, enrichment.get("budtenders_by_retailer", {}), threshold=0.4)
                if bt_key:
                    bt_data = enrichment["budtenders_by_retailer"][bt_key]
                    company["budtenders"] = sorted(bt_data.keys(), key=lambda x: sum(bt_data[x].values()), reverse=True)[:3]
                contacts = []
                for ac in apex:
                    for bn in ac.get("buyer_names", []):
                        if name.lower() in bn.lower() or bn.lower() in name.lower():
                            contacts.append({"name": ac.get("name", ""), "email": ac.get("email", ""), "title": ac.get("title", "")})
                            break
                if contacts:
                    company["contacts"] = contacts[:5]
                targets.append(company)
        targets = targets[:limit]
        print(f"Researching {len(targets)} companies\n")
        output = run_research_fn(targets, dry_run=dry_run)
        print(output)
    elif command == "all":
        run_all(dry_run=dry_run)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
