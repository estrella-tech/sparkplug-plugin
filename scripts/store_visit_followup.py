#!/usr/bin/env python3
"""
Generate follow-up email drafts after store visits.

Usage:
    python scripts/store_visit_followup.py "Cannabis Culture, Resinate, Embr"
    python scripts/store_visit_followup.py "Embr, Honey" --visitor Jared --tasting
    python scripts/store_visit_followup.py "Turning Leaf" --dry-run --notes "They loved the Focus Elixir"
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from email_utils import (
    get_gmail_service, generate_with_llm, load_enrichment_data,
    fuzzy_match, create_gmail_draft, load_prompt_template, EXPORTS_DIR,
)


def parse_args():
    """Parse command line arguments."""
    import argparse
    parser = argparse.ArgumentParser(description="Generate store visit follow-up email drafts")
    parser.add_argument("stores", help="Comma-separated list of store names")
    parser.add_argument("--visitor", default="our team", help="Who visited (default: 'our team')")
    parser.add_argument("--tasting", action="store_true", help="Flag that a tasting was done")
    parser.add_argument("--date", default=None, help="Visit date (default: today)")
    parser.add_argument("--notes", default="", help="Additional context per store")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating drafts")
    return parser.parse_args()


def lookup_store(store_name: str, enrichment: dict) -> dict:
    """Look up a store across all data sources."""
    context = {
        "store_name": store_name,
        "company": None,
        "deals": [],
        "deal_stage": None,
        "budtenders": [],
        "to_email": None,
    }

    # Match to HubSpot company
    key, score = fuzzy_match(store_name, enrichment["companies_by_name"])
    if key:
        context["company"] = enrichment["companies_by_name"][key]
        domain = context["company"].get("domain", "")
        if domain:
            context["to_email"] = f"info@{domain}"

    # Match deals
    key, _ = fuzzy_match(store_name, enrichment["deals_by_company"])
    if key:
        context["deals"] = enrichment["deals_by_company"][key]
        stage_order = ["Closed Won", "First Order Placed", "Verbal Commitment", "Tasting Done", "Sampled", "Contacted", "Hot Lead"]
        for stage in stage_order:
            for d in context["deals"]:
                if d.get("stage_label") == stage:
                    context["deal_stage"] = stage
                    break
            if context["deal_stage"]:
                break

    # Match budtenders
    key, _ = fuzzy_match(store_name, enrichment["budtenders_by_retailer"])
    if key:
        bt_data = enrichment["budtenders_by_retailer"][key]
        sorted_bts = sorted(bt_data.items(), key=lambda x: sum(x[1].values()), reverse=True)
        context["budtenders"] = [{"name": name, **stats} for name, stats in sorted_bts[:5]]

    return context


def build_followup_prompt(store_context: dict, visit_details: dict, system_prompt: str) -> str:
    """Build prompt for store visit follow-up."""
    parts = [system_prompt]

    parts.append(f"\n\n--- VISIT DETAILS ---")
    parts.append(f"Store: {store_context['store_name']}")
    parts.append(f"Visited by: {visit_details['visitor']}")
    parts.append(f"Visit date: {visit_details['date']}")
    parts.append(f"Tasting done: {'Yes' if visit_details['tasting'] else 'No'}")
    if visit_details.get("notes"):
        parts.append(f"Notes: {visit_details['notes']}")

    if store_context["company"]:
        c = store_context["company"]
        parts.append(f"\nCompany: {c.get('name', 'Unknown')}")
        parts.append(f"Domain: {c.get('domain', 'N/A')}")

    if store_context["deal_stage"]:
        parts.append(f"Current deal stage: {store_context['deal_stage']}")

    if store_context["budtenders"]:
        parts.append("\nBudtender engagement at this location:")
        for bt in store_context["budtenders"][:3]:
            parts.append(f"  - {bt['name']}: {bt['views']} views, {bt['completions']} completions")

    parts.append("\n\n--- WRITE THE FOLLOW-UP EMAIL ---")
    return "\n".join(parts)


def main():
    args = parse_args()

    stores = [s.strip() for s in args.stores.split(",") if s.strip()]
    visit_date = args.date or datetime.now().strftime("%B %d, %Y")

    print(f"=== Store Visit Follow-Up Generator ===")
    print(f"Stores: {', '.join(stores)}")
    print(f"Visitor: {args.visitor}")
    print(f"Tasting: {'Yes' if args.tasting else 'No'}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()

    # Load data
    print("[1/3] Loading enrichment data...")
    enrichment = load_enrichment_data()
    system_prompt = load_prompt_template("followup_prompt.txt")

    service = None
    if not args.dry_run:
        service = get_gmail_service()

    # Process each store
    print(f"\n[2/3] Generating follow-ups...")
    results = []

    for store_name in stores:
        print(f"\n  --- {store_name} ---")
        context = lookup_store(store_name, enrichment)

        company_name = context["company"]["name"] if context["company"] else "No HubSpot match"
        print(f"  Company: {company_name}")
        if context["to_email"]:
            print(f"  Email: {context['to_email']}")
        if context["budtenders"]:
            names = ", ".join(bt["name"] for bt in context["budtenders"][:3])
            print(f"  Budtenders: {names}")
        if context["deal_stage"]:
            print(f"  Deal stage: {context['deal_stage']}")

        visit_details = {
            "visitor": args.visitor,
            "date": visit_date,
            "tasting": args.tasting,
            "notes": args.notes,
        }

        prompt = build_followup_prompt(context, visit_details, system_prompt)

        if args.dry_run:
            print(f"  [DRY RUN] Would generate with {len(prompt)} char prompt")
            results.append({"store": store_name, "company": company_name, "status": "dry_run"})
            continue

        try:
            body = generate_with_llm(prompt)
            print(f"  Generated {len(body)} chars")

            to = context["to_email"] or f"info@{store_name.lower().replace(' ', '')}.com"
            subject = f"Great meeting your team — Atomic Fungi x {store_name}"
            draft_id = create_gmail_draft(service, to, subject, body)
            print(f"  Draft created: {draft_id}")

            results.append({
                "store": store_name,
                "company": company_name,
                "to": to,
                "draft_id": draft_id,
                "status": "created",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            time.sleep(1)  # Brief pause between API calls

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"store": store_name, "status": f"error: {e}"})

    # Save log
    print(f"\n[3/3] Saving results...")
    log_path = EXPORTS_DIR / "followup_log.json"
    existing = json.loads(log_path.read_text()) if log_path.exists() else []
    all_results = existing + results
    log_path.write_text(json.dumps(all_results, indent=2))

    created = sum(1 for r in results if r.get("status") == "created")
    print(f"\n=== Summary: {created} follow-up drafts created for {len(stores)} stores ===")


if __name__ == "__main__":
    main()
