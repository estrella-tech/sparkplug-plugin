#!/usr/bin/env python3
"""
Update HubSpot deal stages and create new deals for store visits.

Usage:
    python scripts/update_hubspot_deals.py --dry-run   # Preview changes
    python scripts/update_hubspot_deals.py              # Apply changes
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFIG_DIR = Path.home() / ".sparkplug"
EXPORTS_DIR = Path(__file__).parent.parent / "exports"

# HubSpot internal stage IDs
STAGE_IDS = {
    "Hot Lead": "appointmentscheduled",
    "Contacted": "qualifiedtobuy",
    "Sampled": "presentationscheduled",
    "Tasting Done": "decisionmakerboughtin",
    "Verbal Commitment": "contractsent",
    "First Order Placed": "3335917290",
    "Closed Won": "closedwon",
    "Closed Lost": "closedlost",
}

# Store visits to process — move to "Sampled"
STORE_VISITS = {
    # Giovanni's visits
    "Redi": {"visitor": "Giovanni", "deal_ids": ["316069598969"]},
    "Redi Natick": {"visitor": "Giovanni", "deal_ids": ["316279666385"]},
    "Garden Remedies": {"visitor": "Giovanni", "deal_ids": ["316130305769"]},
    "Apotho Therapeutics": {"visitor": "Giovanni", "deal_ids": ["316110530293"]},
    "NETA": {"visitor": "Giovanni", "deal_ids": []},  # needs new deal
    # Jared's visits
    "Cannabis Culture": {"visitor": "Jared", "deal_ids": []},
    "Resinate": {"visitor": "Jared", "deal_ids": []},
    "Embr": {"visitor": "Jared", "deal_ids": ["316057099988"]},
    "Fyre Ants": {"visitor": "Jared", "deal_ids": []},
    "Turning Leaf": {"visitor": "Jared", "deal_ids": []},
    "Honey": {"visitor": "Jared", "deal_ids": []},
    "Cheech and Chongs Dispensoria": {"visitor": "Jared", "deal_ids": []},
    "Liberty": {"visitor": "Jared", "deal_ids": []},
    "Dry Humor": {"visitor": "Jared", "deal_ids": []},
    # Giovanni's other visits (2nd locations)
    "Garden Remedies (2nd location)": {"visitor": "Giovanni", "deal_ids": []},
}

TARGET_STAGE = "Sampled"


def get_hubspot_client():
    token_path = CONFIG_DIR / "hubspot_token.txt"
    if not token_path.exists():
        raise RuntimeError(f"HubSpot token not found at {token_path}")
    token = token_path.read_text().strip()
    from hubspot import HubSpot
    return HubSpot(access_token=token)


def update_deal_stage(hs, deal_id: str, stage_label: str, dry_run: bool = False) -> bool:
    stage_id = STAGE_IDS[stage_label]
    if dry_run:
        print(f"  [DRY RUN] Would update deal {deal_id} to stage '{stage_label}' ({stage_id})")
        return True
    try:
        hs.crm.deals.basic_api.update(
            deal_id=deal_id,
            simple_public_object_input={"properties": {"dealstage": stage_id}}
        )
        print(f"  Updated deal {deal_id} to '{stage_label}'")
        return True
    except Exception as e:
        print(f"  ERROR updating deal {deal_id}: {e}")
        return False


def create_deal(hs, store_name: str, visitor: str, stage_label: str, dry_run: bool = False) -> str:
    stage_id = STAGE_IDS[stage_label]
    deal_name = f"{store_name} — AF Wholesale"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    properties = {
        "dealname": deal_name,
        "dealstage": stage_id,
        "pipeline": "default",
        "amount": "0",
    }
    if dry_run:
        print(f"  [DRY RUN] Would create deal: '{deal_name}' at stage '{stage_label}'")
        return "dry-run"
    try:
        from hubspot.crm.deals import SimplePublicObjectInputForCreate
        result = hs.crm.deals.basic_api.create(
            simple_public_object_input_for_create=SimplePublicObjectInputForCreate(properties=properties)
        )
        deal_id = result.id
        print(f"  Created deal: '{deal_name}' (ID: {deal_id}) at stage '{stage_label}'")
        return deal_id
    except Exception as e:
        print(f"  ERROR creating deal '{deal_name}': {e}")
        return ""


def main():
    dry_run = "--dry-run" in sys.argv
    print(f"=== HubSpot Deal Stage Updates ===")
    print(f"Target stage: {TARGET_STAGE}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Stores: {len(STORE_VISITS)}\n")

    hs = get_hubspot_client()
    updated = 0
    created = 0
    errors = 0

    for store, info in STORE_VISITS.items():
        print(f"\n{store} (visited by {info['visitor']}):")

        if info["deal_ids"]:
            for did in info["deal_ids"]:
                ok = update_deal_stage(hs, did, TARGET_STAGE, dry_run)
                if ok:
                    updated += 1
                else:
                    errors += 1
        else:
            deal_id = create_deal(hs, store, info["visitor"], TARGET_STAGE, dry_run)
            if deal_id:
                created += 1
            else:
                errors += 1

    print(f"\n=== Summary ===")
    print(f"  Updated: {updated}")
    print(f"  Created: {created}")
    print(f"  Errors: {errors}")


if __name__ == "__main__":
    main()
