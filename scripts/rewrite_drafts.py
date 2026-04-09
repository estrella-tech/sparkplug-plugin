#!/usr/bin/env python3
"""
Rewrite outreach email drafts using Gemini + Sparkplug/HubSpot enrichment data.
Creates NEW drafts (originals preserved) with Giovanni's personal tone.

Usage:
    python scripts/rewrite_drafts.py --dry-run --limit 3   # preview first 3
    python scripts/rewrite_drafts.py --limit 10             # rewrite first 10
    python scripts/rewrite_drafts.py                        # rewrite all
"""

import base64
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from email.utils import parseaddr

sys.path.insert(0, str(Path(__file__).parent))
from email_utils import (
    get_gmail_service, generate_with_gemini, load_enrichment_data,
    match_company, create_gmail_draft, load_prompt_template, EXPORTS_DIR,
)


def fetch_all_drafts(service, limit: int = None) -> list[dict]:
    """Fetch all drafts with headers and body."""
    print("  Fetching draft list...")
    drafts_resp = service.users().drafts().list(userId="me", maxResults=500).execute()
    draft_ids = drafts_resp.get("drafts", [])
    if limit:
        draft_ids = draft_ids[:limit]

    print(f"  Loading {len(draft_ids)} drafts...")
    drafts = []
    for i, d in enumerate(draft_ids):
        try:
            full = service.users().drafts().get(userId="me", id=d["id"], format="full").execute()
            msg = full.get("message", {})
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

            # Extract body
            body_text = ""
            payload = msg.get("payload", {})
            if payload.get("body", {}).get("data"):
                body_text = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
            else:
                for part in payload.get("parts", []):
                    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                        body_text = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                        break

            to = headers.get("To", "")
            _, to_email = parseaddr(to)
            to_name = to.split("<")[0].strip().strip('"') if "<" in to else ""

            drafts.append({
                "draft_id": d["id"],
                "to": to,
                "to_email": to_email,
                "to_name": to_name,
                "subject": headers.get("Subject", ""),
                "body": body_text,
                "date": headers.get("Date", ""),
            })

            if (i + 1) % 20 == 0:
                print(f"    Loaded {i + 1}/{len(draft_ids)}...")
        except Exception as e:
            print(f"    Warning: failed to load draft {d['id']}: {e}")

    return drafts


def build_rewrite_prompt(draft: dict, context: dict, system_prompt: str, gold_standard: str) -> str:
    """Build the full prompt for Gemini."""
    parts = [system_prompt, "\n\n--- GOLD STANDARD EMAIL (match this tone) ---\n", gold_standard]

    # Add enrichment context
    parts.append("\n\n--- CONTEXT FOR THIS EMAIL ---\n")
    parts.append(f"Recipient: {draft['to_name'] or draft['to_email']}")
    parts.append(f"Their email: {draft['to_email']}")
    parts.append(f"Original subject: {draft['subject']}")

    if context["company"]:
        c = context["company"]
        parts.append(f"\nCompany: {c.get('name', 'Unknown')}")
        parts.append(f"Domain: {c.get('domain', 'N/A')}")
        last = c.get("last_contacted", "")
        parts.append(f"Last contacted: {last or 'Never'}")
        parts.append(f"Active deals: {c.get('num_deals', 0)}")

    if context["deal_stage"]:
        parts.append(f"Current deal stage: {context['deal_stage']}")

    if context["budtenders"]:
        parts.append("\nBudtender engagement at this location:")
        for bt in context["budtenders"][:3]:
            parts.append(f"  - {bt['name']}: {bt['views']} views, {bt['completions']} completions, {bt['ctas']} quiz answers")

    parts.append(f"\n\n--- ORIGINAL DRAFT TO REWRITE ---\n{draft['body'][:2000]}")
    parts.append("\n\n--- YOUR REWRITE ---")

    return "\n".join(parts)


def main():
    dry_run = "--dry-run" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        limit = int(sys.argv[idx + 1])
    skip_existing = "--skip-existing" in sys.argv

    print(f"=== Outreach Draft Rewriter ===")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    if limit:
        print(f"Limit: {limit} drafts")
    print()

    # Load log of already-rewritten drafts
    log_path = EXPORTS_DIR / "rewrite_log.json"
    existing_log = []
    if log_path.exists() and skip_existing:
        existing_log = json.loads(log_path.read_text())
    rewritten_ids = {entry["original_draft_id"] for entry in existing_log}

    # Load templates
    system_prompt = load_prompt_template("rewrite_prompt.txt")
    gold_standard = load_prompt_template("gold_standard_email.txt")

    # Load enrichment data
    print("[1/4] Loading enrichment data...")
    enrichment = load_enrichment_data()
    print(f"  Companies: {len(enrichment['companies_by_name'])}")
    print(f"  Retailers with budtenders: {len(enrichment['budtenders_by_retailer'])}")
    print()

    # Fetch drafts
    print("[2/4] Fetching Gmail drafts...")
    service = get_gmail_service()
    drafts = fetch_all_drafts(service, limit=limit)

    # Filter out non-outreach drafts (skip internal emails, daily intel drafts, etc.)
    outreach_drafts = []
    skip_subjects = ["af daily intel", "daily intel", "test"]
    skip_domains = ["atomicfungi.com", "gmail.com"]  # skip internal
    for d in drafts:
        subj_lower = d["subject"].lower()
        domain = d["to_email"].split("@")[-1].lower() if "@" in d["to_email"] else ""
        if any(s in subj_lower for s in skip_subjects):
            continue
        if domain in skip_domains:
            continue
        if skip_existing and d["draft_id"] in rewritten_ids:
            continue
        outreach_drafts.append(d)

    print(f"  Total drafts: {len(drafts)}")
    print(f"  Outreach drafts to rewrite: {len(outreach_drafts)}")
    print()

    # Rewrite each
    print("[3/4] Rewriting drafts...")
    results = []
    for i, draft in enumerate(outreach_drafts):
        print(f"\n  [{i+1}/{len(outreach_drafts)}] {draft['subject'][:60]}")
        print(f"    To: {draft['to_email']}")

        # Match to enrichment data
        context = match_company(draft["to_email"], draft["subject"], draft["body"], enrichment)
        company_name = context["company"]["name"] if context["company"] else "No match"
        print(f"    Company: {company_name}")
        if context["budtenders"]:
            names = ", ".join(bt["name"] for bt in context["budtenders"][:3])
            print(f"    Budtenders: {names}")
        if context["deal_stage"]:
            print(f"    Deal stage: {context['deal_stage']}")

        # Build prompt and generate
        prompt = build_rewrite_prompt(draft, context, system_prompt, gold_standard)

        if dry_run:
            print(f"    [DRY RUN] Would call Gemini with {len(prompt)} char prompt")
            results.append({
                "original_draft_id": draft["draft_id"],
                "to": draft["to_email"],
                "subject": draft["subject"],
                "company": company_name,
                "budtenders": [bt["name"] for bt in context["budtenders"][:3]],
                "deal_stage": context["deal_stage"],
                "status": "dry_run",
            })
            continue

        try:
            rewritten = generate_with_gemini(prompt)
            print(f"    Generated {len(rewritten)} chars")

            # Create new draft
            new_subject = draft["subject"]  # Keep original subject
            new_draft_id = create_gmail_draft(service, draft["to"], new_subject, rewritten)
            print(f"    Created new draft: {new_draft_id}")

            results.append({
                "original_draft_id": draft["draft_id"],
                "new_draft_id": new_draft_id,
                "to": draft["to_email"],
                "subject": draft["subject"],
                "company": company_name,
                "status": "rewritten",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            time.sleep(4.5)  # Stay under 15 RPM free tier limit

        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({
                "original_draft_id": draft["draft_id"],
                "to": draft["to_email"],
                "subject": draft["subject"],
                "status": f"error: {e}",
            })

    # Save log
    print(f"\n[4/4] Saving results...")
    all_results = existing_log + results
    log_path.write_text(json.dumps(all_results, indent=2))
    print(f"  Log saved to {log_path}")

    # Summary
    rewritten = sum(1 for r in results if r.get("status") == "rewritten")
    errors = sum(1 for r in results if r.get("status", "").startswith("error"))
    dry = sum(1 for r in results if r.get("status") == "dry_run")
    print(f"\n=== Summary ===")
    print(f"  Rewritten: {rewritten}")
    print(f"  Errors: {errors}")
    print(f"  Dry run: {dry}")


if __name__ == "__main__":
    main()
