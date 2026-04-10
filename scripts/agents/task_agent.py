"""
Task Agent — manages tasks.json, nags daily on overdue items, creates tasks from emails.
Escalates urgency over time: day 1 reminder, day 3 urgent, day 7 critical.
"""

from .base import run_agent_sync
from .tools import TASK_TOOLS, GMAIL_TOOLS

SYSTEM_PROMPT = """You are the Atomic Fungi Task Manager agent. Your job is to keep Giovanni and his team on track.

YOUR RESPONSIBILITIES:
1. Review all open/in_progress tasks daily
2. Nag on overdue tasks with escalating urgency
3. Scan recent emails for action items that should become tasks
4. Update task status when evidence suggests completion
5. Generate a daily task status report

ESCALATION RULES:
- 0 days overdue: "Reminder: this is due today"
- 1-2 days overdue: "This task is overdue. Please prioritize."
- 3-6 days overdue: "URGENT: This is X days overdue and blocking progress."
- 7+ days overdue: "CRITICAL: This has been overdue for X days. This needs immediate attention or a decision to reschedule."
- If nag_count >= 5, include: "This has been nagged X times. Consider: is this still the right priority, or should we reschedule/delegate?"

TASK CREATION FROM EMAILS:
When scanning emails, create tasks for:
- Explicit requests ("can you send...", "please provide...", "we need...")
- Deadlines mentioned ("by Friday", "due April 15")
- Follow-up promises Giovanni made ("I'll send that over", "let me get back to you")
- Government/regulatory deadlines (these are always critical priority)

Always set realistic due dates. If no date is mentioned, default to 3 business days out.

ACTIVE PROJECTS:
- label_redesign: FDA label compliance for wholesale certificate. BLOCKING. D'Avon Wilson at Mass DPH.
- dispensary_outreach: 63 rewritten drafts sitting in Gmail. Need to be reviewed and sent.
- Add new projects as needed when tasks don't fit existing ones.

OUTPUT: Provide a structured report with:
1. OVERDUE tasks (with escalation level)
2. DUE TODAY
3. UPCOMING (next 7 days)
4. NEW TASKS CREATED (from email scan)
5. COMPLETED since last run
"""


def run(scan_emails: bool = True, dry_run: bool = False) -> str:
    """Run the task agent. Returns structured task report."""
    prompt_parts = [
        "Review all tasks and generate today's task status report.",
        "",
        "Steps:",
        "1. List all tasks (all statuses)",
        "2. For each open/in_progress task that is overdue, record a nag",
        "3. Generate the escalation report",
    ]

    if scan_emails:
        prompt_parts.extend([
            "4. Search Gmail for recent emails (last 24 hours) that might contain action items:",
            "   - Search: 'newer_than:1d to:giovanni@atomicfungi.com'",
            "   - Read each email and identify any tasks or follow-ups needed",
            "   - Create new tasks for any action items found",
            "5. Check if any emails suggest a task has been completed (e.g., 'labels have been reprinted')",
        ])

    if dry_run:
        prompt_parts.append("\nDRY RUN: Do NOT modify any tasks or create new ones. Just report what you WOULD do.")

    prompt_parts.append("\nProvide the full structured report at the end.")

    result = run_agent_sync(
        name="task-agent",
        system_prompt=SYSTEM_PROMPT,
        user_prompt="\n".join(prompt_parts),
        tools=TASK_TOOLS + GMAIL_TOOLS,
        max_turns=20,
    )
    return result


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    no_email = "--no-email-scan" in sys.argv
    print(f"=== Task Agent {'(DRY RUN)' if dry else ''} ===\n")
    output = run(scan_emails=not no_email, dry_run=dry)
    print(output)
