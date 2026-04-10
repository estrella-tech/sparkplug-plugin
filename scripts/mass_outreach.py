#!/usr/bin/env python3
"""
Atomic Fungi Mass Email Outreach — drafts emails for EVERY company in the CRM.

Three tiers:
  Tier 1: CTA email submissions from Sparkplug (warmest — budtenders gave us the manager's email)
  Tier 2: Previously contacted companies (follow-up)
  Tier 3: Never contacted companies (cold outreach)

Usage:
    python scripts/mass_outreach.py --dry-run          # preview
    python scripts/mass_outreach.py --tier 1           # only Tier 1
    python scripts/mass_outreach.py --tier 2           # only Tier 2
    python scripts/mass_outreach.py --tier 3           # only Tier 3
    python scripts/mass_outreach.py --limit 10         # first 10 only
    python scripts/mass_outreach.py                    # full run
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from email_utils import (
    get_gmail_service, create_gmail_draft, load_enrichment_data,
    fuzzy_match, load_prompt_template, EXPORTS_DIR,
)

PROJECT_ROOT = Path(__file__).parent.parent

# Domains to skip (internal, non-cannabis, or generic)
SKIP_DOMAINS = {
    "atomicfungi.com", "sparkplug.app", "gmail.com", "yahoo.com", "hotmail.com",
    "outlook.com", "icloud.com", "hubspot.com", "google.com", "mass.gov",
    "gong.io", "adobe.com", "salesforce.com", "linkedin.com", "twitter.com",
}

# Non-cannabis companies to exclude
SKIP_COMPANIES = {
    "whole foods market", "gnc", "sprouts", "hy-vee", "natural grocers",
    "earth fare", "fresh thyme market", "gong", "adobe", "hubspot",
    "inner-city muslim action network",
}

# About me paragraphs — VERBATIM from gold_standard_email.txt
ABOUT_ME = """A little bit about me and us:

I founded Atomic Fungi after a personal health scare during my time at Harvard Business School. I was dealing with some serious health issues and turned to medicinal mushrooms almost out of desperation. They changed my life. My energy, focus, and overall wellbeing improved dramatically in a short time. That experience lit a fire in me to bring functional mushrooms to a community I already knew and loved: cannabis.

I've been in the cannabis industry for over 6 years as a process engineer at some of the largest MSOs in the country, and a consumer for much longer than that. I wrote about the full journey in this substack piece titled, "How Weed Got Me into Harvard, and How Mushroom Tea Got me Through It."

Atomic Fungi makes functional mushroom teas designed as a wellness complement for cannabis consumers. We're currently in 15 retail locations and growing quickly! We just moved into a much larger production kitchen and are expanding the team to keep up with demand. Our teas are 100% herbal (no THC, no Metrc required), shelf-stable, and pair naturally with cannabis: Focus Elixir for sativas, Chill Tonic for indicas, Booster Shot for immunity."""

# Standard pitch block
PITCH = """We'd love to schedule a pop-up at your location. I've attached our sales sheet for reference. A case of tea is $112.50 (15 boxes), and retailers see 50% margins. A typical first order looks like this: one case of each tea. We do a pop-up the same day to help you sell 1-2 cases, and it helps your budtenders understand how to talk about the product with customers.

We can also do a pop-up where we sell the products ourselves and charge at our table, before you commit to carrying the product. Ideal Craft Cannabis did this and they ended up buying 4 cases of tea after the tasting was finished because of how excited their customers were.

In case you weren't aware, as of December 11, 2025, it is now legal for Massachusetts dispensaries to carry shelf-stable foods and beverages (935 CMR 500.000). This makes it the perfect opportunity to pair cannabis with complementary wellness products that are growing in demand.

We can come in the morning or afternoon, any day of the week. Whatever works best for your team."""

SIGN_OFF = """I've CC'd Jared Ferreira, my sales manager. Looking forward to hearing from you.

Best,
Giovanni Estrella
Founder, Atomic Fungi
(617) 467-9288"""


# ---------------------------------------------------------------------------
# Phase 0: Load all data sources
# ---------------------------------------------------------------------------

def load_cta_emails() -> dict:
    """Parse CTA responses for valid email submissions. Returns {email: {retailer, budtender}}."""
    path = EXPORTS_DIR / "cta_responses.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text()).get("data", [])
    emails = {}
    for r in data:
        resp = str(r.get("response", "")).strip()
        retailer = r.get("retailer", "")
        employee = r.get("employee", "")
        # Must look like an email
        if "@" in resp and "." in resp and len(resp) < 80:
            email = resp.split()[0].strip().lower().rstrip(".")
            if "@" in email and "." in email.split("@")[-1]:
                domain = email.split("@")[-1]
                if domain not in SKIP_DOMAINS:
                    if email not in emails:
                        emails[email] = {"retailer": retailer, "budtender": employee}
    return emails


def load_apex_contacts() -> dict:
    """Load Apex contacts indexed by domain. Returns {domain: [{name, email, title, phone}]}."""
    path = EXPORTS_DIR / "apex_contacts_deduped.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    by_domain = {}
    for c in data:
        email = c.get("email", "").strip().lower()
        if not email or "@" not in email:
            continue
        domain = email.split("@")[-1]
        if domain in SKIP_DOMAINS:
            continue
        by_domain.setdefault(domain, []).append({
            "name": c.get("name", ""),
            "email": email,
            "title": c.get("title", ""),
            "phone": c.get("phone", ""),
        })
    return by_domain


def load_hs_contacts() -> dict:
    """Load HubSpot contacts indexed by domain. Returns {domain: [email]}."""
    path = EXPORTS_DIR / "hubspot_contacts_snapshot.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    by_domain = {}
    for email in data.get("emails", []):
        email = email.strip().lower()
        if "@" not in email:
            continue
        domain = email.split("@")[-1]
        if domain not in SKIP_DOMAINS:
            by_domain.setdefault(domain, []).append(email)
    return by_domain


def load_companies() -> tuple:
    """Load HubSpot companies, split into contacted and not contacted.
    Returns (contacted_list, not_contacted_list).
    """
    path = EXPORTS_DIR / "hubspot_companies.json"
    if not path.exists():
        return [], []
    data = json.loads(path.read_text()).get("data", [])
    contacted = []
    not_contacted = []
    for c in data:
        domain = (c.get("domain") or "").strip().lower()
        name = (c.get("name") or "").strip()
        last = (c.get("last_contacted") or "").strip()
        if not domain or domain in SKIP_DOMAINS:
            continue
        if name.lower() in SKIP_COMPANIES:
            continue
        entry = {"name": name, "domain": domain, "last_contacted": last}
        if last:
            contacted.append(entry)
        else:
            not_contacted.append(entry)
    return contacted, not_contacted


def load_already_drafted() -> set:
    """Load store names already drafted from logs. Returns set of lowercase names."""
    names = set()
    for log_name in ["followup_log.json", "rewrite_log.json", "mass_outreach_log.json"]:
        path = EXPORTS_DIR / log_name
        if path.exists():
            data = json.loads(path.read_text())
            if isinstance(data, list):
                for entry in data:
                    for key in ("store", "company", "to"):
                        val = entry.get(key, "")
                        if val:
                            names.add(val.strip().lower())
    return names


# ---------------------------------------------------------------------------
# Phase 1: Build master send list with dedup and email resolution
# ---------------------------------------------------------------------------

PREFERRED_TITLES = {"gm", "general manager", "buyer", "retail buyer", "ceo",
                    "coo", "owner", "manager", "director", "inventory lead"}
AVOID_NAMES = {"accounting", "ap", "billing", "bookkeeping", "bookkeeper"}


def pick_best_apex_contact(contacts: list) -> dict:
    """Pick the best contact from Apex — prefer titled/named people over generic."""
    # First pass: anyone with a preferred title
    for c in contacts:
        title = c.get("title", "").strip().lower()
        if title and any(t in title for t in PREFERRED_TITLES):
            return c
    # Second pass: named person (not ACCOUNTING, AP, etc.)
    for c in contacts:
        name = c.get("name", "").strip().upper()
        if name and name not in {n.upper() for n in AVOID_NAMES}:
            return c
    # Fallback: first contact
    return contacts[0] if contacts else None


def resolve_email(company_name: str, domain: str, cta_emails: dict,
                  apex_by_domain: dict, hs_by_domain: dict,
                  enrichment: dict) -> tuple:
    """Resolve recipient email for a company.
    Returns (email, contact_name, source) or (None, None, None).
    """
    # 1. Check CTA responses by retailer name match
    for email, info in cta_emails.items():
        retailer = info["retailer"].lower()
        if (company_name.lower() in retailer or retailer in company_name.lower() or
            (len(company_name.split()[0]) > 3 and company_name.split()[0].lower() in retailer)):
            return email, info["budtender"], "cta"

    # 2. Check Apex contacts by domain
    if domain in apex_by_domain:
        best = pick_best_apex_contact(apex_by_domain[domain])
        if best:
            return best["email"], best["name"], "apex"

    # 3. Check HubSpot contacts by domain
    if domain in hs_by_domain:
        return hs_by_domain[domain][0], "", "hubspot"

    # 4. Fallback: info@domain
    return f"info@{domain}", "", "fallback"


def is_cannabis_company(name, domain, apex_by_domain, enrichment):
    """Check if a company is cannabis-related (in Apex or Sparkplug)."""
    if domain in apex_by_domain:
        return True
    bt_retailers = enrichment.get("budtenders_by_retailer", {})
    key, score = fuzzy_match(name, bt_retailers, threshold=0.5)
    if key:
        return True
    # Check HubSpot deals
    deals = enrichment.get("deals_by_company", {})
    key, score = fuzzy_match(name, deals, threshold=0.5)
    if key:
        return True
    return False


def build_master_list(cta_emails, contacted, not_contacted,
                      apex_by_domain, hs_by_domain, enrichment,
                      already_drafted, tier_filter=None):
    """Build the deduplicated master send list across all tiers."""
    master = []
    covered_domains = set()
    covered_names = set()

    # --- Tier 1: CTA email submissions ---
    if tier_filter is None or tier_filter == 1:
        for email, info in cta_emails.items():
            retailer = info["retailer"]
            domain = email.split("@")[-1]
            if retailer.lower() in already_drafted:
                continue
            master.append({
                "tier": 1,
                "company": retailer,
                "to_email": email,
                "contact_name": "",
                "budtender": info["budtender"],
                "source": "cta",
                "domain": domain,
            })
            covered_domains.add(domain)
            covered_names.add(retailer.lower())

    # --- Tier 2: Previously contacted ---
    if tier_filter is None or tier_filter == 2:
        for c in contacted:
            name = c["name"]
            domain = c["domain"]
            if name.lower() in covered_names or name.lower() in already_drafted:
                continue
            if domain in covered_domains:
                continue
            if not is_cannabis_company(name, domain, apex_by_domain, enrichment):
                continue
            email, contact, source = resolve_email(
                name, domain, cta_emails, apex_by_domain, hs_by_domain, enrichment
            )
            if not email:
                continue
            # Get budtender data if available
            bt_key, _ = fuzzy_match(name, enrichment.get("budtenders_by_retailer", {}), threshold=0.5)
            bt_name = ""
            if bt_key:
                bt_data = enrichment["budtenders_by_retailer"][bt_key]
                bt_name = sorted(bt_data.keys(), key=lambda x: sum(bt_data[x].values()), reverse=True)[0]
            master.append({
                "tier": 2,
                "company": name,
                "to_email": email,
                "contact_name": contact,
                "budtender": bt_name,
                "source": source,
                "domain": domain,
                "last_contacted": c.get("last_contacted", ""),
            })
            covered_domains.add(domain)
            covered_names.add(name.lower())

    # --- Tier 3: Never contacted ---
    if tier_filter is None or tier_filter == 3:
        # Sort: those with Sparkplug engagement first
        bt_retailers = enrichment.get("budtenders_by_retailer", {})
        def sort_key(c):
            key, _ = fuzzy_match(c["name"], bt_retailers, threshold=0.5)
            return 0 if key else 1
        sorted_nc = sorted(not_contacted, key=sort_key)

        for c in sorted_nc:
            name = c["name"]
            domain = c["domain"]
            if name.lower() in covered_names or name.lower() in already_drafted:
                continue
            if domain in covered_domains:
                continue
            if not is_cannabis_company(name, domain, apex_by_domain, enrichment):
                continue
            email, contact, source = resolve_email(
                name, domain, cta_emails, apex_by_domain, hs_by_domain, enrichment
            )
            if not email:
                continue
            bt_key, _ = fuzzy_match(name, bt_retailers, threshold=0.5)
            bt_name = ""
            if bt_key:
                bt_data = bt_retailers[bt_key]
                bt_name = sorted(bt_data.keys(), key=lambda x: sum(bt_data[x].values()), reverse=True)[0]
            master.append({
                "tier": 3,
                "company": name,
                "to_email": email,
                "contact_name": contact,
                "budtender": bt_name,
                "source": source,
                "domain": domain,
            })
            covered_domains.add(domain)
            covered_names.add(name.lower())

    return master


# ---------------------------------------------------------------------------
# Phase 2: Email templates
# ---------------------------------------------------------------------------

def build_tier1_email(entry: dict) -> tuple:
    """Build Tier 1 email (CTA submission — warmest). Returns (subject, body)."""
    store = entry["company"]
    budtender = entry["budtender"]
    subject = f"{budtender} recommended we connect - Atomic Fungi x {store}"
    body = f"""Hi there,

I'm reaching out because {budtender} from your team at {store} has been engaging with our Sparkplug content and shared your contact information. That kind of enthusiasm from the floor is exactly what gets us excited to partner with a store.

{PITCH}

-----

{ABOUT_ME}

{SIGN_OFF}"""
    return subject, body


def build_tier2_email(entry: dict) -> tuple:
    """Build Tier 2 email (follow-up — short). Returns (subject, body)."""
    company = entry["company"]
    budtender = entry.get("budtender", "")
    bt_line = ""
    if budtender:
        bt_line = f"\n\nI also wanted to mention that {budtender} from your team has been engaging with our Sparkplug content, which shows real interest from the floor."

    subject = f"Checking in - Atomic Fungi x {company}"
    body = f"""Hi there,

I wanted to follow up on our earlier outreach. Atomic Fungi makes functional mushroom teas designed as a wellness complement for cannabis consumers, and I think {company} would be a great fit.{bt_line}

In case you weren't aware, as of December 11, 2025, it is now legal for Massachusetts dispensaries to carry shelf-stable foods and beverages (935 CMR 500.000). This makes it the perfect time to explore complementary wellness products.

{PITCH}

-----

{ABOUT_ME}

{SIGN_OFF}"""
    return subject, body


def build_tier3_email(entry: dict) -> tuple:
    """Build Tier 3 email (cold outreach). Returns (subject, body)."""
    company = entry["company"]
    budtender = entry.get("budtender", "")

    if budtender:
        subject = f"{budtender} from your team has been engaging with Atomic Fungi"
        opener = f"""I'm reaching out because {budtender} from your team at {company} has been engaging with our Sparkplug content. That kind of enthusiasm from the floor is exactly what gets us excited to partner with a store."""
    else:
        subject = f"Functional mushroom teas for {company} - Atomic Fungi"
        opener = f"""I wanted to reach out because I think {company} would be a great fit for our functional mushroom teas."""

    body = f"""Hi there,

{opener}

{PITCH}

-----

{ABOUT_ME}

{SIGN_OFF}"""
    return subject, body


# ---------------------------------------------------------------------------
# Phase 3: Create drafts + log
# ---------------------------------------------------------------------------

def create_drafts(master_list: list, dry_run: bool = False, limit: int = None):
    """Create Gmail drafts for the master list. Returns results list."""
    if limit:
        master_list = master_list[:limit]

    if not dry_run:
        service = get_gmail_service()
    else:
        service = None

    results = []
    needs_review = []

    for i, entry in enumerate(master_list):
        tier = entry["tier"]
        company = entry["company"]
        to_email = entry["to_email"]
        source = entry["source"]

        # Build email based on tier
        if tier == 1:
            subject, body = build_tier1_email(entry)
        elif tier == 2:
            subject, body = build_tier2_email(entry)
        else:
            subject, body = build_tier3_email(entry)

        if dry_run:
            print(f"  [{i+1}/{len(master_list)}] [T{tier}] {company}")
            print(f"    To: {to_email} (via {source})")
            print(f"    Subject: {subject}")
            if entry.get("budtender"):
                print(f"    Budtender: {entry['budtender']}")
            result = {"tier": tier, "company": company, "to": to_email,
                      "source": source, "subject": subject, "status": "dry_run"}
        else:
            try:
                draft_id = create_gmail_draft(service, to_email, subject, body)
                print(f"  [{i+1}/{len(master_list)}] [T{tier}] {company} -> {to_email} ({source}) -- {draft_id}")
                result = {"tier": tier, "company": company, "to": to_email,
                          "source": source, "subject": subject, "draft_id": draft_id,
                          "status": "created", "timestamp": datetime.now(timezone.utc).isoformat()}
                time.sleep(1)
            except Exception as e:
                print(f"  [{i+1}/{len(master_list)}] [T{tier}] ERROR: {company} -- {e}")
                result = {"tier": tier, "company": company, "to": to_email,
                          "source": source, "status": f"error: {e}"}

        results.append(result)
        if source == "fallback":
            needs_review.append({"company": company, "email": to_email, "tier": tier})

    return results, needs_review


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    tier_filter = None
    limit = None

    if "--tier" in args:
        idx = args.index("--tier")
        tier_filter = int(args[idx + 1])
    if "--limit" in args:
        idx = args.index("--limit")
        limit = int(args[idx + 1])

    print("=" * 60)
    print("ATOMIC FUNGI MASS OUTREACH")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    if tier_filter:
        print(f"Tier: {tier_filter} only")
    if limit:
        print(f"Limit: {limit}")
    print("=" * 60)
    print()

    # Phase 0: Load data
    print("[Phase 0] Loading data sources...")
    enrichment = load_enrichment_data()
    cta_emails = load_cta_emails()
    apex_by_domain = load_apex_contacts()
    hs_by_domain = load_hs_contacts()
    contacted, not_contacted = load_companies()
    already_drafted = load_already_drafted()

    print(f"  CTA emails: {len(cta_emails)}")
    print(f"  Apex domains: {len(apex_by_domain)}")
    print(f"  HubSpot contact domains: {len(hs_by_domain)}")
    print(f"  Companies (contacted): {len(contacted)}")
    print(f"  Companies (not contacted): {len(not_contacted)}")
    print(f"  Already drafted: {len(already_drafted)}")
    print()

    # Phase 1: Build master list
    print("[Phase 1] Building master send list...")
    master = build_master_list(
        cta_emails, contacted, not_contacted,
        apex_by_domain, hs_by_domain, enrichment,
        already_drafted, tier_filter
    )
    tier_counts = {}
    source_counts = {}
    for entry in master:
        tier_counts[entry["tier"]] = tier_counts.get(entry["tier"], 0) + 1
        source_counts[entry["source"]] = source_counts.get(entry["source"], 0) + 1

    print(f"  Total to send: {len(master)}")
    for t in sorted(tier_counts):
        print(f"    Tier {t}: {tier_counts[t]}")
    for s in sorted(source_counts):
        print(f"    Source '{s}': {source_counts[s]}")
    print()

    if not master:
        print("Nothing to send!")
        return

    # Phase 2-3: Generate and create drafts
    print(f"[Phase 2-3] {'Previewing' if dry_run else 'Creating'} drafts...")
    results, needs_review = create_drafts(master, dry_run=dry_run, limit=limit)
    print()

    # Save logs
    if not dry_run:
        log_path = EXPORTS_DIR / "mass_outreach_log.json"
        existing = []
        if log_path.exists():
            existing = json.loads(log_path.read_text())
        existing.extend(results)
        log_path.write_text(json.dumps(existing, indent=2))
        print(f"  Log saved: {log_path}")

    if needs_review:
        review_path = EXPORTS_DIR / "needs_email_review.json"
        review_path.write_text(json.dumps(needs_review, indent=2))
        print(f"  Needs review: {review_path} ({len(needs_review)} entries)")

    # Summary
    created = sum(1 for r in results if r["status"] == "created")
    errors = sum(1 for r in results if r["status"].startswith("error"))
    dry = sum(1 for r in results if r["status"] == "dry_run")
    print(f"\n{'=' * 60}")
    print(f"Summary: {created} created, {dry} dry-run, {errors} errors")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
