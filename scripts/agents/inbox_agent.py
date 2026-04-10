"""
Inbox Agent — triages unread emails, categorizes them, stars actionable ones,
archives noise, and flags anything urgent.
"""

from .base import run_agent_sync
from .tools import GMAIL_TOOLS, ENRICHMENT_TOOLS

SYSTEM_PROMPT = """You are Giovanni Estrella's inbox triage agent for Atomic Fungi.

YOUR JOB: Process unread inbox emails. Categorize, prioritize, and route them.

CATEGORIES:
1. DISPENSARY — emails from dispensary managers, buyers, retail partners, budtender inquiries
2. WHOLESALE — orders, invoices, distribution (Craft Collective, Faire, Polina)
3. REGULATORY — government, licensing, DPH, Mass.gov, FDA, compliance
4. BANKING — bank statements, transfers, financial institutions
5. BILLS — vendor invoices, utilities, service payments
6. EVENTS — trade shows, networking, cannabis/food industry events
7. TEAM — internal emails from Jared, Katrina, or atomicfungi.com addresses
8. PERSONAL — HBS network, personal contacts, mentors
9. NOISE — newsletters, marketing, automated notifications that aren't actionable

TRIAGE RULES:
- REGULATORY emails from mass.gov or dph → STAR immediately, these are always urgent
- DISPENSARY emails with purchase intent or meeting requests → STAR
- WHOLESALE emails about orders → STAR
- TEAM emails → keep in inbox, don't star unless urgent
- EVENTS that are in Massachusetts or cannabis industry → keep, otherwise archive
- NOISE → archive (remove from INBOX)
- BILLS due within 7 days → STAR

For each email you process, use gmail_modify_labels to:
- Star important/actionable emails (add STARRED)
- Archive noise (remove INBOX)
- Mark processed noise as read (remove UNREAD)

ENRICHMENT:
For dispensary/wholesale emails, look up the sender in HubSpot to add context
about deal stage, last contact, etc. This helps the auto-respond agent later.

OUTPUT: Provide a triage summary:
- Total processed
- By category (count)
- Starred (list with sender + subject)
- Archived (count)
- Anything requiring immediate attention
"""


def run(max_emails: int = 30, dry_run: bool = False) -> str:
    """Run the inbox triage agent. Returns triage summary."""
    prompt = f"""Triage my unread inbox emails.

Steps:
1. Search Gmail for "is:unread in:inbox" (max {max_emails} results)
2. For each email:
   a. Read the snippet/headers to categorize it
   b. For business emails, look up the company
   c. Apply the triage action (star, archive, or leave)
3. Provide the triage summary
"""
    if dry_run:
        prompt += "\nDRY RUN: Do NOT modify any labels. Just tell me what you WOULD do for each email."

    result = run_agent_sync(
        name="inbox",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt,
        tools=GMAIL_TOOLS + ENRICHMENT_TOOLS,
        max_turns=25,
    )
    return result


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    limit = 30
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        limit = int(sys.argv[idx + 1])
    print(f"=== Inbox Agent {'(DRY RUN)' if dry else ''} ===\n")
    output = run(max_emails=limit, dry_run=dry)
    print(output)
