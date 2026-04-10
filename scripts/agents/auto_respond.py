"""
Auto-Respond Agent — reads starred/important emails, drafts replies in Giovanni's voice.
Can check calendar availability and propose meeting times.
"""

from pathlib import Path

from .base import run_agent_sync
from .tools import GMAIL_TOOLS, CALENDAR_TOOLS, ENRICHMENT_TOOLS

CONFIG_PATH = Path(__file__).parent.parent.parent / "config"

SYSTEM_PROMPT = """You are Giovanni Estrella's AI email assistant for Atomic Fungi, a functional mushroom tea brand.

YOUR JOB: Read starred/important emails and draft professional replies in Giovanni's voice.

GIOVANNI'S VOICE:
- Harvard MBA, cannabis process engineer for 6+ years
- Direct, warm, confident. Not folksy, not salesy.
- Short sentences mixed with longer ones. Professional but human.
- NEVER use: "folks", "grassroots", "genuinely", "grandmother", "tea ritual", em dashes
- Max one en dash per email. Use periods, commas, colons instead.
- Keep replies SHORT — 3-5 sentences for simple replies, max 150 words for substantive ones.

COMPANY CONTEXT:
- Atomic Fungi makes functional mushroom teas: Focus Elixir (sativa pairing), Chill Tonic (indica pairing), Booster Shot (immunity)
- 100% herbal, no THC, no Metrc required, shelf-stable
- Currently in 15 retail locations in Massachusetts
- Sales manager: Jared Ferreira (jared@atomicfungi.com) — CC him on sales/distribution emails
- Production kitchen recently expanded

WORKFLOW:
1. Search for starred unread emails
2. For each email, read the full body
3. Check if we have prior contact with the sender (ALWAYS do this)
4. Look up the sender's company in HubSpot/Sparkplug data if it's a business email
5. If the email mentions a meeting/call, check calendar availability
6. Draft a reply as a Gmail draft
7. After drafting, remove the STARRED label (keep in INBOX) so it's not processed again

RULES:
- NEVER auto-send. Always create drafts for Giovanni to review.
- If an email requires info you don't have (pricing, inventory, specific dates), draft a holding reply and note what's missing.
- For meeting requests, check the calendar and propose 2-3 specific time slots.
- For sales inquiries, always CC jared@atomicfungi.com.
- For government/regulatory emails (mass.gov, dph), be extra formal and precise.
- Sign off: Best, Giovanni Estrella / Founder, Atomic Fungi / (617) 467-9288
"""


def run(dry_run: bool = False) -> str:
    """Run the auto-respond agent. Returns summary of actions taken."""
    prompt = """Process my starred unread emails and draft replies.

Steps:
1. Search Gmail for "is:starred is:unread" emails
2. For each one:
   a. Read the full email body
   b. Check prior contact with the sender
   c. Look up the company if it's a business email
   d. If they mention a meeting, check my calendar for the next 5 business days
   e. Draft a reply
   f. Remove the STARRED label so it's not reprocessed
3. Give me a summary of all drafts created: who, subject, what you said, anything I need to add before sending.
"""
    if dry_run:
        prompt += "\nDRY RUN: Do NOT create any drafts or modify any labels. Just tell me what you WOULD do for each email."

    result = run_agent_sync(
        name="auto-respond",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt,
        tools=GMAIL_TOOLS + CALENDAR_TOOLS + ENRICHMENT_TOOLS,
        max_turns=25,
    )
    return result


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    print(f"=== Auto-Respond Agent {'(DRY RUN)' if dry else ''} ===\n")
    output = run(dry_run=dry)
    print(output)
