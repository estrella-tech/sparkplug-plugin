"""
Research Agent — looks up company and contact social profiles (LinkedIn, Instagram).
Enriches outreach with intel on buyers, budtenders, and managers.
"""

from .base import run_agent_sync
from .tools import GMAIL_TOOLS, ENRICHMENT_TOOLS

SYSTEM_PROMPT = """You are a research assistant for Atomic Fungi, a functional mushroom tea brand.

YOUR JOB: Research dispensaries, cannabis retailers, and their key people. Find social media profiles and any useful intel for sales outreach.

FOR EACH COMPANY, FIND:
1. Company LinkedIn page URL
2. Company Instagram handle/URL
3. Company website (if not already known)
4. Any recent news or press about the company

FOR EACH PERSON (buyer, manager, budtender), FIND:
1. LinkedIn profile URL
2. Instagram handle (if public/findable)
3. Job title and role at the company
4. Any mutual connections or shared background with Giovanni (Harvard, cannabis industry, process engineering)

SEARCH STRATEGY:
- Search: "{person_name} {company_name} LinkedIn"
- Search: "{company_name} cannabis dispensary Massachusetts LinkedIn"
- Search: "{company_name} cannabis Instagram"
- Search: "{person_name} cannabis industry"
- If the person has a unique name, try just their name + LinkedIn

OUTPUT FORMAT:
For each company/person researched, provide a structured summary:
```
COMPANY: {name}
  LinkedIn: {url or "not found"}
  Instagram: {url or "not found"}
  Website: {url}
  Notes: {any useful intel}

  CONTACTS:
    {name} ({role})
      LinkedIn: {url or "not found"}
      Notes: {any relevant background}
```

RULES:
- Only report URLs you actually find and verify. Do not guess or fabricate URLs.
- Focus on Massachusetts cannabis dispensaries and retailers.
- Note any Harvard connections, cannabis industry experience, or wellness/mushroom interests.
- Keep notes concise and actionable for sales outreach.
"""


def run(companies: list[dict], dry_run: bool = False) -> str:
    """Research a list of companies and their contacts.

    Each company dict should have: name, contacts (list of {name, email, title})
    Returns structured research results.
    """
    # Build the research prompt
    prompt_parts = ["Research the following companies and their contacts. Find LinkedIn and Instagram profiles.\n"]

    for i, company in enumerate(companies):
        prompt_parts.append(f"\n--- Company {i+1}: {company['name']} ---")
        if company.get("domain"):
            prompt_parts.append(f"Website domain: {company['domain']}")
        if company.get("location"):
            prompt_parts.append(f"Location: {company['location']}")

        contacts = company.get("contacts", [])
        if contacts:
            prompt_parts.append("Contacts to research:")
            for c in contacts:
                name = c.get("name", "")
                title = c.get("title", "")
                email = c.get("email", "")
                prompt_parts.append(f"  - {name}" + (f" ({title})" if title else "") + (f" [{email}]" if email else ""))

        # Add budtender names if available
        budtenders = company.get("budtenders", [])
        if budtenders:
            prompt_parts.append("Budtenders (engaged on Sparkplug):")
            for bt in budtenders:
                prompt_parts.append(f"  - {bt}")

    if dry_run:
        prompt_parts.append("\nDRY RUN: Just list what you WOULD search for, don't actually search.")

    prompt_parts.append("\nProvide the structured research results for each company.")

    # Research agent gets WebSearch + WebFetch via Claude Code CLI built-in tools
    result = run_agent_sync(
        name="research",
        system_prompt=SYSTEM_PROMPT,
        user_prompt="\n".join(prompt_parts),
        tools=ENRICHMENT_TOOLS,  # lookup_company for HubSpot/Sparkplug cross-ref
        max_turns=30,
        extra_allowed_tools=["WebSearch", "WebFetch"],
    )
    return result


if __name__ == "__main__":
    import sys
    import json
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from email_utils import load_enrichment_data, fuzzy_match

    dry = "--dry-run" in sys.argv
    limit = 5
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        limit = int(sys.argv[idx + 1])

    # Load Apex contacts for research targets
    apex_path = Path(__file__).parent.parent.parent / "exports" / "apex_contacts_deduped.json"
    enrichment = load_enrichment_data()

    # Build company list from HubSpot deals at Tasting Done stage (highest priority)
    deals_path = Path(__file__).parent.parent.parent / "exports" / "hubspot_deals.json"
    if deals_path.exists():
        deals = json.loads(deals_path.read_text()).get("data", [])
        target_stages = {"Tasting Done", "Sampled", "Verbal Commitment"}
        targets = []
        seen = set()

        for d in deals:
            if d.get("stage_label") in target_stages:
                name = d["name"].split("—")[0].split("–")[0].strip()
                if name.lower() in seen:
                    continue
                seen.add(name.lower())

                company = {"name": name}

                # Get budtender data
                bt_key, _ = fuzzy_match(name, enrichment.get("budtenders_by_retailer", {}), threshold=0.4)
                if bt_key:
                    bt_data = enrichment["budtenders_by_retailer"][bt_key]
                    company["budtenders"] = sorted(bt_data.keys(), key=lambda x: sum(bt_data[x].values()), reverse=True)[:3]

                # Get Apex contacts
                if apex_path.exists():
                    apex = json.loads(apex_path.read_text())
                    contacts = []
                    for ac in apex:
                        for bn in ac.get("buyer_names", []):
                            if name.lower() in bn.lower() or bn.lower() in name.lower():
                                contacts.append({
                                    "name": ac.get("name", ""),
                                    "email": ac.get("email", ""),
                                    "title": ac.get("title", ""),
                                })
                                break
                    if contacts:
                        company["contacts"] = contacts[:5]

                targets.append(company)

        targets = targets[:limit]

        print(f"=== Research Agent {'(DRY RUN)' if dry else ''} ===")
        print(f"Researching {len(targets)} companies\n")

        output = run(targets, dry_run=dry)
        print(output)
